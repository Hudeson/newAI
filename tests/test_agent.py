"""智能体运行时：动作解析、工具注册、安全护栏与 ReAct 轨迹。"""

from __future__ import annotations

import pytest

from dive.agent import (
    GuardDecision,
    ReActAgent,
    Risk,
    SafetyPolicy,
    ScriptedBrain,
    Tool,
    ToolRegistry,
    Trajectory,
    calculator_tool,
    make_kv_tools,
    make_payment_tool,
    parse_action,
)


# ----------------------------------------------------------------------
# 动作解析
# ----------------------------------------------------------------------
def test_parse_tool_action():
    action = parse_action("Thought: 先算一下\nAction: calculator\nAction Input: 12*(3+4)")
    assert action.tool == "calculator"
    assert action.argument == "12*(3+4)"
    assert not action.is_final


def test_parse_action_accepts_full_width_colon():
    action = parse_action("Action：kv_read\nAction Input：备忘")
    assert (action.tool, action.argument) == ("kv_read", "备忘")


def test_parse_action_keeps_only_the_first_argument_line():
    action = parse_action("Action: kv_write\nAction Input: a=1\nObservation: 已写入")
    assert action.argument == "a=1"


def test_parse_final_answer():
    action = parse_action("Thought: 够了\nFinal Answer: 84")
    assert action.is_final and action.final_answer == "84"
    assert action.tool is None


def test_final_answer_wins_over_action():
    action = parse_action("Action: calculator\nAction Input: 1+1\nFinal Answer: 2")
    assert action.is_final and action.final_answer == "2"


def test_unstructured_output_falls_back_to_final_answer():
    action = parse_action("我觉得答案是 42")
    assert action.is_final and action.final_answer == "我觉得答案是 42"


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------
def test_tool_registry_lookup_and_description():
    registry = ToolRegistry([calculator_tool()])
    assert "calculator" in registry
    assert registry.get("calculator") is not None
    assert registry.get("不存在") is None
    assert "calculator" in registry.describe()


def test_calculator_evaluates_arithmetic():
    run = calculator_tool().run
    assert run("12*(3+4)") == "84"
    assert run(" 2 ** 10 ") == "1024"
    assert run("-7 + 2.5") == "-4.5"


@pytest.mark.parametrize(
    "expression",
    ['__import__("os").system("ls")', "open('/etc/passwd').read()", "[][0]", "x + 1", "lambda: 1"],
)
def test_calculator_rejects_non_arithmetic(expression: str):
    """计算器绝不使用 eval：任何非算术语法都必须被拒绝。"""
    with pytest.raises((ValueError, SyntaxError)):
        calculator_tool().run(expression)


def test_kv_tools_read_and_write():
    store: dict[str, str] = {}
    read, write = make_kv_tools(store)
    assert read.risk == Risk.SAFE and write.risk == Risk.SENSITIVE
    assert write.run("会议=周三下午") == "已写入 会议"
    assert store == {"会议": "周三下午"}
    assert read.run("会议") == "周三下午"
    assert read.run("不存在的键") == "（无此记录）"


def test_payment_tool_is_dangerous_and_records_transfers():
    ledger: list[str] = []
    tool = make_payment_tool(ledger)
    assert tool.risk == Risk.DANGEROUS
    tool.run("张三,100")
    assert ledger == ["张三,100"]


# ----------------------------------------------------------------------
# 安全护栏
# ----------------------------------------------------------------------
def test_policy_allows_tools_within_the_risk_ceiling():
    policy = SafetyPolicy(max_risk=Risk.SENSITIVE)
    read, write = make_kv_tools()
    assert policy.check(read, "任意").allowed
    assert policy.check(write, "a=1").allowed


def test_policy_blocks_tools_above_the_risk_ceiling():
    policy = SafetyPolicy(max_risk=Risk.SENSITIVE, dangerous_budget=0)
    verdict = policy.check(make_payment_tool(), "张三,100")
    assert not verdict.allowed
    assert verdict.rule == "风险上限"


def test_policy_requires_confirmation_within_budget():
    policy = SafetyPolicy(max_risk=Risk.SENSITIVE, dangerous_budget=1, require_confirmation=True)
    verdict = policy.check(make_payment_tool(), "张三,100")
    assert not verdict.allowed and verdict.rule == "人工确认"


def test_policy_spends_the_dangerous_budget():
    policy = SafetyPolicy(max_risk=Risk.SENSITIVE, dangerous_budget=1, require_confirmation=False)
    tool = make_payment_tool()
    assert policy.check(tool, "张三,100").allowed
    second = policy.check(tool, "李四,100")
    assert not second.allowed and second.rule == "风险上限"
    policy.reset()
    assert policy.check(tool, "王五,100").allowed


