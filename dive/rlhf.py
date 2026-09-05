"""人类偏好对齐：奖励模型、PPO 与 DPO。

对齐要解决的问题是"好回答"没有标准答案，只有相对偏好。三种做法在本模块
里都能跑通：

1. **奖励模型（RM）**：用 Bradley-Terry 模型把成对偏好变成一个打分函数，
   损失为 ``-log σ(r(chosen) - r(rejected))``；
2. **PPO**：把语言模型当策略，用 RM 打分做强化学习，靠裁剪比值稳定更新，
   并用与参考模型的 KL 惩罚防止"为了高分不说人话"（reward hacking）；
3. **DPO**：跳过 RM 与采样，直接把偏好数据变成一个分类损失
   ``-log σ(β[(logπ_c - logπ_ref_c) - (logπ_r - logπ_ref_r)])``，
   实现简单、训练稳定，是目前的主流选择。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .autograd import Tensor, no_grad
from .decoding import SamplingConfig, generate
from .nn import AdamW, Embedding, Linear, Module, clip_grad_norm
from .transformer import TinyLM

__all__ = [
    "Preference",
    "SequenceRewardModel",
    "bradley_terry_loss",
    "train_reward_model",
    "reward_accuracy",
    "sequence_logprob",
    "dpo_loss",
    "train_dpo",
    "ppo_train",
]


@dataclass
class Preference:
    """一条偏好数据：同一个提示下，``chosen`` 优于 ``rejected``。"""

    prompt: list[int]
    chosen: list[int]
    rejected: list[int]

    @property
    def chosen_sequence(self) -> list[int]:
        return self.prompt + self.chosen

    @property
    def rejected_sequence(self) -> list[int]:
        return self.prompt + self.rejected


class SequenceRewardModel(Module):
    """把整条序列打成一个标量分数的奖励模型。

    结构故意保持简单：词嵌入 -> 平均池化 -> MLP -> 标量。真实 RM 会复用
    策略模型的主干并只换一个标量头，但训练目标与本实现完全一致。
    """

    def __init__(self, vocab_size: int, dim: int = 32, hidden: int = 64, seed: int = 0) -> None:
        super().__init__()
        rng = np.random.default_rng(seed)
        self.embed = Embedding(vocab_size, dim, rng=rng)
        self.fc1 = Linear(dim, hidden, rng=rng)
        self.fc2 = Linear(hidden, 1, rng=rng)

    def forward(self, ids: np.ndarray) -> Tensor:
        ids = np.atleast_2d(np.asarray(ids, dtype=np.int64))
        hidden = self.embed(ids).mean(axis=1)
        return self.fc2(self.fc1(hidden).relu()).reshape(ids.shape[0])

    def score(self, ids: Sequence[int]) -> float:
        with no_grad():
            return float(self.forward(np.asarray([list(ids)], dtype=np.int64)).data[0])


def bradley_terry_loss(chosen_rewards: Tensor, rejected_rewards: Tensor) -> Tensor:
    """``-log σ(r_chosen - r_rejected)``，成对偏好的标准损失。"""
    margin = chosen_rewards - rejected_rewards
    return -(margin.sigmoid() + 1e-12).log().mean()


def train_reward_model(
    model: SequenceRewardModel,
    preferences: Sequence[Preference],
    epochs: int = 60,
    lr: float = 5e-3,
    pad_id: int = 0,
    verbose: bool = True,
    log_every: int = 20,
) -> list[dict[str, float]]:
    """在偏好数据上训练奖励模型，返回损失与成对准确率历史。"""
    from .training import pad_sequences

    optimizer = AdamW(model.trainable_parameters(), lr=lr)
    chosen = pad_sequences([p.chosen_sequence for p in preferences], pad_id)
    rejected = pad_sequences([p.rejected_sequence for p in preferences], pad_id)
    history: list[dict[str, float]] = []

    for epoch in range(1, epochs + 1):
        optimizer.zero_grad()
        loss = bradley_terry_loss(model(chosen), model(rejected))
        loss.backward()
        clip_grad_norm(model.trainable_parameters(), 1.0)
        optimizer.step()

        accuracy = reward_accuracy(model, preferences)
        history.append({"epoch": float(epoch), "loss": loss.item(), "accuracy": accuracy})
        if verbose and (epoch % log_every == 0 or epoch == 1):
            print(f"  epoch {epoch:3d} | BT loss {loss.item():.4f} | 成对准确率 {accuracy:.1%}")
    return history


def reward_accuracy(model: SequenceRewardModel, preferences: Sequence[Preference]) -> float:
    """奖励模型给 chosen 打分高于 rejected 的比例。"""
    correct = sum(
        1
        for pref in preferences
        if model.score(pref.chosen_sequence) > model.score(pref.rejected_sequence)
    )
    return correct / len(preferences)


# ----------------------------------------------------------------------
# 策略侧：DPO 与 PPO
# ----------------------------------------------------------------------
def sequence_logprob(model: TinyLM, ids: Sequence[int], prompt_len: int) -> Tensor:
    """回答部分的对数似然之和（保留计算图，可反向传播）。"""
    ids = np.asarray(list(ids), dtype=np.int64)
    if len(ids) <= prompt_len:
        raise ValueError("序列中没有回答部分")
    logits = model(ids[None, :-1])
    log_probs = logits.log_softmax(axis=-1)
    targets = ids[1:]
    positions = np.arange(prompt_len - 1, len(targets))
    picked = log_probs[(np.zeros_like(positions), positions, targets[positions])]
    return picked.sum()


def dpo_loss(
    policy: TinyLM,
    reference: TinyLM,
    preference: Preference,
    beta: float = 0.1,
) -> Tensor:
    """单条偏好的 DPO 损失。"""
    prompt_len = len(preference.prompt)
    policy_chosen = sequence_logprob(policy, preference.chosen_sequence, prompt_len)
    policy_rejected = sequence_logprob(policy, preference.rejected_sequence, prompt_len)
    with no_grad():
        ref_chosen = sequence_logprob(reference, preference.chosen_sequence, prompt_len).item()
        ref_rejected = sequence_logprob(reference, preference.rejected_sequence, prompt_len).item()

    logits = beta * ((policy_chosen - ref_chosen) - (policy_rejected - ref_rejected))
    return -(logits.sigmoid() + 1e-12).log()


def train_dpo(
    policy: TinyLM,
    preferences: Sequence[Preference],
    beta: float = 0.1,
    epochs: int = 20,
    lr: float = 1e-3,
    verbose: bool = True,
    log_every: int = 5,
) -> list[dict[str, float]]:
    """DPO 训练；参考模型是训练开始前策略的一份冻结副本。"""
    reference = copy.deepcopy(policy)
    for param in reference.parameters():
        param.requires_grad = False

    optimizer = AdamW(policy.trainable_parameters(), lr=lr)
    history: list[dict[str, float]] = []

    for epoch in range(1, epochs + 1):
        total_loss = 0.0
        for preference in preferences:
            optimizer.zero_grad()
            loss = dpo_loss(policy, reference, preference, beta=beta)
            loss.backward()
            clip_grad_norm(policy.trainable_parameters(), 1.0)
            optimizer.step()
            total_loss += loss.item()

        margin = preference_margin(policy, preferences)
        record = {
            "epoch": float(epoch),
            "loss": total_loss / len(preferences),
            "margin": margin,
            "accuracy": preference_accuracy(policy, preferences),
        }
        history.append(record)
        if verbose and (epoch % log_every == 0 or epoch == 1):
            print(
                f"  epoch {epoch:3d} | DPO loss {record['loss']:.4f} | "
                f"logp 间隔 {margin:+.3f} | 偏好准确率 {record['accuracy']:.1%}"
            )
    return history


def preference_margin(policy: TinyLM, preferences: Sequence[Preference]) -> float:
    """策略给 chosen 与 rejected 的平均对数似然之差。"""
    margins = []
    for pref in preferences:
        prompt_len = len(pref.prompt)
        with no_grad():
            chosen = sequence_logprob(policy, pref.chosen_sequence, prompt_len).item()
            rejected = sequence_logprob(policy, pref.rejected_sequence, prompt_len).item()
        margins.append(chosen - rejected)
    return float(np.mean(margins))


def preference_accuracy(policy: TinyLM, preferences: Sequence[Preference]) -> float:
    """策略给 chosen 更高似然的比例。"""
    correct = 0
    for pref in preferences:
        prompt_len = len(pref.prompt)
        with no_grad():
            chosen = sequence_logprob(policy, pref.chosen_sequence, prompt_len).item()
            rejected = sequence_logprob(policy, pref.rejected_sequence, prompt_len).item()
        correct += int(chosen > rejected)
    return correct / len(preferences)


def ppo_train(
    policy: TinyLM,
    reward_model: SequenceRewardModel,
    prompts: Sequence[Sequence[int]],
    response_len: int = 4,
    iterations: int = 30,
    samples_per_prompt: int = 4,
    lr: float = 1e-3,
    clip_ratio: float = 0.2,
    kl_coef: float = 0.05,
    inner_epochs: int = 2,
    temperature: float = 1.0,
    seed: int = 0,
    verbose: bool = True,
    log_every: int = 5,
) -> list[dict[str, float]]:
    """序列级 PPO。

    每轮：用当前策略采样若干回答 → 奖励模型打分 → 以"奖励 - 批次均值"为
    优势 → 用裁剪后的重要性比值做若干步更新，并对与参考策略的 KL 施加惩罚。

    生产级实现会做 token 级 GAE 与独立价值网络，但裁剪目标、KL 约束、
    优势归一化这三个决定训练是否稳定的要素，与此处一致。
    """
    reference = copy.deepcopy(policy)
    for param in reference.parameters():
        param.requires_grad = False

    optimizer = AdamW(policy.trainable_parameters(), lr=lr)
    rng = np.random.default_rng(seed)
    history: list[dict[str, float]] = []

    for iteration in range(1, iterations + 1):
        # --- rollout：用当前策略采样 ---
        episodes: list[tuple[list[int], int, float, float]] = []
        for prompt in prompts:
            prompt = [int(t) for t in prompt]
            for _ in range(samples_per_prompt):
                response = generate(
                    policy,
                    prompt,
                    max_new_tokens=response_len,
                    config=SamplingConfig(temperature=temperature),
                    rng=rng,
                )
                sequence = prompt + response
                reward = reward_model.score(sequence)
                with no_grad():
                    old_logprob = sequence_logprob(policy, sequence, len(prompt)).item()
                episodes.append((sequence, len(prompt), reward, old_logprob))

        rewards = np.array([episode[2] for episode in episodes])
        advantages = rewards - rewards.mean()
        if advantages.std() > 1e-8:
            advantages = advantages / advantages.std()

        # --- 多轮小步更新 ---
        for _ in range(inner_epochs):
            for (sequence, prompt_len, _, old_logprob), advantage in zip(episodes, advantages):
                optimizer.zero_grad()
                new_logprob = sequence_logprob(policy, sequence, prompt_len)
                ratio = (new_logprob - old_logprob).exp()
                unclipped = ratio * float(advantage)
                clipped = _clip(ratio, 1 - clip_ratio, 1 + clip_ratio) * float(advantage)
                surrogate = -_minimum(unclipped, clipped)

                ref_logprob = sequence_logprob(reference, sequence, prompt_len).item()
                kl = new_logprob - ref_logprob
                loss = surrogate + kl_coef * kl
                loss.backward()
                clip_grad_norm(policy.trainable_parameters(), 1.0)
                optimizer.step()

        record = {
            "iteration": float(iteration),
            "reward": float(rewards.mean()),
            "reward_std": float(rewards.std()),
        }
        history.append(record)
        if verbose and (iteration % log_every == 0 or iteration == 1):
            print(f"  iter {iteration:3d} | 平均奖励 {record['reward']:+.4f}")
    return history


def _clip(tensor: Tensor, low: float, high: float) -> Tensor:
    """可微裁剪：落在区间外时梯度为 0。"""
    inside = ((tensor.data >= low) & (tensor.data <= high)).astype(np.float64)
    clipped_value = np.clip(tensor.data, low, high)
    # tensor*inside 保留区间内的梯度；常数项补上被裁掉的部分
    return tensor * Tensor(inside) + Tensor(clipped_value - tensor.data * inside)


def _minimum(a: Tensor, b: Tensor) -> Tensor:
    """逐元素取较小者，梯度只流向被选中的一侧。"""
    a_selected = (a.data <= b.data).astype(np.float64)
    return a * Tensor(a_selected) + b * Tensor(1.0 - a_selected)
