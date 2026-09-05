"""第 9 章实验：GUI 智能体。

真实的 GUI Agent 要处理截图、坐标与异步渲染，但"看界面 → 决定点哪 →
界面变化 → 再看"这个闭环，以及随之而来的评测问题，在模拟环境里就能讲清楚。

观测采用**无障碍树**（accessibility tree）的文本形式，这也是目前多数 GUI
Agent 真正喂给模型的东西——比截图省 token，也比截图准确。

* 实验 A：环境长什么样、一步动作会发生什么；
* 实验 B：随机智能体 vs 规则规划器的成功率与步数；
* 实验 C：误触危险按钮的概率——GUI Agent 最现实的风险不是"做不成"，
  而是"做错了不可撤销的事"；
* 实验 D：加上二次确认护栏之后的效果。

用法::

    python -m labs.lab09_gui_agent --episodes 300
"""

from __future__ import annotations

import argparse

import numpy as np

from dive.gui_agent import GUIEnvironment, build_settings_app

from ._common import bar, kv, section

MAX_STEPS = 12


def random_agent(env: GUIEnvironment, rng: np.random.Generator, guard: bool = False) -> dict[str, object]:
    """随机点击当前界面上任意一个可用元素。"""
    env.reset()
    for _ in range(MAX_STEPS):
        options = [element for element in env.screen.elements if element.enabled]
        if env.pending_confirm:
            options_actions = [("confirm", ""), ("cancel", "")]
            action, argument = options_actions[int(rng.integers(0, 2))]
            if guard and action == "confirm":
                action, argument = "cancel", ""
        else:
            element = options[int(rng.integers(0, len(options)))]
            action, argument = "click", element.id
        result = env.step(action, argument)
        if result.done:
            break
    return {"success": env.goal(env), "steps": env.steps, "side_effects": list(env.side_effects)}


def planner_agent(env: GUIEnvironment, goal_labels: list[str], guard: bool = True) -> dict[str, object]:
    """规则规划器：在无障碍树里按标签找目标元素，找不到就先做导航。

    这是最朴素的"看得懂界面"的策略：把目标拆成一串标签，依次点过去。
    真实系统里这一步由大模型完成，但它输出的动作格式与这里完全相同。
    """
    env.reset()
    pending = list(goal_labels)
    for _ in range(MAX_STEPS):
        if env.pending_confirm:
            env.step("cancel" if guard else "confirm")
            continue
        if not pending:
            break
        target = pending[0]
        element = next((e for e in env.screen.elements if e.label == target and e.enabled), None)
        if element is not None:
            result = env.step("click", element.id)
            pending.pop(0)
            if result.done:
                break
        else:
            # 目标不在当前界面，找一个导航按钮走过去
            navigation = next(
                (e for e in env.screen.elements if e.role == "button" and not e.confirm), None
            )
            if navigation is None:
                break
            env.step("click", navigation.id)
    return {"success": env.goal(env), "steps": env.steps, "side_effects": list(env.side_effects)}


def summarize(name: str, runs: list[dict[str, object]]) -> tuple[str, float, float, float]:
    success = float(np.mean([run["success"] for run in runs]))
    steps = float(np.mean([run["steps"] for run in runs]))
    damage = float(np.mean([bool(run["side_effects"]) for run in runs]))
    return name, success, steps, damage


def main() -> None:
    parser = argparse.ArgumentParser(description="第 9 章：GUI 智能体")
    parser.add_argument("--episodes", type=int, default=300)
    args = parser.parse_args()

    env = build_settings_app()

    section("实验 A：环境与观测")
    print("  初始界面（无障碍树）：")
    for line in env.observe().splitlines():
        print(f"    {line}")
    env.step("click", "open_settings")
    print("\n  执行 click(open_settings) 之后：")
    for line in env.observe().splitlines():
        print(f"    {line}")
    print("\n  任务目标：打开深色模式并保存（即 dark_mode=on 且停在 saved 界面）。")
    print("  注意界面上那个标着 needs-confirm 的「清空所有数据」——它是本实验的地雷。")

    # ------------------------------------------------------------------
    section("实验 B / C：不同策略的成功率与误触率")
    rng = np.random.default_rng(0)
    results = [
        summarize("随机点击", [random_agent(env, rng) for _ in range(args.episodes)]),
        summarize("随机点击 + 护栏", [random_agent(env, rng, guard=True) for _ in range(args.episodes)]),
        summarize("规则规划器（无护栏）", [planner_agent(env, ["深色模式", "保存"], guard=False)]),
        summarize("规则规划器 + 护栏", [planner_agent(env, ["深色模式", "保存"], guard=True)]),
    ]

    print(f"  {'策略':<22}{'成功率':>9}{'平均步数':>10}{'危险操作触发率':>16}")
    print("  " + "-" * 68)
    for name, success, steps, damage in results:
        print(f"  {name:<22}{success:>8.1%}{steps:>10.1f}{damage:>15.1%}")

    print(f"\n  随机智能体在 {MAX_STEPS} 步内几乎撞不到目标，却有相当概率点掉「清空所有数据」。")
    print("  这就是 GUI Agent 的核心风险画像：能力不足只是效率问题，误触才是事故。")

    # ------------------------------------------------------------------
    section("实验 D：护栏的作用")
    baseline = next(r for r in results if r[0] == "随机点击")
    guarded = next(r for r in results if r[0] == "随机点击 + 护栏")
    print(f"  {'指标':<20}{'无护栏':>12}{'有护栏':>12}")
    print("  " + "-" * 46)
    print(f"  {'成功率':<20}{baseline[1]:>11.1%}{guarded[1]:>12.1%}")
    print(f"  {'危险操作触发率':<20}{baseline[3]:>11.1%}{guarded[3]:>12.1%}")
    print(f"\n  {'危险操作触发率':<12}{bar(baseline[3], 24)} 无护栏")
    print(f"  {'':<12}{bar(guarded[3], 24)} 有护栏")

    print("\n  护栏做的事只有一件：拒绝对不可撤销操作点「确认」。它把「事故」这一类")
    print("  结果整个从分布里删掉，而且没有牺牲成功率——成功率反而还升了，")
    print("  因为误触「清空所有数据」会把智能体打回首页，白白浪费掉剩下的步数。")

    section("规划器的完整轨迹")
    env.reset()
    for action, argument in (("click", "open_settings"), ("click", "dark_mode"), ("click", "save")):
        result = env.step(action, argument)
        print(f"  {action}({argument}) -> {env.observe().splitlines()[0]}  done={result.done}")
    kv("最终状态", f"深色模式={env.state.get('dark_mode')}，界面={env.current}，副作用={env.side_effects}")


if __name__ == "__main__":
    main()
