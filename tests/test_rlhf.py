"""RLHF：Bradley-Terry 奖励模型、DPO 与序列级 PPO。

约定：token 9 是「礼貌词」。所有偏好数据都是「带 9 的回答优于不带 9 的回答」，
于是我们可以直接检查对齐是否学到了这条规律。
"""

from __future__ import annotations

import copy

import numpy as np
import pytest

from dive.autograd import Tensor, no_grad
from dive.rlhf import (
    Preference,
    SequenceRewardModel,
    bradley_terry_loss,
    dpo_loss,
    ppo_train,
    preference_accuracy,
    preference_margin,
    reward_accuracy,
    sequence_logprob,
    train_dpo,
    train_reward_model,
)
from dive.transformer import TinyLM, TinyLMConfig

VOCAB = 12
POLITE = 9


def build_preferences() -> list[Preference]:
    rng = np.random.default_rng(0)
    preferences = []
    for _ in range(8):
        prompt = [1] + list(rng.integers(2, 6, size=2))
        filler = int(rng.integers(2, 6))
        preferences.append(
            Preference(prompt=[int(t) for t in prompt], chosen=[POLITE, filler], rejected=[filler, filler])
        )
    return preferences


def build_policy(seed: int = 0) -> TinyLM:
    return TinyLM(
        TinyLMConfig(vocab_size=VOCAB, dim=16, n_layers=1, n_heads=2, max_seq_len=24, seed=seed)
    )


# ----------------------------------------------------------------------
# 偏好数据
# ----------------------------------------------------------------------
def test_preference_builds_full_sequences():
    pref = Preference(prompt=[1, 2], chosen=[9, 3], rejected=[3, 3])
    assert pref.chosen_sequence == [1, 2, 9, 3]
    assert pref.rejected_sequence == [1, 2, 3, 3]


# ----------------------------------------------------------------------
# 奖励模型
# ----------------------------------------------------------------------
def test_bradley_terry_loss_matches_formula():
    chosen = Tensor(np.array([2.0, 0.5]))
    rejected = Tensor(np.array([1.0, 0.5]))
    expected = -np.mean(np.log(1 / (1 + np.exp(-np.array([1.0, 0.0])))))
    assert bradley_terry_loss(chosen, rejected).item() == pytest.approx(expected)


def test_bradley_terry_loss_rewards_larger_margin():
    small = bradley_terry_loss(Tensor(np.array([0.1])), Tensor(np.array([0.0])))
    large = bradley_terry_loss(Tensor(np.array([3.0])), Tensor(np.array([0.0])))
    assert large.item() < small.item()


def test_reward_model_output_shape_and_score():
    model = SequenceRewardModel(VOCAB, dim=8, hidden=16)
    rewards = model(np.array([[1, 2, 3], [4, 5, 6]]))
    assert rewards.shape == (2,)
    assert model.score([1, 2, 3]) == pytest.approx(rewards.data[0])


def test_train_reward_model_learns_the_preference():
    preferences = build_preferences()
    model = SequenceRewardModel(VOCAB, dim=8, hidden=16, seed=0)
    history = train_reward_model(model, preferences, epochs=80, lr=1e-2, verbose=False)

    assert history[-1]["loss"] < history[0]["loss"]
    assert history[-1]["accuracy"] == 1.0
    assert reward_accuracy(model, preferences) == 1.0


def test_reward_model_generalizes_to_an_unseen_prompt():
    preferences = build_preferences()
    model = SequenceRewardModel(VOCAB, dim=8, hidden=16, seed=0)
    train_reward_model(model, preferences, epochs=80, lr=1e-2, verbose=False)
    # 训练里没出现过的提示，礼貌回答依然应当得分更高
    assert model.score([1, 5, 5, POLITE, 4]) > model.score([1, 5, 5, 4, 4])


# ----------------------------------------------------------------------
# 对数似然
# ----------------------------------------------------------------------
def test_sequence_logprob_matches_manual_computation():
    policy = build_policy()
    ids = [1, 3, 4, POLITE, 2]
    prompt_len = 3

    value = sequence_logprob(policy, ids, prompt_len).item()

    with no_grad():
        log_probs = policy(np.array([ids[:-1]])).log_softmax(axis=-1).data[0]
    targets = ids[1:]
    expected = sum(log_probs[position, targets[position]] for position in range(prompt_len - 1, len(targets)))
    assert value == pytest.approx(expected)
    # 只统计回答部分：token 数 = 序列长 - 提示长
    assert len(ids) - prompt_len == 2


