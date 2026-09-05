"""第 2 章实验：思维链与推理时的解码策略。

本章关心的是**训练完之后**还能怎样提升表现——不改一个参数，只改
"让模型怎么说"和"我们怎么读"。在同一个模型、同一批题目上比较：

1. **输出格式**：直接给答案 vs 先写逐位进位草稿再给答案（思维链）；
2. **解码策略**：贪心、温度采样、集束搜索；
3. **自洽投票（Self-Consistency）**：采样多条推理链后对最终答案投票。

思维链之所以有用，一个朴素但正确的解释是：Transformer 每生成一个 token
只做固定量的计算，把中间结果写出来等于给了模型更多"可用的计算步数"，
也让每一步只需要做一件很局部的事（本例中就是一位加法加进位）。

用法::

    python -m labs.lab02_prompting_cot
    python -m labs.lab02_prompting_cot --epochs 25 --n-test 200
"""

from __future__ import annotations

import argparse

import numpy as np

from dive.decoding import SamplingConfig, beam_search, generate
from dive.prompting import majority_vote

from ._common import bar, kv, section, timer
from ._tasks import ArithmeticTask, train_on_task


def evaluate(arithmetic, task_sft, model, examples, temperature, rng=None):
    correct = 0
    for prompt, gold in examples:
        prediction = task_sft.predict(model, prompt, temperature=temperature, rng=rng)
        correct += int(arithmetic.answer_matches(prediction, gold))
    return correct / len(examples)


def main() -> None:
    parser = argparse.ArgumentParser(description="第 2 章：提示学习与思维链")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--n-train", type=int, default=800)
    parser.add_argument("--n-test", type=int, default=100)
    parser.add_argument("--k", type=int, default=5, help="自洽投票的采样条数")
    parser.add_argument("--quick", action="store_true", help="更少数据与轮数，约 30 秒跑完")
    args = parser.parse_args()
    if args.quick:
        args.epochs, args.n_train, args.n_test, args.k = 12, 500, 50, 5

    section("任务：两位数加法")
    direct_task = ArithmeticTask(n_train=args.n_train, n_test=args.n_test, style="direct")
    cot_task = ArithmeticTask(n_train=args.n_train, n_test=args.n_test, style="cot")
    a, b = direct_task.train_pairs[0]
    kv("训练 / 测试题量", f"{args.n_train} / {args.n_test}（测试题在训练中从未出现）")
    kv("直接作答格式", f"{direct_task.prompt(a, b)}{direct_task.target(a, b)}")
    kv("思维链格式", f"{cot_task.prompt(a, b)}{cot_task.target(a, b)}")
    print("\n  草稿含义：[个位和c进位;十位和c进位] 最终三位数答案")

    # ------------------------------------------------------------------
    section("实验 A：输出格式的影响（相同模型、相同题目、相同轮数）")
    results: dict[str, float] = {}
    models = {}
    for style, task in (("direct", direct_task), ("cot", cot_task)):
        sft = task.to_sft_task()
        print(f"\n  训练「{'直接作答' if style == 'direct' else '思维链'}」模型：")
        with timer(f"{style} 训练"):
            model = train_on_task(
                sft, epochs=args.epochs, batch_size=64, log_every=max(1, args.epochs // 2)
            )
        accuracy = evaluate(task, sft, model, sft.test_examples, temperature=0.0)
        results[style] = accuracy
        models[style] = (task, sft, model)
        kv("贪心解码测试准确率", f"{accuracy:.1%}")

    print()
    print(f"  {'输出格式':<16}{'测试准确率':>12}")
    print("  " + "-" * 46)
    print(f"  {'直接作答':<16}{results['direct']:>11.1%}  {bar(results['direct'])}")
    print(f"  {'思维链':<16}{results['cot']:>11.1%}  {bar(results['cot'])}")
    delta = results["cot"] - results["direct"]
    print(f"\n  思维链带来 {delta:+.1%} 的绝对提升——模型没变大，只是被允许「把草稿写出来」。")

    # ------------------------------------------------------------------
    arithmetic, sft, model = models["cot"]
    section("实验 B：解码策略对比（思维链模型）")
    rows = []
    for label, temperature in (("贪心 (T=0)", 0.0), ("采样 T=0.5", 0.5), ("采样 T=1.0", 1.0)):
        rng = np.random.default_rng(0)
        accuracy = evaluate(arithmetic, sft, model, sft.test_examples, temperature=temperature, rng=rng)
        rows.append((label, accuracy))

    beam_correct = 0
    for prompt, gold in sft.test_examples:
        ids = sft.tokenizer.encode(prompt, bos=True)
        candidates = beam_search(
            model, ids, max_new_tokens=sft.max_new_tokens, beam_width=3, eos_id=sft.tokenizer.eos_id
        )
        prediction = sft.tokenizer.decode(candidates[0])
        beam_correct += int(arithmetic.answer_matches(prediction, gold))
    rows.append(("集束搜索 (beam=3)", beam_correct / len(sft.test_examples)))

    print(f"  {'解码策略':<20}{'准确率':>10}")
    print("  " + "-" * 46)
    for label, accuracy in rows:
        print(f"  {label:<20}{accuracy:>9.1%}  {bar(accuracy)}")

    # ------------------------------------------------------------------
    section(f"实验 C：自洽投票（T=1.0，每题采样 {args.k} 条推理链）")
    rng = np.random.default_rng(7)
    single_correct = 0
    voted_correct = 0
    showcase = None

    for index, (prompt, gold) in enumerate(sft.test_examples):
        ids = sft.tokenizer.encode(prompt, bos=True)
        answers, texts = [], []
        for _ in range(args.k):
            out = generate(
                model,
                ids,
                max_new_tokens=sft.max_new_tokens,
                config=SamplingConfig(temperature=1.0),
                stop_ids=[sft.tokenizer.eos_id],
                rng=rng,
            )
            text = sft.tokenizer.decode(out)
            digits = "".join(ch for ch in text if ch.isdigit())
            texts.append(text)
            answers.append(digits[-3:] if len(digits) >= 3 else None)

        single_correct += int(answers[0] == gold)
        winner, votes, total = majority_vote(answers)
        voted_correct += int(winner == gold)

        if showcase is None and answers[0] != gold and winner == gold:
            showcase = (prompt, gold, texts, answers, votes, total)

    single = single_correct / len(sft.test_examples)
    voted = voted_correct / len(sft.test_examples)
    print(f"  {'方法':<24}{'准确率':>10}")
    print("  " + "-" * 46)
    print(f"  {'单次采样 (T=1.0)':<24}{single:>9.1%}  {bar(single)}")
    print(f"  {f'自洽投票 (k={args.k})':<24}{voted:>9.1%}  {bar(voted)}")
    print(f"  {'贪心解码（参照）':<24}{rows[0][1]:>9.1%}  {bar(rows[0][1])}")

    if showcase:
        prompt, gold, texts, answers, votes, total = showcase
        print(f"\n  一个被投票救回来的例子：{prompt}（正确答案 {gold}）")
        for text, answer in zip(texts, answers):
            print(f"    采样：{text:<16} -> {answer}")
        print(f"    投票结果：{gold}（{votes}/{total} 票）")

    section("小结")
    print("  1. 把推理过程显式写出来，比让模型「心算」更可靠——这是思维链的本质。")
    print("  2. 采样温度是准确率与多样性的权衡：T 越高越发散，单次正确率越低。")
    print("  3. 自洽投票用「多条路径殊途同归」把采样噪声平均掉，代价是 k 倍推理开销。")


if __name__ == "__main__":
    main()
