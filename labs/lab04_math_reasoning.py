"""第 4 章实验：数学推理与"迷你 R1"蒸馏。

R1 一类推理模型的核心经验是：**让小模型模仿大模型的思考过程，比让它模仿
大模型的答案有用得多**。本实验在三位数加法上把这句话量化。

* 实验 A：固定模型、固定数据量、固定训练轮数，只改变"允许模型写多长的草稿"，
  看准确率如何随思考长度变化；
* 实验 B：固定输出格式，改变教师轨迹的数量，得到蒸馏的数据效率曲线；
* 实验 C：逐位错误分析，看看模型到底错在哪一位——这是判断"它是学会了算法
  还是背下了答案"的关键证据。

用法::

    python -m labs.lab04_math_reasoning
    python -m labs.lab04_math_reasoning --digits 2 --epochs 15   # 更快
"""

from __future__ import annotations

import argparse
from collections import Counter

from ._common import bar, kv, section, timer
from ._tasks import ArithmeticTask, train_on_task

_STYLE_NAMES = {"direct": "直接作答", "reverse": "倒序草稿", "cot": "逐位思维链"}


def evaluate(arithmetic, sft, model, examples=None) -> float:
    examples = examples if examples is not None else sft.test_examples
    correct = sum(
        1
        for prompt, gold in examples
        if arithmetic.answer_matches(sft.predict(model, prompt), gold)
    )
    return correct / len(examples)


def main() -> None:
    parser = argparse.ArgumentParser(description="第 4 章：数学推理与蒸馏")
    parser.add_argument("--digits", type=int, default=3)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--n-train", type=int, default=1200)
    parser.add_argument("--n-test", type=int, default=80)
    parser.add_argument("--quick", action="store_true", help="两位数 + 更少轮数，约 1 分钟跑完")
    args = parser.parse_args()
    if args.quick:
        args.digits, args.epochs, args.n_train, args.n_test = 2, 15, 800, 60

    section(f"任务：{args.digits} 位数加法")
    samples = {}
    for style in ("direct", "reverse", "cot"):
        task = ArithmeticTask(
            n_train=args.n_train, n_test=args.n_test, style=style, digits=args.digits
        )
        a, b = task.train_pairs[0]
        samples[style] = task
        kv(_STYLE_NAMES[style], f"{task.prompt(a, b)}{task.target(a, b)}")
    kv("训练 / 测试题量", f"{args.n_train} / {args.n_test}")
    print("\n  三种格式承载的信息完全相同，唯一的区别是模型被允许用多少 token 来算。")

    # ------------------------------------------------------------------
    section("实验 A：思考长度 vs 准确率")
    trained = {}
    rows = []
    for style in ("direct", "reverse", "cot"):
        task = samples[style]
        sft = task.to_sft_task()
        print(f"\n  训练「{_STYLE_NAMES[style]}」：目标长度 {task.target_length} 字符")
        with timer(f"{style} 训练"):
            model = train_on_task(
                sft, epochs=args.epochs, batch_size=64, log_every=max(1, args.epochs // 2)
            )
        accuracy = evaluate(task, sft, model)
        trained[style] = (task, sft, model)
        rows.append((_STYLE_NAMES[style], task.target_length, accuracy))
        kv("测试准确率", f"{accuracy:.1%}")

    print()
    print(f"  {'输出格式':<14}{'目标长度':>10}{'测试准确率':>12}")
    print("  " + "-" * 58)
    for name, length, accuracy in rows:
        print(f"  {name:<14}{length:>10}{accuracy:>11.1%}  {bar(accuracy)}")
    print("\n  思考长度越长，准确率越高——多出来的 token 就是模型多拿到的计算步数。")

    # ------------------------------------------------------------------
    section("实验 B：蒸馏的数据效率（思维链格式）")
    print(f"  {'教师轨迹条数':<14}{'测试准确率':>12}")
    print("  " + "-" * 58)
    for n_train in (150, 300, 600, args.n_train):
        task = ArithmeticTask(
            n_train=n_train, n_test=args.n_test, style="cot", digits=args.digits, seed=1
        )
        sft = task.to_sft_task()
        model = train_on_task(sft, epochs=args.epochs, batch_size=64, verbose=False)
        accuracy = evaluate(task, sft, model)
        print(f"  {n_train:<14}{accuracy:>11.1%}  {bar(accuracy)}")
    print("\n  准确率随教师数据量单调上升并趋于饱和：蒸馏的成本主要在「教师肯写多少推理」。")

    # ------------------------------------------------------------------
    section("实验 C：错在哪一位？")
    task, sft, model = trained["cot"]
    position_errors: Counter[str] = Counter()
    wrong_examples = []
    for prompt, gold in sft.test_examples:
        prediction = sft.predict(model, prompt)
        if task.answer_matches(prediction, gold):
            continue
        digits = "".join(ch for ch in prediction if ch.isdigit())[-(args.digits + 1) :]
        wrong_examples.append((prompt, gold, prediction))
        for index, (predicted_digit, gold_digit) in enumerate(zip(digits.rjust(len(gold), "?"), gold)):
            if predicted_digit != gold_digit:
                place = len(gold) - index - 1
                position_errors[f"10^{place} 位"] += 1

    if not wrong_examples:
        print("  测试集全对，没有可分析的错误。")
    else:
        kv("错误题数", f"{len(wrong_examples)} / {len(sft.test_examples)}")
        for place, count in sorted(position_errors.items(), reverse=True):
            print(f"    {place:<10}出错 {count} 次")
        print("\n  典型错例：")
        for prompt, gold, prediction in wrong_examples[:3]:
            print(f"    {prompt}{prediction}   （正确答案 {gold}）")
        print("\n  错误集中在高位，说明模型学到的是「逐位加 + 进位」这个算法，")
        print("  只是进位链越长越容易在某一环断掉——和人做竖式算错的地方是一样的。")


if __name__ == "__main__":
    main()
