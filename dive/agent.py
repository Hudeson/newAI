"""大模型智能体：ReAct 运行时、工具注册与安全护栏。

一个智能体 = **大脑**（决定下一步做什么）+ **运行时**（把决定变成真实调用）。
本模块实现的是运行时部分，它是真实可用的：

* :class:`ToolRegistry`：登记工具、声明风险等级、执行调用；
* :class:`ReActAgent`：解析 ``Thought / Action / Action Input`` 循环，
  把工具返回值作为 ``Observation`` 喂回大脑；
* :class:`SafetyPolicy`：在**工具真正执行之前**拦截高风险动作——这是智能体
  安全的关键位置，因为一旦调用发出，副作用就无法撤回了。

大脑是可插拔的：离线测试用 :class:`ScriptedBrain`，接真实模型时换成
:class:`~dive.prompting.OpenAICompatClient` 即可。
"""

from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass, field
from typing import Callable, Protocol, Sequence

__all__ = [
    "Risk",
    "Tool",
    "ToolRegistry",
    "Action",
    "parse_action",
    "SafetyPolicy",
    "GuardDecision",
    "Brain",
    "ScriptedBrain",
    "ReActAgent",
    "Trajectory",
    "calculator_tool",
    "make_kv_tools",
    "make_payment_tool",
]


class Risk:
    """工具风险等级。"""

    SAFE = "safe"
    """只读、无副作用。"""

    SENSITIVE = "sensitive"
    """会读取隐私数据或访问外部网络。"""

    DANGEROUS = "dangerous"
    """有不可撤销的副作用：转账、删除、发送消息……"""

    ORDER = {SAFE: 0, SENSITIVE: 1, DANGEROUS: 2}


@dataclass
class Tool:
    """一个可被智能体调用的工具。"""

    name: str
    description: str
    run: Callable[[str], str]
    risk: str = Risk.SAFE


