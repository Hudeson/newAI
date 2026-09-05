"""解码策略：贪心、温度采样、Top-k、Top-p、重复惩罚与集束搜索。

大模型"说什么"由两部分决定：模型给出的概率分布，以及我们如何从
这个分布里挑 token。本模块把后者抽象成三个可插拔的钩子：

* ``processors``：在 softmax 之前修改 logits（水印、禁用词、引导生成都走这里）；
* ``selector``：拿到概率分布后决定选哪个 token（隐写术走这里）；
* :class:`SamplingConfig`：常规采样超参。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, Sequence

import numpy as np

__all__ = [
    "SamplingConfig",
    "LogitsProcessor",
    "softmax",
    "apply_repetition_penalty",
    "top_k_filter",
    "top_p_filter",
    "prepare_distribution",
    "generate",
    "beam_search",
]

NEG_INF = -1e30


class SupportsLogits(Protocol):
    """生成接口只要求模型能对一段前缀给出下一个 token 的 logits。"""

    def next_token_logits(self, ids: Sequence[int]) -> np.ndarray: ...


LogitsProcessor = Callable[[Sequence[int], np.ndarray], np.ndarray]
"""``(已生成的完整 id 序列, logits) -> 新 logits``"""

TokenSelector = Callable[[Sequence[int], np.ndarray, np.random.Generator], int]
"""``(前缀, 概率分布, 随机源) -> 选中的 token id``"""


@dataclass
class SamplingConfig:
    """采样超参数。``temperature<=0`` 表示贪心解码。"""

    temperature: float = 1.0
    top_k: int | None = None
    top_p: float | None = None
    repetition_penalty: float = 1.0
    seed: int | None = None

    @property
    def greedy(self) -> bool:
        return self.temperature <= 0.0


def softmax(logits: np.ndarray) -> np.ndarray:
    """数值稳定的 softmax。"""
    shifted = logits - np.max(logits)
    exp = np.exp(shifted)
    return exp / exp.sum()


def apply_repetition_penalty(logits: np.ndarray, generated: Sequence[int], penalty: float) -> np.ndarray:
    """对已出现过的 token 施加重复惩罚（CTRL 论文的做法）。"""
    if penalty == 1.0 or not len(generated):
        return logits
    out = logits.copy()
    for token in set(int(t) for t in generated):
        if out[token] > 0:
            out[token] /= penalty
        else:
            out[token] *= penalty
    return out


def top_k_filter(logits: np.ndarray, k: int) -> np.ndarray:
    """只保留概率最高的 k 个 token。"""
    if k <= 0 or k >= logits.size:
        return logits
    out = np.full_like(logits, NEG_INF)
    top = np.argpartition(logits, -k)[-k:]
    out[top] = logits[top]
    return out


def top_p_filter(logits: np.ndarray, p: float) -> np.ndarray:
    """核采样：保留累计概率刚好超过 p 的最小 token 集合。"""
    if not 0.0 < p < 1.0:
        return logits
    order = np.argsort(logits)[::-1]
    probs = softmax(logits)[order]
    cumulative = np.cumsum(probs)
    # 至少保留 1 个 token；第一个使累计概率 >= p 的位置也要保留
    cutoff = int(np.searchsorted(cumulative, p)) + 1
    keep = order[:cutoff]
    out = np.full_like(logits, NEG_INF)
    out[keep] = logits[keep]
    return out


def prepare_distribution(
    logits: np.ndarray,
    generated: Sequence[int] = (),
    config: SamplingConfig | None = None,
) -> np.ndarray:
    """按配置依次施加重复惩罚、温度、Top-k、Top-p，返回概率分布。"""
    config = config or SamplingConfig()
    logits = np.asarray(logits, dtype=np.float64)
    logits = apply_repetition_penalty(logits, generated, config.repetition_penalty)
    temperature = 1.0 if config.greedy else config.temperature
    logits = logits / temperature
    if config.top_k:
        logits = top_k_filter(logits, config.top_k)
    if config.top_p is not None:
        logits = top_p_filter(logits, config.top_p)
    return softmax(logits)


class _Runner:
    """统一封装"带 KV Cache"与"每步重算"两种前向方式。"""

    def __init__(self, model: SupportsLogits, prompt: Sequence[int], use_cache: bool) -> None:
        self.model = model
        self.use_cache = use_cache and hasattr(model, "empty_caches")
        self.ids = list(int(t) for t in prompt)
        if self.use_cache:
            from .autograd import no_grad

            self._no_grad = no_grad
            self.caches = model.empty_caches()  # type: ignore[attr-defined]
            with no_grad():
                out = model(np.asarray(self.ids, dtype=np.int64)[None, :], caches=self.caches, offset=0)
            self._logits = out.data[0, -1]
            self._offset = len(self.ids)
        else:
            self._logits = model.next_token_logits(self.ids)

    @property
    def logits(self) -> np.ndarray:
        return self._logits

    def push(self, token: int) -> None:
        self.ids.append(int(token))
        if self.use_cache:
            with self._no_grad():
                out = self.model(  # type: ignore[operator]
                    np.asarray([[token]], dtype=np.int64), caches=self.caches, offset=self._offset
                )
            self._logits = out.data[0, -1]
            self._offset += 1
        else:
            self._logits = self.model.next_token_logits(self.ids)


def generate(
    model: SupportsLogits,
    prompt_ids: Sequence[int],
    max_new_tokens: int = 32,
    config: SamplingConfig | None = None,
    processors: Sequence[LogitsProcessor] = (),
    selector: TokenSelector | None = None,
    stop_ids: Sequence[int] = (),
    rng: np.random.Generator | None = None,
    use_cache: bool = True,
) -> list[int]:
    """自回归生成，返回"新生成"的 token（不含 prompt）。"""
    config = config or SamplingConfig()
    rng = rng or np.random.default_rng(config.seed)
    stop = set(int(t) for t in stop_ids)

    runner = _Runner(model, prompt_ids, use_cache)
    generated: list[int] = []

    for _ in range(max_new_tokens):
        logits = runner.logits
        for processor in processors:
            logits = processor(runner.ids, logits)
        probs = prepare_distribution(logits, runner.ids, config)

        if selector is not None:
            token = int(selector(runner.ids, probs, rng))
        elif config.greedy:
            token = int(np.argmax(probs))
        else:
            token = int(rng.choice(len(probs), p=probs))

        generated.append(token)
        if token in stop:
            break
        runner.push(token)

    return generated


def beam_search(
    model: SupportsLogits,
    prompt_ids: Sequence[int],
    max_new_tokens: int = 16,
    beam_width: int = 4,
    length_penalty: float = 1.0,
    eos_id: int | None = None,
) -> list[list[int]]:
    """集束搜索，返回按分数从高到低排序的候选序列（不含 prompt）。

    分数为长度归一化的对数似然 ``logP / len**length_penalty``。
    """
    prompt = list(int(t) for t in prompt_ids)
    beams: list[tuple[float, list[int], bool]] = [(0.0, [], False)]

    for _ in range(max_new_tokens):
        if all(finished for _, _, finished in beams):
            break
        candidates: list[tuple[float, list[int], bool]] = []
        for logprob, tokens, finished in beams:
            if finished:
                candidates.append((logprob, tokens, True))
                continue
            logits = model.next_token_logits(prompt + tokens)
            log_probs = np.log(softmax(np.asarray(logits, dtype=np.float64)) + 1e-30)
            top = np.argpartition(log_probs, -beam_width)[-beam_width:]
            for token in top:
                token = int(token)
                candidates.append(
                    (logprob + float(log_probs[token]), tokens + [token], token == eos_id)
                )
        candidates.sort(key=lambda item: item[0] / (max(len(item[1]), 1) ** length_penalty), reverse=True)
        beams = candidates[:beam_width]

    beams.sort(key=lambda item: item[0] / (max(len(item[1]), 1) ** length_penalty), reverse=True)
    return [tokens for _, tokens, _ in beams]
