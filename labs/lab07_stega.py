"""第 7 章实验：大模型隐写。

隐写与水印目标相反：水印要让人**检测得出**，隐写要让人**看不出来**，
同时接收方能把藏进去的比特一个不差地取回来。

做法是在每一步生成时，对模型给出的 top-k 候选建一棵 Huffman 树，用秘密
比特流在树上走路径，走到哪个叶子就输出哪个 token。解码方用同一个模型和
同一段前缀重建出同一棵树，就能从观察到的 token 反推出比特。

* 实验 A：端到端收发，验证比特完全无损；
* 实验 B：容量与隐蔽性的权衡——``top_k`` 越大每个 token 能藏越多比特，
  但选到低概率词的机会也越大，文本越可疑；
* 实验 C：脆弱性——隐写对改写零容忍，这正好和水印形成对照。

用法::

    python -m labs.lab07_stega
    python -m labs.lab07_stega --message "上海交通大学"
"""

from __future__ import annotations

import argparse

import numpy as np

from dive.decoding import SamplingConfig, generate
from dive.stega import HuffmanStego, bytes_to_bits

from ._common import bar, kv, section, timer
from ._corpus import mean_entropy, train_slot_lm


def perplexity_under(model, ids: list[int]) -> float:
    return float(np.exp(-np.mean(model.logprobs_for_sequence(ids))))


def main() -> None:
    parser = argparse.ArgumentParser(description="第 7 章：大模型隐写")
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--message", type=str, default="密钥7788")
    parser.add_argument("--top-k", type=int, default=8)
    args = parser.parse_args()

    section("准备：训练载体语言模型")
    with timer("语言模型训练"):
        tokenizer, model, _ = train_slot_lm(epochs=args.epochs)
    prompt = tokenizer.encode(["今天", "研究员"], bos=True)
    kv("词表大小", tokenizer.vocab_size)
    normal = generate(model, prompt, 30, SamplingConfig(temperature=1.0), rng=np.random.default_rng(0))
    kv("正常生成（无隐写）", tokenizer.decode(prompt + normal)[:50] + "…")

    # ------------------------------------------------------------------
    section("实验 A：端到端收发")
    message = args.message.encode("utf-8")
    bits = bytes_to_bits(message)
    stego = HuffmanStego(model, top_k=args.top_k)
    payload = stego.encode(prompt, message, max_tokens=400)
    recovered = stego.decode(prompt, payload)

    kv("秘密消息", args.message)
    kv("消息比特数", f"{len(bits)} bit（{len(message)} 字节）")
    kv("载体 token 数", payload.steps)
    kv("嵌入率", f"{payload.bits_per_token:.2f} bit/token")
    kv("还原结果", recovered.decode("utf-8"))
    kv("是否完全一致", "是" if recovered == message else "否")
    print()
    print(f"  隐写文本：{tokenizer.decode(prompt + payload.token_ids)[:60]}…")
    print("\n  这段文本读起来和正常生成没有区别，但它的每一个用词选择都在传递比特。")
    print("  只有持有同一个模型和同一段前缀的接收方能把它们读出来。")

    # ------------------------------------------------------------------
    section("实验 B：容量与隐蔽性的权衡")
    natural = [
        perplexity_under(
            model,
            prompt
            + generate(
                model, prompt, 40, SamplingConfig(temperature=1.0),
                rng=np.random.default_rng(500 + index),
            ),
        )
        for index in range(20)
    ]
    natural_mean, natural_std = float(np.mean(natural)), float(np.std(natural))
    entropy_bits = mean_entropy(model, prompt + normal) / np.log(2)

    print(f"  正常采样的困惑度：{natural_mean:.2f} ± {natural_std:.2f}")
    print(f"  模型每步熵：{entropy_bits:.2f} bit —— 这是嵌入率的理论上限\n")
    print(f"  {'top_k':>7}{'bit/token':>12}{'载体长度':>10}{'困惑度':>10}{'偏离正常':>12}")
    print("  " + "-" * 58)
    for top_k in (2, 4, 8, 16, 32):
        trial = HuffmanStego(model, top_k=top_k)
        trial_payload = trial.encode(prompt, message, max_tokens=600)
        assert trial.decode(prompt, trial_payload) == message
        perplexity = perplexity_under(model, prompt + trial_payload.token_ids)
        deviation = abs(perplexity - natural_mean) / natural_std
        print(
            f"  {top_k:>7}{trial_payload.bits_per_token:>12.2f}{trial_payload.steps:>10}"
            f"{perplexity:>10.2f}{deviation:>10.1f}σ"
        )
    print(f"\n  两条规律：")
    print(f"   · 嵌入率随 top_k 上升后停在 {entropy_bits:.2f} bit 附近，正好是模型的熵——")
    print("     Huffman 编码已经逼近了信息论上限，再放大候选集也榨不出更多比特；")
    print("   · top_k 小的时候文本反而**过于流畅**（困惑度显著低于正常采样）。")
    print("     隐写的破绽不在于「用词奇怪」，而在于「统计特征和正常生成对不上」，")
    print("     两个方向的偏离都会被隐写分析（steganalysis）分类器抓住。")

    # ------------------------------------------------------------------
    section("实验 C：脆弱性——改一个 token 会怎样")
    rng = np.random.default_rng(0)
    print(f"  {'被篡改的 token 数':>18}{'还原是否正确':>14}{'正确字节比例':>14}")
    print("  " + "-" * 50)
    for n_corrupt in (0, 1, 2, 5):
        corrupted = list(payload.token_ids)
        if n_corrupt:
            positions = rng.choice(len(corrupted), size=n_corrupt, replace=False)
            for position in positions:
                corrupted[position] = int(rng.integers(0, tokenizer.vocab_size))
        broken = type(payload)(token_ids=corrupted, n_bits=payload.n_bits, steps=payload.steps)
        try:
            result = stego.decode(prompt, broken)
        except ValueError:
            result = b""
        matched = sum(1 for a, b in zip(result, message) if a == b)
        ratio = matched / len(message)
        print(f"  {n_corrupt:>18}{'是' if result == message else '否':>13}{ratio:>13.0%}  {bar(ratio, 16)}")

    print("\n  只要改动一个 token，后续所有步骤的 Huffman 树就与编码端错位，比特流随之崩塌。")
    print("  对比第 5 章：水印替换三成 token 仍可检出，隐写改一个 token 就全毁。")
    print("  这不是实现缺陷，而是两者目标不同——水印要的是鲁棒的统计证据，")
    print("  隐写要的是精确的逐比特还原，后者天然不能容错（除非再叠一层纠错码）。")


if __name__ == "__main__":
    main()
