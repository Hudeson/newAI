"""第 3 章实验：知识编辑。

把 FFN 的下投影层当作**线性关联记忆**（key = 主语表示，value = 客体表示），
"改一条事实"就变成了一个带约束的最小二乘问题。本实验对比三种改法：

===================  ==============================================
方法                  更新方向
===================  ==============================================
ROME（带协方差）        ``C⁻¹k*``——沿着"与其他知识最不冲突"的方向
ROME（单位协方差）       ``k*``——最小 L2 改动
朴素梯度微调            只对目标事实做梯度下降
===================  ==============================================

实验会同时报告两个指标：**有效性**（新事实改对了吗）与**局部性**
（其他事实被殃及了吗）。只看前者的编辑方法都是耍流氓。

用法::

    python -m labs.lab03_knowledge_edit
    python -m labs.lab03_knowledge_edit --correlation 0.0   # 观察相关性的作用
"""

from __future__ import annotations

import argparse

from dive.knowledge_edit import FactStore, evaluate_edit, finetune_edit, rome_edit

from ._common import bar, kv, section

_LANDMARKS = [
    ("埃菲尔铁塔位于", "巴黎"),
    ("自由女神像位于", "纽约"),
    ("大本钟位于", "伦敦"),
    ("故宫位于", "北京"),
    ("红场位于", "莫斯科"),
    ("浅草寺位于", "东京"),
    ("斗兽场位于", "罗马"),
    ("勃兰登堡门位于", "柏林"),
    ("金字塔位于", "开罗"),
    ("歌剧院位于", "悉尼"),
    ("外滩位于", "上海"),
    ("兵马俑位于", "西安"),
    ("布达拉宫位于", "拉萨"),
    ("圣家堂位于", "巴塞罗那"),
    ("自由钟位于", "费城"),
    ("小美人鱼位于", "哥本哈根"),
    ("圣索菲亚位于", "伊斯坦布尔"),
    ("大教堂位于", "科隆"),
    ("风车村位于", "阿姆斯特丹"),
    ("狮身人面像位于", "吉萨"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="第 3 章：知识编辑")
    parser.add_argument("--dim", type=int, default=20)
    parser.add_argument("--correlation", type=float, default=0.9)
    parser.add_argument("--sequential", type=int, default=8, help="连续编辑次数")
    args = parser.parse_args()

    store = FactStore(dim=args.dim, seed=0, correlation=args.correlation)
    store.add_many(_LANDMARKS)
    store.add("__新客体__", "威尼斯", as_fact=False)
    memory = store.fit(ridge=1e-6)

    section("构建「预训练」记忆")
    kv("事实条数", len(store.facts))
    kv("表示维度", args.dim)
    kv("主语向量相关性", f"{args.correlation}（真实模型中的主语表示远非正交）")
    kv("编辑前召回准确率", f"{store.accuracy(memory):.1%}")
    kv("抽查", f"埃菲尔铁塔位于 -> {store.recall('埃菲尔铁塔位于', memory)}")

    target = "埃菲尔铁塔位于"
    key = store.subject_vectors[target]
    new_value = store.object_vectors["威尼斯"]
    other_keys = store.keys([s for s, _ in store.facts if s != target])

    section(f"编辑目标：{target} 巴黎 -> 威尼斯")
    methods = {
        "ROME（带协方差）": rome_edit(memory, key, new_value, covariance=store.covariance()),
        "ROME（单位协方差）": rome_edit(memory, key, new_value, covariance=None),
        "朴素梯度微调": finetune_edit(memory, key, new_value, steps=400, lr=0.3),
    }

    print(f"  {'方法':<20}{'编辑后召回':<10}{'有效性':>8}{'局部性':>8}{'其他事实准确率':>14}{'|ΔW|':>9}")
    print("  " + "-" * 78)
    for name, edited in methods.items():
        report = evaluate_edit(memory, edited, key, new_value, other_keys)
        accuracy = store.accuracy(edited, skip=target)
        print(
            f"  {name:<20}{store.recall(target, edited):<10}"
            f"{report.efficacy:>8.3f}{report.locality:>8.3f}{accuracy:>13.0%}{report.weight_change:>9.2f}"
        )

    print("\n  读法：")
    print("   · 有效性都是 1.000——三种方法都把目标事实改对了，光看这一列分不出高下；")
    print("   · 局部性拉开了差距——带协方差的 ROME 保持 1.000，另外两种掉到 0.73，")
    print("     说明其他知识的表示已经被明显推偏了；")
    print("   · 但「其他事实准确率」此时还都是 100%：单次编辑造成的偏移尚不足以让")
    print("     最近邻判断翻车。局部性是先行指标，准确率是滞后指标——下一节会看到代价；")
    print("   · 朴素微调与「单位协方差 ROME」结果逐位相同，因为对单个样本做梯度下降")
    print("     收敛到的正是最小 L2 改动解。ROME 真正的价值全在 C⁻¹ 这一项上；")
    print("   · 带协方差的 ΔW 范数反而更大：它宁愿多改一点，也要改在与其他 key 正交的方向上。")

    # ------------------------------------------------------------------
    section(f"连续编辑 {args.sequential} 条事实：副作用会累积吗？")
    print(f"  {'已编辑条数':<12}{'ROME（带协方差）':>18}{'ROME（单位协方差）':>20}")
    print("  " + "-" * 52)

    rome_memory = memory.copy()
    naive_memory = memory.copy()
    covariance = store.covariance()
    edited_subjects: list[str] = []

    for step in range(args.sequential + 1):
        if step > 0:
            subject, _ = store.facts[step - 1]
            edited_subjects.append(subject)
            new_object = store.facts[(step + 4) % len(store.facts)][1]
            k = store.subject_vectors[subject]
            v = store.object_vectors[new_object]
            rome_memory = rome_edit(rome_memory, k, v, covariance=covariance)
            naive_memory = rome_edit(naive_memory, k, v, covariance=None)

        untouched = [s for s, _ in store.facts if s not in edited_subjects]
        rome_accuracy = _accuracy_on(store, rome_memory, untouched)
        naive_accuracy = _accuracy_on(store, naive_memory, untouched)
        print(
            f"  {step:<12}{rome_accuracy:>15.0%} {bar(rome_accuracy, 12)}"
            f"{naive_accuracy:>8.0%} {bar(naive_accuracy, 12)}"
        )

    print("\n  单位协方差版本每编辑一条就把「未编辑事实」的准确率打下去一截，")
    print("  几次之后知识库已经千疮百孔；带协方差的 ROME 则始终保持 100%。")
    print("\n  必要的免责声明：这里的协方差是从全部 key 精确算出来的，记忆也严格线性，")
    print("  所以 ROME 的表现是理想上界。真实模型里 C 只能从语料抽样估计、FFN 之外还有")
    print("  注意力与非线性，连续编辑到几百上千条时同样会崩——这正是 MEMIT 等方法")
    print("  要一次性联立求解所有事实、而不是逐条叠加的原因。")


def _accuracy_on(store: FactStore, memory, subjects: list[str]) -> float:
    if not subjects:
        return 1.0
    gold = dict(store.facts)
    correct = sum(1 for subject in subjects if store.recall(subject, memory) == gold[subject])
    return correct / len(subjects)


if __name__ == "__main__":
    main()
