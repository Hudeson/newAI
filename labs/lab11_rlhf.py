"""第 11 章实验：基于人类偏好的对齐（RM / PPO / DPO）。

"好回答"没有标准答案，只有相对偏好。本实验用一个两句话的客服助手，
把三条主流路线完整跑一遍：

* 实验 A：SFT 基线——模型学会了礼貌与生硬两种说法，各占一半；
* 实验 B：奖励模型——用 Bradley-Terry 损失把成对偏好压成一个打分函数；
* 实验 C：DPO——绕过 RM 与采样，直接优化偏好，并扫描 β 观察**对齐税**；
* 实验 D：PPO——用 RM 打分做策略优化，并对比有无 KL 惩罚的差别。

贯穿全章的核心指标有三个，缺一不可：
**礼貌率**（对齐目标达成度）、**多样性**（还剩多少种说法）、
**与参考模型的 KL**（跑偏了多远）。只看第一个，就会训出一个只会说
同一句话的模型。

用法::

    python -m labs.lab11_rlhf
"""

from __future__ import annotations

import argparse
import copy
import itertools

import numpy as np

from dive.decoding import SamplingConfig, generate
from dive.rlhf import (
    Preference,
    SequenceRewardModel,
    ppo_train,
    preference_margin,
    reward_accuracy,
    sequence_logprob,
    train_dpo,
    train_reward_model,
)
from dive.tokenizer import WordTokenizer
from dive.training import TrainConfig, sft_batch, train_causal_lm
from dive.transformer import TinyLM, TinyLMConfig

from ._common import bar, kv, section, timer

QUESTIONS = ["问:天气", "问:路线", "问:菜谱", "问:报错", "问:退款", "问:密码"]
POLITE_OPENERS = ["好的", "没问题", "当然"]
POLITE_BODIES = ["马上为您处理", "这就为您查询", "很高兴帮忙"]
RUDE_OPENERS = ["不知道", "别问了", "懒得说"]
RUDE_BODIES = ["自己查去", "没空", "问别人"]