def test_policy_blocks_forbidden_argument_patterns():
    policy = SafetyPolicy(max_risk=Risk.DANGEROUS, forbidden_patterns=[r",\s*\d{4,}"])
    tool = make_payment_tool()
    assert policy.check(tool, "张三,100").allowed
    verdict = policy.check(tool, "张三,999999")
    assert not verdict.allowed and verdict.rule == "参数黑名单"


def test_guard_decision_defaults():
    decision = GuardDecision(True)
    assert decision.allowed and decision.reason == "" and decision.rule == ""


# ----------------------------------------------------------------------
# ReAct 轨迹
# ----------------------------------------------------------------------
def test_react_agent_executes_a_tool_then_answers():
    brain = ScriptedBrain(
        [
            "Thought: 先算\nAction: calculator\nAction Input: 12*(3+4)",
            "Thought: 有结果了\nFinal Answer: 84",
        ]
    )
    agent = ReActAgent(brain, ToolRegistry([calculator_tool()]))
    trajectory = agent.run("12 乘以 3 加 4 等于多少")

    assert trajectory.answer == "84"
    assert trajectory.executed_tools == ["calculator"]
    assert trajectory.steps[0]["observation"] == "84"
    assert trajectory.blocked == []
    assert "calculator(12*(3+4))" in trajectory.transcript()


def test_react_agent_reports_unknown_tools_without_crashing():
    brain = ScriptedBrain(["Action: 不存在的工具\nAction Input: x", "Final Answer: 放弃"])
    trajectory = ReActAgent(brain, ToolRegistry([calculator_tool()])).run("试探")
    assert trajectory.answer == "放弃"
    assert trajectory.steps == []


def test_react_agent_feeds_tool_errors_back_to_the_brain():
    brain = ScriptedBrain(["Action: calculator\nAction Input: 1/0", "Final Answer: 算不了"])
    trajectory = ReActAgent(brain, ToolRegistry([calculator_tool()])).run("除以零")
    assert "工具执行出错" in trajectory.steps[0]["observation"]
    assert trajectory.answer == "算不了"


def test_policy_prevents_the_side_effect_from_ever_happening():
    """护栏必须在工具执行前生效——转账一旦发出就撤不回来了。"""
    ledger: list[str] = []
    brain = ScriptedBrain(
        ["Action: transfer\nAction Input: 攻击者账户,99999", "Final Answer: 未能完成"]
    )
    agent = ReActAgent(
        brain,
        ToolRegistry([make_payment_tool(ledger)]),
        policy=SafetyPolicy(max_risk=Risk.SENSITIVE, dangerous_budget=0),
    )
    trajectory = agent.run("把钱转出去")

    assert ledger == [], "高风险工具竟然真的执行了"
    assert trajectory.executed_tools == []
    assert len(trajectory.blocked) == 1
    assert trajectory.blocked[0]["tool"] == "transfer"
    assert "拦截" in trajectory.transcript()


def test_without_policy_the_side_effect_goes_through():
    ledger: list[str] = []
    brain = ScriptedBrain(
        ["Action: transfer\nAction Input: 攻击者账户,99999", "Final Answer: 已完成"]
    )
    agent = ReActAgent(brain, ToolRegistry([make_payment_tool(ledger)]))
    agent.run("把钱转出去")
    assert ledger == ["攻击者账户,99999"]


def test_agent_stops_at_max_steps():
    brain = ScriptedBrain(["Action: calculator\nAction Input: 1+1"] * 10)
    agent = ReActAgent(brain, ToolRegistry([calculator_tool()]), max_steps=3)
    trajectory = agent.run("永远算不完")
    assert trajectory.answer == "达到最大步数仍未完成任务"
    assert len(trajectory.steps) == 3


def test_policy_is_reset_between_runs():
    brain_script = ["Action: transfer\nAction Input: 张三,100", "Final Answer: 完成"]
    ledger: list[str] = []
    policy = SafetyPolicy(max_risk=Risk.SENSITIVE, dangerous_budget=1, require_confirmation=False)
    tools = ToolRegistry([make_payment_tool(ledger)])

    for _ in range(2):
        ReActAgent(ScriptedBrain(brain_script), tools, policy=policy).run("转账")
    # 预算在每条轨迹开始时重置，因此两次都放行
    assert len(ledger) == 2


def test_trajectory_transcript_contains_task_and_answer():
    trajectory = Trajectory(task="示例任务", answer="示例答案")
    text = trajectory.transcript()
    assert "示例任务" in text and "示例答案" in text