class ToolRegistry:
    """工具集合。"""

    def __init__(self, tools: Sequence[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def describe(self) -> str:
        return "\n".join(
            f"- {tool.name}（{tool.risk}）：{tool.description}" for tool in self._tools.values()
        )


@dataclass
class Action:
    """智能体的一步动作。"""

    tool: str | None
    argument: str
    final_answer: str | None = None

    @property
    def is_final(self) -> bool:
        return self.final_answer is not None


_ACTION_RE = re.compile(r"Action\s*[:：]\s*(?P<tool>[\w\-]+)\s*(?:\n|.)*?Action Input\s*[:：]\s*(?P<arg>.*)", re.S)
_FINAL_RE = re.compile(r"Final Answer\s*[:：]\s*(?P<answer>.*)", re.S)


def parse_action(text: str) -> Action:
    """从大脑输出里解析出动作。"""
    final = _FINAL_RE.search(text)
    if final:
        return Action(tool=None, argument="", final_answer=final.group("answer").strip())
    match = _ACTION_RE.search(text)
    if match:
        return Action(tool=match.group("tool").strip(), argument=match.group("arg").strip().splitlines()[0])
    return Action(tool=None, argument="", final_answer=text.strip())


@dataclass
class GuardDecision:
    """护栏的判定结果。"""

    allowed: bool
    reason: str = ""
    rule: str = ""


class SafetyPolicy:
    """执行前护栏。

    三层检查，任意一层不通过就拦截：

    1. **风险上限**：超过 ``max_risk`` 的工具一律不放行（除非人工确认）；
    2. **参数模式**：命中黑名单正则的参数直接拒绝（如超额转账、通配删除）；
    3. **预算**：限制单条轨迹内高风险调用的次数，避免"失控循环"。
    """

    def __init__(
        self,
        max_risk: str = Risk.SENSITIVE,
        forbidden_patterns: Sequence[str] = (),
        dangerous_budget: int = 0,
        require_confirmation: bool = True,
    ) -> None:
        self.max_risk = max_risk
        self.forbidden = [re.compile(pattern) for pattern in forbidden_patterns]
        self.dangerous_budget = dangerous_budget
        self.require_confirmation = require_confirmation
        self._spent = 0

    def reset(self) -> None:
        self._spent = 0

    def check(self, tool: Tool, argument: str) -> GuardDecision:
        for pattern in self.forbidden:
            if pattern.search(argument):
                return GuardDecision(False, f"参数命中禁止模式 {pattern.pattern}", "参数黑名单")

        if Risk.ORDER[tool.risk] > Risk.ORDER[self.max_risk]:
            if self._spent >= self.dangerous_budget:
                return GuardDecision(
                    False,
                    f"工具 {tool.name} 风险等级为 {tool.risk}，超出允许上限 {self.max_risk}",
                    "风险上限",
                )
            self._spent += 1
            if self.require_confirmation:
                return GuardDecision(False, f"工具 {tool.name} 需要人工确认后才能执行", "人工确认")
        return GuardDecision(True)


class Brain(Protocol):
    """大脑：给定提示返回下一步的文本决策。"""

    def complete(self, prompt: str, **kwargs: object) -> str: ...


class ScriptedBrain:
    """离线测试用的大脑：按预先写好的剧本逐条输出决策。"""

    def __init__(self, script: Sequence[str]) -> None:
        self.script = list(script)
        self.cursor = 0

    def complete(self, prompt: str, **kwargs: object) -> str:
        if self.cursor >= len(self.script):
            return "Final Answer: 剧本已结束"
        step = self.script[self.cursor]
        self.cursor += 1
        return step


@dataclass
class Trajectory:
    """一条完整的执行轨迹，便于事后审计。"""

    task: str
    steps: list[dict[str, str]] = field(default_factory=list)
    answer: str | None = None
    blocked: list[dict[str, str]] = field(default_factory=list)

    @property
    def executed_tools(self) -> list[str]:
        return [step["tool"] for step in self.steps if step.get("tool")]

    def transcript(self) -> str:
        lines = [f"任务：{self.task}"]
        for index, step in enumerate(self.steps, 1):
            lines.append(f"  {index}. {step['tool']}({step['argument']}) -> {step['observation']}")
        for block in self.blocked:
            lines.append(f"  [拦截] {block['tool']}({block['argument']})：{block['reason']}")
        lines.append(f"最终回答：{self.answer}")
        return "\n".join(lines)


PROMPT_TEMPLATE = """你是一个可以使用工具的智能体。可用工具：
{tools}

请按以下格式作答：
Thought: 你的思考
Action: 工具名
Action Input: 工具参数
或者当你已经可以回答时：
Final Answer: 最终答案

任务：{task}
{scratchpad}"""


class ReActAgent:
    """ReAct 智能体运行时。"""

    def __init__(
        self,
        brain: Brain,
        tools: ToolRegistry,
        policy: SafetyPolicy | None = None,
        max_steps: int = 8,
    ) -> None:
        self.brain = brain
        self.tools = tools
        self.policy = policy
        self.max_steps = max_steps

    def run(self, task: str) -> Trajectory:
        trajectory = Trajectory(task=task)
        if self.policy is not None:
            self.policy.reset()
        scratchpad = ""

        for _ in range(self.max_steps):
            prompt = PROMPT_TEMPLATE.format(
                tools=self.tools.describe(), task=task, scratchpad=scratchpad
            )
            decision = self.brain.complete(prompt)
            action = parse_action(decision)

            if action.is_final:
                trajectory.answer = action.final_answer
                return trajectory

            tool = self.tools.get(action.tool or "")
            if tool is None:
                observation = f"错误：不存在名为 {action.tool} 的工具"
            else:
                verdict = self.policy.check(tool, action.argument) if self.policy else GuardDecision(True)
                if not verdict.allowed:
                    observation = f"该操作已被安全策略拦截（{verdict.rule}）：{verdict.reason}"
                    trajectory.blocked.append(
                        {
                            "tool": tool.name,
                            "argument": action.argument,
                            "reason": verdict.reason,
                            "rule": verdict.rule,
                        }
                    )
                else:
                    try:
                        observation = tool.run(action.argument)
                    except Exception as error:  # noqa: BLE001 - 工具异常要回灌给大脑
                        observation = f"工具执行出错：{error}"
                    trajectory.steps.append(
                        {"tool": tool.name, "argument": action.argument, "observation": observation}
                    )

            scratchpad += f"\n{decision}\nObservation: {observation}\n"

        trajectory.answer = "达到最大步数仍未完成任务"
        return trajectory


# ----------------------------------------------------------------------
# 内置工具
# ----------------------------------------------------------------------
_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.Mod: operator.mod,
}


def _safe_eval(node: ast.AST) -> float:
    """只允许算术表达式的求值器——绝不使用 ``eval``。"""
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        return _OPERATORS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPERATORS:
        return _OPERATORS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("表达式中包含不被允许的语法")


def calculator_tool() -> Tool:
    """安全的计算器工具。"""

    def run(expression: str) -> str:
        value = _safe_eval(ast.parse(expression.strip(), mode="eval"))
        return f"{value:g}"

    return Tool(
        name="calculator",
        description="计算一个算术表达式，例如 12*(3+4)",
        run=run,
        risk=Risk.SAFE,
    )


def make_kv_tools(store: dict[str, str] | None = None) -> tuple[Tool, Tool]:
    """一对读写工具，用来演示"读安全、写敏感"的风险分级。"""
    data = store if store is not None else {}

    def read(key: str) -> str:
        return data.get(key.strip(), "（无此记录）")

    def write(argument: str) -> str:
        key, _, value = argument.partition("=")
        data[key.strip()] = value.strip()
        return f"已写入 {key.strip()}"

    return (
        Tool("kv_read", "按键读取备忘录内容", read, Risk.SAFE),
        Tool("kv_write", "写入备忘录，格式 key=value", write, Risk.SENSITIVE),
    )


def make_payment_tool(ledger: list[str] | None = None) -> Tool:
    """高风险工具：模拟转账，用来验证护栏是否真的拦得住。"""
    records = ledger if ledger is not None else []

    def run(argument: str) -> str:
        records.append(argument)
        return f"已转账：{argument}"

    return Tool("transfer", "向指定账户转账，格式 账户,金额", run, Risk.DANGEROUS)