class Bench:
    """把评测指标集中在一处，保证各方法用完全相同的口径比较。"""

    def __init__(self, tokenizer: WordTokenizer, reference: TinyLM, n_samples: int = 40) -> None:
        self.tokenizer = tokenizer
        self.reference = reference
        self.n_samples = n_samples
        self.polite_ids = set(tokenizer.encode(POLITE_OPENERS + POLITE_BODIES))
        self.prompts = [tokenizer.encode([question], bos=True) for question in QUESTIONS]

    def _samples(self, model: TinyLM, seed: int = 0) -> list[tuple[list[int], list[int]]]:
        rng = np.random.default_rng(seed)
        out = []
        for prompt in self.prompts:
            for _ in range(self.n_samples):
                out.append((prompt, generate(model, prompt, 2, SamplingConfig(temperature=1.0), rng=rng)))
        return out

    def report(self, model: TinyLM, seed: int = 0) -> dict[str, float]:
        samples = self._samples(model, seed)
        polite = float(np.mean([all(t in self.polite_ids for t in response) for _, response in samples]))
        diversity = len({tuple(response) for _, response in samples})
        drifts = []
        for prompt, response in samples[:: max(1, len(samples) // 60)]:
            sequence = prompt + response
            drifts.append(
                sequence_logprob(model, sequence, len(prompt)).item()
                - sequence_logprob(self.reference, sequence, len(prompt)).item()
            )
        return {"polite": polite, "diversity": float(diversity), "kl": float(np.mean(drifts))}

    def show(self, name: str, metrics: dict[str, float]) -> None:
        print(
            f"  {name:<22}{metrics['polite']:>8.1%}{int(metrics['diversity']):>10}"
            f"{metrics['kl']:>+11.2f}   {bar(metrics['polite'])}"
        )


def build_sft_model(tokenizer: WordTokenizer, epochs: int) -> TinyLM:
    """在礼貌与生硬各半的语料上做 SFT——这是所有对齐方法的共同起点。"""
    sequences, prompt_lengths = [], []
    for question in QUESTIONS:
        responses = list(itertools.product(POLITE_OPENERS, POLITE_BODIES)) + list(
            itertools.product(RUDE_OPENERS, RUDE_BODIES)
        )
        for opener, body in responses:
            prompt = tokenizer.encode([question], bos=True)
            sequences.append(prompt + tokenizer.encode([opener, body], eos=True))
            prompt_lengths.append(len(prompt))

    batch_size = 36
    batches = [
        sft_batch(sequences[i : i + batch_size], prompt_lengths[i : i + batch_size], tokenizer.pad_id)
        for i in range(0, len(sequences), batch_size)
    ]
    model = TinyLM(
        TinyLMConfig(vocab_size=tokenizer.vocab_size, dim=64, n_layers=2, n_heads=4, max_seq_len=16, seed=0)
    )
    train_causal_lm(model, batches, TrainConfig(epochs=epochs, lr=3e-3, verbose=False))
    return model


def build_preferences(tokenizer: WordTokenizer) -> list[Preference]:
    return [
        Preference(
            prompt=tokenizer.encode([question], bos=True),
            chosen=tokenizer.encode([polite[0], polite[1]]),
            rejected=tokenizer.encode([rude[0], rude[1]]),
        )
        for question in QUESTIONS
        for polite, rude in zip(
            itertools.product(POLITE_OPENERS, POLITE_BODIES),
            itertools.product(RUDE_OPENERS, RUDE_BODIES),
        )
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="第 11 章：RLHF 安全对齐")
    parser.add_argument("--sft-epochs", type=int, default=40)
    parser.add_argument("--rm-epochs", type=int, default=80)
    parser.add_argument("--ppo-iterations", type=int, default=20)
    args = parser.parse_args()

    tokenizer = WordTokenizer(
        QUESTIONS + POLITE_OPENERS + POLITE_BODIES + RUDE_OPENERS + RUDE_BODIES
    )

    section("实验 A：SFT 基线")
    with timer("SFT"):
        sft_model = build_sft_model(tokenizer, args.sft_epochs)
    bench = Bench(tokenizer, sft_model)
    kv("问题数", len(QUESTIONS))
    kv("词表大小", tokenizer.vocab_size)
    kv("SFT 语料", "每个问题各 9 条礼貌回答 + 9 条生硬回答")

    print(f"\n  {'模型':<22}{'礼貌率':>8}{'多样性':>10}{'与SFT的KL':>11}")
    print("  " + "-" * 78)
    baseline = bench.report(sft_model)
    bench.show("SFT 基线", baseline)
    print("\n  基线礼貌率约 50%——模型两种说法都学会了，但不知道该偏向哪一种。")
    print("  对齐要做的就是把这个分布推过去，同时不要把模型推坏。")

    rng = np.random.default_rng(0)
    print("\n  SFT 模型的采样示例：")
    for prompt in bench.prompts[:3]:
        for _ in range(2):
            response = generate(sft_model, prompt, 2, SamplingConfig(temperature=1.0), rng=rng)
            print(f"    {tokenizer.decode(prompt)} -> {tokenizer.decode(response)}")

    # ------------------------------------------------------------------
    section("实验 B：奖励模型")
    preferences = build_preferences(tokenizer)
    kv("偏好对数量", len(preferences))
    reward_model = SequenceRewardModel(tokenizer.vocab_size, dim=32, hidden=64, seed=0)
    train_reward_model(
        reward_model, preferences, epochs=args.rm_epochs, lr=5e-3,
        pad_id=tokenizer.pad_id, log_every=max(1, args.rm_epochs // 3),
    )
    chosen_scores = [reward_model.score(p.chosen_sequence) for p in preferences]
    rejected_scores = [reward_model.score(p.rejected_sequence) for p in preferences]
    kv("成对准确率", f"{reward_accuracy(reward_model, preferences):.1%}")
    kv("礼貌回答平均分", f"{np.mean(chosen_scores):+.2f}")
    kv("生硬回答平均分", f"{np.mean(rejected_scores):+.2f}")
    kv("分数间隔", f"{np.mean(chosen_scores) - np.mean(rejected_scores):+.2f}")
    print("\n  奖励模型从未见过「礼貌」这个词，它只是从成对比较里学出了一个打分函数。")
    print("  注意 BT 损失只约束**相对**大小，奖励的绝对尺度是自由的——所以 PPO 里")
    print("  必须对优势做归一化，否则学习率的含义会随奖励尺度漂移。")

    # ------------------------------------------------------------------
    section("实验 C：DPO 与对齐税")
    print(f"  {'方法':<22}{'礼貌率':>8}{'多样性':>10}{'与SFT的KL':>11}")
    print("  " + "-" * 78)
    bench.show("SFT 基线", baseline)
    for beta in (0.5, 0.1, 0.02):
        policy = copy.deepcopy(sft_model)
        train_dpo(policy, preferences, beta=beta, epochs=6, lr=1e-3, verbose=False)
        metrics = bench.report(policy)
        bench.show(f"DPO β={beta}", metrics)
        if beta == 0.1:
            dpo_reference = policy

    print("\n  β 是「允许偏离参考模型多远」的旋钮，它直接标出了对齐税：")
    print("   · β 大：约束紧，礼貌率略低，但保留了更多种说法；")
    print("   · β 小：约束松，礼貌率满分，多样性却塌缩到只剩几种固定回答。")
    print("  真实系统里这表现为「对齐后的模型变得千篇一律」，是个必须自觉权衡的取舍。")
    kv("\n  DPO(β=0.1) 偏好对数似然间隔", f"{preference_margin(dpo_reference, preferences):+.2f}")

    # ------------------------------------------------------------------
    section("实验 D：PPO 与 KL 惩罚")
    print("  用奖励模型的打分做策略优化。每轮：采样 → 打分 → 归一化优势 → 裁剪更新。\n")
    results = []
    for kl_coef in (0.05, 0.0):
        policy = copy.deepcopy(sft_model)
        print(f"  KL 系数 = {kl_coef}：")
        with timer(f"PPO (kl={kl_coef})"):
            history = ppo_train(
                policy, reward_model, bench.prompts, response_len=2,
                iterations=args.ppo_iterations, samples_per_prompt=4, lr=1e-3,
                kl_coef=kl_coef, log_every=max(1, args.ppo_iterations // 4),
            )
        results.append((kl_coef, bench.report(policy), history))
        print()

    print(f"  {'方法':<22}{'礼貌率':>8}{'多样性':>10}{'与SFT的KL':>11}")
    print("  " + "-" * 78)
    bench.show("SFT 基线", baseline)
    for kl_coef, metrics, history in results:
        bench.show(f"PPO kl_coef={kl_coef}", metrics)
    for kl_coef, metrics, history in results:
        print(
            f"    kl_coef={kl_coef}: 平均奖励 {history[0]['reward']:+.2f} -> {history[-1]['reward']:+.2f}"
        )

    print("\n  两组的礼貌率与最终奖励几乎一样，差别全在最后一列：带 KL 惩罚的策略把漂移")
    print("  稳住在 +1 附近，去掉惩罚后一路漂到 +9，奖励却没有变得更高。")
    print("  这就是「白跑的漂移」——策略只对奖励模型负责，而奖励模型只是人类偏好的一个")
    print("  有偏近似，离参考模型越远，这个近似越不可信，钻空子（reward hacking）的")
    print("  空间也越大。KL 惩罚的作用不是提升指标，而是让指标继续可信。")
    print("\n  实现上有个坑值得记住：KL 惩罚要从**奖励**里扣（InstructGPT 的做法），")
    print("  而不是当成一项加进损失。后者会对每条被采样到的序列都施加一个方向一致的")
    print("  「降低其概率」的梯度，而概率之和恒为 1，结果是把质量推给没采样到的序列，")
    print("  训练直接崩掉。")

    section("小结")
    print("  1. 奖励模型把「说不清的偏好」变成了「可优化的标量」，代价是引入了一层近似；")
    print("  2. PPO 需要采样 + RM + 参考模型三份前向，工程复杂；DPO 把它化简成一个")
    print("     分类损失，同样有效且稳定得多，这是它成为主流的原因；")
    print("  3. 无论哪条路线，都必须同时盯住礼貌率、多样性与 KL 三个数——")
    print("     只盯第一个，你会得到一个满分但只会说一句话的模型。")


if __name__ == "__main__":
    main()
