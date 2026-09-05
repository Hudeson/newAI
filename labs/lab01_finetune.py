"""第 1 章实验：指令微调与部署。

跑通三件事：

1. **全参数 SFT**：只对回答部分计算损失，让模型学会"评论 → 情感"这个格式与任务；
2. **LoRA**：冻结主干、只训练 2% 的低秩参数，对比效果与开销，并验证合并回主干后
   推理结果逐位一致；
3. **部署**：把训练好的模型包成一个命令行推理接口。

评测集由训练中**从未同时出现过**的"主语 + 情感词"组合构成，
所以准确率反映的是组合泛化，而不是背题。

用法::

    python -m labs.lab01_finetune            # 完整实验
    python -m labs.lab01_finetune --serve    # 训练完进入交互式推理
"""

from __future__ import annotations

import argparse

import numpy as np

from dive.lora import apply_lora, lora_state_dict, merge_lora, trainable_report
from dive.training import TrainConfig, train_causal_lm
from dive.transformer import TinyLM, TinyLMConfig

from ._common import bar, kv, section, timer
from ._tasks import build_sentiment_task


def build_model(task, seed: int = 0) -> TinyLM:
    return TinyLM(
        TinyLMConfig(
            vocab_size=task.tokenizer.vocab_size,
            dim=96,
            n_layers=3,
            n_heads=4,
            max_seq_len=task.max_seq_len,
            seed=seed,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="第 1 章：微调与部署")
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--lora-rank", type=int, default=8)
    parser.add_argument("--serve", action="store_true", help="训练完成后进入交互式推理")
    args = parser.parse_args()

    task = build_sentiment_task()
    batches = task.batches(batch_size=32)

    section("任务概览")
    kv("任务", task.name)
    kv("训练样本 / 测试样本", f"{len(task.train_examples)} / {len(task.test_examples)}")
    kv("字符表大小", task.tokenizer.vocab_size)
    kv("测试集构成", "训练中从未共现的「主语+情感词」组合")
    prompt, label = task.train_examples[0]
    kv("样本示例", f"{prompt.replace(chr(10), '⏎')}{label}")
    print("\n  提示：SFT 的损失只覆盖回答部分，提示词位置全部记为 IGNORE_INDEX。")
    inputs, targets = batches[0]
    kv("首个 batch 形状", f"输入 {inputs.shape}，其中参与损失的位置 {(targets != -100).sum()} 个")

    # ------------------------------------------------------------------
    section("实验 A：全参数微调")
    full = build_model(task)
    kv("参数量", f"{full.num_parameters():,}")
    kv("微调前测试准确率", f"{task.accuracy(full):.1%}")
    with timer("全参数微调"):
        train_causal_lm(
            full, batches, TrainConfig(epochs=args.epochs, lr=3e-3, log_every=max(1, args.epochs // 3))
        )
    full_train_acc = task.accuracy(full, task.train_examples)
    full_test_acc = task.accuracy(full)
    kv("训练集准确率", f"{full_train_acc:.1%}")
    kv("测试集准确率（组合泛化）", f"{full_test_acc:.1%}")

    # ------------------------------------------------------------------
    section("实验 B：LoRA 微调")
    lora_model = build_model(task)
    replaced = apply_lora(lora_model, rank=args.lora_rank, targets=("wq", "wv"))
    report = trainable_report(lora_model)
    kv("被替换的线性层", ", ".join(replaced))
    kv("总参数 / 可训练参数", f"{int(report['total']):,} / {int(report['trainable']):,}")
    kv("可训练占比", f"{report['trainable_ratio']:.2%}")
    kv("适配器体积", f"{sum(v.size for v in lora_state_dict(lora_model).values()) * 8 / 1024:.1f} KB")
    with timer("LoRA 微调"):
        train_causal_lm(
            lora_model,
            batches,
            TrainConfig(epochs=args.epochs, lr=8e-3, log_every=max(1, args.epochs // 3)),
        )
    lora_test_acc = task.accuracy(lora_model)
    kv("测试集准确率", f"{lora_test_acc:.1%}")

    before = lora_model(batches[0][0]).data.copy()
    merged = merge_lora(lora_model)
    after = lora_model(batches[0][0]).data
    kv("合并的 LoRA 层数", merged)
    kv("合并前后 logits 最大偏差", f"{np.abs(before - after).max():.2e}（数值误差量级）")
    kv("合并后测试准确率", f"{task.accuracy(lora_model):.1%}")

    # ------------------------------------------------------------------
    section("对比小结")
    print(f"  {'方案':<14}{'可训练参数':>12}{'测试准确率':>12}")
    print("  " + "-" * 40)
    print(f"  {'全参数微调':<14}{full.num_parameters(True):>12,}{full_test_acc:>11.1%}  {bar(full_test_acc)}")
    print(f"  {'LoRA r=' + str(args.lora_rank):<14}{int(report['trainable']):>12,}{lora_test_acc:>11.1%}  {bar(lora_test_acc)}")
    print(
        "\n  结论：LoRA 用约 "
        f"{report['trainable_ratio']:.1%} 的可训练参数达到了与全参数微调相当的效果，"
        "\n  且合并后推理开销为零——这就是「一个基座模型 + 一堆小适配器」的由来。"
    )

    # ------------------------------------------------------------------
    section("部署：把模型包成推理接口")
    for prompt, gold in task.test_examples[:5]:
        prediction = task.predict(full, prompt)
        flag = "✓" if prediction.strip() == gold else "✗"
        print(f"  {flag} {prompt.replace(chr(10), ' | ')}{prediction}   (标准答案 {gold})")

    if args.serve:
        print("\n  进入交互模式，直接输入评论内容，Ctrl-C 退出。")
        try:
            while True:
                text = input("  评论> ").strip()
                if not text:
                    continue
                print(f"  情感> {task.predict(full, f'评论:{text}{chr(10)}情感:')}")
        except (KeyboardInterrupt, EOFError):
            print("\n  再见。")


if __name__ == "__main__":
    main()
