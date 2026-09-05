"""提示工程：零样本 / 少样本 / 思维链 / 自洽投票。

提示词不是玄学，它改变的是模型在给定条件下的输出分布。本模块提供
可复用的提示模板与答案抽取、投票工具，配合 ``labs/lab02_prompting_cot.py``
可以在一个真实（虽然很小）的模型上量化每种技巧带来的收益。

同时提供 :class:`OpenAICompatClient`，方便读者把同一套实验换到
真实大模型（OpenAI / DeepSeek / vLLM / Ollama 等兼容接口）上跑。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Protocol, Sequence

__all__ = [
    "Example",
    "zero_shot_prompt",
    "few_shot_prompt",
    "chain_of_thought_prompt",
    "extract_answer",
    "majority_vote",
    "SelfConsistencyResult",
    "self_consistency",
    "ChatClient",
    "OpenAICompatClient",
]

_ANSWER_PATTERN = re.compile(r"(-?\d+(?:\.\d+)?)")

COT_TRIGGER = "让我们一步一步地思考。"


@dataclass
class Example:
    """一条少样本示例。"""

    question: str
    answer: str
    reasoning: str | None = None


def zero_shot_prompt(question: str, instruction: str | None = None) -> str:
    """零样本提示。"""
    head = f"{instruction}\n\n" if instruction else ""
    return f"{head}问题：{question}\n答案："


def few_shot_prompt(
    examples: Sequence[Example],
    question: str,
    with_reasoning: bool = False,
    instruction: str | None = None,
) -> str:
    """少样本提示；``with_reasoning=True`` 时即为 Few-shot CoT。"""
    blocks = [instruction] if instruction else []
    for example in examples:
        if with_reasoning and example.reasoning:
            blocks.append(f"问题：{example.question}\n推理：{example.reasoning}\n答案：{example.answer}")
        else:
            blocks.append(f"问题：{example.question}\n答案：{example.answer}")
    blocks.append(f"问题：{question}\n" + ("推理：" if with_reasoning else "答案："))
    return "\n\n".join(blocks)


def chain_of_thought_prompt(question: str, trigger: str = COT_TRIGGER) -> str:
    """零样本思维链：只加一句"一步一步想"。"""
    return f"问题：{question}\n{trigger}\n"


def extract_answer(text: str, pattern: re.Pattern[str] | None = None, last: bool = True) -> str | None:
    """从模型输出里抽取最终答案（默认取最后一个数字）。"""
    matches = (pattern or _ANSWER_PATTERN).findall(text)
    if not matches:
        return None
    return matches[-1] if last else matches[0]


def majority_vote(answers: Sequence[str | None]) -> tuple[str | None, int, int]:
    """多数投票，返回 ``(答案, 得票数, 有效票数)``。"""
    valid = [a for a in answers if a is not None]
    if not valid:
        return None, 0, 0
    answer, votes = Counter(valid).most_common(1)[0]
    return answer, votes, len(valid)


@dataclass
class SelfConsistencyResult:
    """自洽解码（Self-Consistency）的结果。"""

    answer: str | None
    votes: int
    total: int
    samples: list[str]
    answers: list[str | None]

    @property
    def confidence(self) -> float:
        return self.votes / self.total if self.total else 0.0


def self_consistency(
    sample_once: Callable[[int], str],
    k: int = 8,
    extractor: Callable[[str], str | None] = extract_answer,
) -> SelfConsistencyResult:
    """采样 ``k`` 条推理链后对最终答案投票。

    ``sample_once(i)`` 需要返回第 i 条采样得到的完整输出文本。
    """
    samples = [sample_once(index) for index in range(k)]
    answers = [extractor(text) for text in samples]
    answer, votes, total = majority_vote(answers)
    return SelfConsistencyResult(answer=answer, votes=votes, total=total, samples=samples, answers=answers)


class ChatClient(Protocol):
    """对话模型的最小接口。"""

    def complete(self, prompt: str, **kwargs: object) -> str: ...


class OpenAICompatClient:
    """OpenAI 兼容接口的极简客户端（只依赖标准库）。

    可用于 OpenAI、DeepSeek、Kimi、vLLM ``--api-server``、Ollama 等服务：

    >>> client = OpenAICompatClient(base_url="http://localhost:11434/v1",
    ...                             api_key="ollama", model="qwen2.5:7b")  # doctest: +SKIP
    >>> client.complete("你好")  # doctest: +SKIP
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60.0,
        temperature: float = 0.7,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.temperature = temperature

    def complete(self, prompt: str, **kwargs: object) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get("temperature", self.temperature),
        }
        if "max_tokens" in kwargs:
            payload["max_tokens"] = kwargs["max_tokens"]

        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as error:  # pragma: no cover - 依赖外部服务
            raise RuntimeError(f"调用 {self.base_url} 失败：{error}") from error
        return body["choices"][0]["message"]["content"]
