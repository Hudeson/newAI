"""第 5 章实验：大模型文本水印。

在一个真实训练出来的词级语言模型上，完整走一遍 KGW 绿名单水印：

* 实验 A：加水印 vs 不加水印，看 z 统计量能否把两者分开；
* 实验 B：偏置强度 δ 的取舍——水印越强越好检测，但文本质量（在原模型下的
  困惑度）越差。这条曲线是水印方案落地时最重要的一张图；
* 实验 C：鲁棒性——攻击者随机替换一部分 token 之后还检测得出来吗；
* 实验 D：熵的作用——水印藏在模型的"选择自由度"里，没有熵就没有水印。

检测端只需要密钥、不需要模型，这是水印相对于"训个分类器判断是否 AI 生成"的
根本优势。

用法::

    python -m labs.lab05_watermark
    python -m labs.lab05_watermark --n-samples 60 --length 80
"""

from __future__ import annotations

import argparse

import numpy as np

from dive.decoding import SamplingConfig, generate
from dive.watermark import GreenListWatermark, WatermarkConfig

from ._common import bar, kv, section, timer
from ._corpus import mean_entropy, train_slot_lm

THRESHOLD = 4.0


def perplexity_under(model, ids: list[int]) -> float:
    """文本在**原始模型**下的困惑度，用来衡量水印造成的质量损失。"""
    return float(np.exp(-np.mean(model.logprobs_for_sequence(ids))))