def test_sequence_logprob_is_differentiable():
    policy = build_policy()
    sequence_logprob(policy, [1, 2, 3, 4], prompt_len=2).backward()
    assert any(param.grad is not None for param in policy.parameters())


def test_sequence_logprob_requires_an_answer():
    policy = build_policy()
    with pytest.raises(ValueError):
        sequence_logprob(policy, [1, 2], prompt_len=2)


def test_preference_margin_and_accuracy_agree():
    policy = build_policy()
    preferences = build_preferences()
    margin = preference_margin(policy, preferences)
    accuracy = preference_accuracy(policy, preferences)
    assert 0.0 <= accuracy <= 1.0
    assert np.isfinite(margin)


# ----------------------------------------------------------------------
# DPO
# ----------------------------------------------------------------------
def test_dpo_loss_is_positive_and_zero_margin_gives_log2():
    policy = build_policy()
    reference = copy.deepcopy(policy)
    pref = build_preferences()[0]
    # 策略与参考完全相同时，两个对数比值都为 0，损失恰好是 -log σ(0) = log 2
    assert dpo_loss(policy, reference, pref, beta=0.1).item() == pytest.approx(np.log(2.0))


def test_train_dpo_increases_preference_margin():
    policy = build_policy()
    preferences = build_preferences()
    before_margin = preference_margin(policy, preferences)

    history = train_dpo(policy, preferences, beta=0.1, epochs=6, lr=3e-3, verbose=False)

    assert len(history) == 6
    assert history[-1]["margin"] > before_margin
    assert history[-1]["accuracy"] >= history[0]["accuracy"]
    assert history[-1]["loss"] < np.log(2.0)


def test_larger_beta_stays_closer_to_the_reference_policy():
    """β 是「离参考模型多远」的旋钮：β 越大，允许的偏移越小。"""
    preferences = build_preferences()
    margins = {}
    for beta in (0.02, 0.5):
        policy = build_policy()
        train_dpo(policy, preferences, beta=beta, epochs=6, lr=3e-3, verbose=False)
        margins[beta] = preference_margin(policy, preferences)
    assert margins[0.02] > margins[0.5]


# ----------------------------------------------------------------------
# PPO
# ----------------------------------------------------------------------
def test_ppo_train_runs_and_reports_reward_and_kl():
    policy = build_policy()
    reward_model = SequenceRewardModel(VOCAB, dim=8, hidden=16, seed=0)
    train_reward_model(reward_model, build_preferences(), epochs=40, lr=1e-2, verbose=False)

    history = ppo_train(
        policy,
        reward_model,
        prompts=[[1, 2, 3]],
        response_len=2,
        iterations=3,
        samples_per_prompt=3,
        inner_epochs=1,
        kl_coef=0.05,
        verbose=False,
        seed=0,
    )

    assert len(history) == 3
    assert set(history[0]) == {"iteration", "reward", "reward_std", "kl"}
    assert all(np.isfinite(record["reward"]) and np.isfinite(record["kl"]) for record in history)


def test_ppo_kl_penalty_keeps_the_policy_closer_to_the_reference():
    """KL 惩罚作用在奖励上：系数越大，策略偏离参考模型越少。"""
    prompts = [[1, 2, 3]]
    reward_model = SequenceRewardModel(VOCAB, dim=8, hidden=16, seed=0)
    train_reward_model(reward_model, build_preferences(), epochs=40, lr=1e-2, verbose=False)

    drift = {}
    for kl_coef in (0.0, 1.0):
        policy = build_policy()
        reference = copy.deepcopy(policy)
        ppo_train(
            policy,
            reward_model,
            prompts=prompts,
            response_len=2,
            iterations=4,
            samples_per_prompt=3,
            inner_epochs=1,
            lr=3e-3,
            kl_coef=kl_coef,
            verbose=False,
            seed=1,
        )
        shift = 0.0
        for (_, updated), (_, original) in zip(policy.named_parameters(), reference.named_parameters()):
            shift += float(np.abs(updated.data - original.data).sum())
        drift[kl_coef] = shift

    assert drift[1.0] < drift[0.0]