def main() -> None:
    parser = argparse.ArgumentParser(description="第 5 章：模型水印")
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--n-samples", type=int, default=40)
    parser.add_argument("--length", type=int, default=60)
    parser.add_argument("--gamma", type=float, default=0.25)
    parser.add_argument("--delta", type=float, default=2.0)
    args = parser.parse_args()

    section("准备：训练一个有真实不确定性的语言模型")
    with timer("语言模型训练"):
        tokenizer, model, documents = train_slot_lm(epochs=args.epochs)
    prompt = tokenizer.encode(["今天", "研究员"], bos=True)
    sample = generate(model, prompt, 40, SamplingConfig(temperature=1.0), rng=np.random.default_rng(0))
    kv("训练文档数", len(documents))
    kv("词表大小", tokenizer.vocab_size)
    kv("每步平均熵", f"{mean_entropy(model, prompt + sample):.2f} nats（约等于每个位置有 8~9 个合理选项）")
    kv("无水印生成", tokenizer.decode(prompt + sample)[:52] + "…")

    # ------------------------------------------------------------------
    section(f"实验 A：水印检测（γ={args.gamma}, δ={args.delta}）")
    watermark = GreenListWatermark(
        tokenizer.vocab_size, WatermarkConfig(gamma=args.gamma, delta=args.delta)
    )
    watermarked_z, clean_z, clean_ppl = [], [], []

    for index in range(args.n_samples):
        marked = generate(
            model, prompt, args.length, SamplingConfig(temperature=1.0),
            processors=[watermark], rng=np.random.default_rng(1000 + index),
        )
        plain = generate(
            model, prompt, args.length, SamplingConfig(temperature=1.0),
            rng=np.random.default_rng(1000 + index),
        )
        watermarked_z.append(watermark.detect(prompt + marked).z_score)
        clean_z.append(watermark.detect(prompt + plain).z_score)
        clean_ppl.append(perplexity_under(model, prompt + plain))

    detected = float(np.mean([z >= THRESHOLD for z in watermarked_z]))
    false_positive = float(np.mean([z >= THRESHOLD for z in clean_z]))

    kv("样本数（各）", args.n_samples)
    kv("水印文本 z 均值", f"{np.mean(watermarked_z):6.2f}   (最小 {np.min(watermarked_z):.2f})")
    kv("无水印文本 z 均值", f"{np.mean(clean_z):6.2f}   (最大 {np.max(clean_z):.2f})")
    kv(f"检出率 (z≥{THRESHOLD})", f"{detected:.1%}")
    kv(f"误报率 (z≥{THRESHOLD})", f"{false_positive:.1%}")
    print()
    print(f"  带水印文本：{tokenizer.decode(prompt + marked)[:52]}…")
    print(f"  检测结果  ：{watermark.detect(prompt + marked)}")
    print(f"  无水印文本：{tokenizer.decode(prompt + plain)[:52]}…")
    print(f"  检测结果  ：{watermark.detect(prompt + plain)}")
    print("\n  两组 z 值完全不重叠——检测端只用密钥重放绿名单，从未接触模型权重。")

    # ------------------------------------------------------------------
    section("实验 B：水印强度 δ 的取舍")
    baseline_ppl = float(np.mean(clean_ppl))
    print(f"  {'δ':>5}{'z 均值':>10}{'检出率':>9}{'困惑度':>10}{'相对无水印':>12}")
    print("  " + "-" * 58)
    for delta in (0.5, 1.0, 2.0, 4.0, 8.0):
        mark = GreenListWatermark(tokenizer.vocab_size, WatermarkConfig(gamma=args.gamma, delta=delta))
        z_scores, perplexities = [], []
        for index in range(max(10, args.n_samples // 2)):
            tokens = generate(
                model, prompt, args.length, SamplingConfig(temperature=1.0),
                processors=[mark], rng=np.random.default_rng(2000 + index),
            )
            z_scores.append(mark.detect(prompt + tokens).z_score)
            perplexities.append(perplexity_under(model, prompt + tokens))
        rate = float(np.mean([z >= THRESHOLD for z in z_scores]))
        mean_ppl = float(np.mean(perplexities))
        print(
            f"  {delta:>5.1f}{np.mean(z_scores):>10.2f}{rate:>8.0%}"
            f"{mean_ppl:>10.2f}{mean_ppl / baseline_ppl:>11.2f}x"
        )
    print(f"\n  无水印基线困惑度 {baseline_ppl:.2f}。δ 越大越好检测，但生成分布被推得越偏。")
    print("  实践中 δ 取 2 左右：检出率已经饱和，质量代价还很小。")

    # ------------------------------------------------------------------
    section("实验 C：鲁棒性——攻击者随机替换 token")
    rng = np.random.default_rng(0)
    marked = generate(
        model, prompt, args.length, SamplingConfig(temperature=1.0),
        processors=[watermark], rng=np.random.default_rng(0),
    )
    full = prompt + marked
    print(f"  {'替换比例':>10}{'z 均值':>10}{'仍可检出':>10}")
    print("  " + "-" * 50)
    for ratio in (0.0, 0.1, 0.2, 0.3, 0.5):
        z_values = []
        for _ in range(10):
            attacked = list(full)
            n_replace = int(len(marked) * ratio)
            if n_replace:
                positions = rng.choice(
                    range(len(prompt), len(full)), size=n_replace, replace=False
                )
                for position in positions:
                    attacked[position] = int(rng.integers(0, tokenizer.vocab_size))
            z_values.append(watermark.detect(attacked).z_score)
        mean_z = float(np.mean(z_values))
        print(
            f"  {ratio:>9.0%}{mean_z:>10.2f}{'是' if mean_z >= THRESHOLD else '否':>9}"
            f"  {bar(mean_z, 22, cap=14)}"
        )
    print("\n  z 统计量是整段文本的累积证据，改掉一部分 token 只会按比例削弱它，")
    print("  不会让水印突然消失——这正是统计式水印比「藏特定字符串」更耐改写的原因。")

    # ------------------------------------------------------------------
    section("实验 D：没有熵就没有水印")
    print("  重新训练几个语料熵不同的模型（限制每个槽位的可选词数），其余设置完全一致：")
    print()
    print(f"  {'每槽可选词数':>12}{'平均熵':>10}{'z 均值':>10}{'检出率':>9}")
    print("  " + "-" * 50)
    for width in (1, 2, 4, None):
        low_tokenizer, low_model, _ = train_slot_lm(
            epochs=args.epochs, slot_width=width, verbose=False
        )
        low_prompt = low_tokenizer.encode(["今天", "研究员"], bos=True)
        low_watermark = GreenListWatermark(
            low_tokenizer.vocab_size, WatermarkConfig(gamma=args.gamma, delta=args.delta)
        )
        z_scores, entropies = [], []
        for index in range(10):
            tokens = generate(
                low_model, low_prompt, args.length, SamplingConfig(temperature=1.0),
                processors=[low_watermark], rng=np.random.default_rng(3000 + index),
            )
            z_scores.append(low_watermark.detect(low_prompt + tokens).z_score)
            entropies.append(mean_entropy(low_model, low_prompt + tokens))
        rate = float(np.mean([z >= THRESHOLD for z in z_scores]))
        label = "全部(8~10)" if width is None else str(width)
        print(
            f"  {label:>12}{np.mean(entropies):>10.2f}"
            f"{np.mean(z_scores):>10.2f}{rate:>8.0%}"
        )

    print("\n  熵趋近于 0 时，模型「只能说那一句话」，δ 的偏置推不动它，水印也就打不上。")
    print("  推论：确定性强的内容（代码、公式、事实问答的短答案）天然难以加水印，")
    print("  这是 KGW 一类方法在工程上真实存在的适用边界。")


if __name__ == "__main__":
    main()
