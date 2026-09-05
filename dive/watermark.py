"""大模型文本水印：KGW 绿名单算法。

参考 Kirchenbauer 等人 *A Watermark for Large Language Models* (ICML 2023)。

核心思想非常朴素：

1. **加水印**：生成第 t 个 token 前，用前一个 token 作为随机种子，把词表
   伪随机地划分成"绿名单"（占比 γ）和"红名单"，然后给所有绿名单 token
   的 logit 加上一个偏置 δ。人类读不出区别，但生成结果会显著偏向绿名单。
2. **检测**：拥有同一个哈希密钥的人可以重放这个划分，数一数文本里有多少
   token 落在绿名单里。无水印文本中绿 token 比例应当接近 γ，于是可以做
   单侧 z 检验：

   .. math:: z = \\frac{|s|_G - \\gamma T}{\\sqrt{T\\gamma(1-\\gamma)}}

z 越大，文本来自加了水印的模型的证据越强。检测**不需要**访问模型本身，
只需要密钥——这正是它适合做溯源的原因。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np

__all__ = ["WatermarkConfig", "GreenListWatermark", "DetectionResult"]

_HASH_PRIME = 15485863


@dataclass
class WatermarkConfig:
    """水印超参。

    ``gamma`` 越小、``delta`` 越大，水印越强，但对生成质量的干扰也越大。
    """

    gamma: float = 0.25
    delta: float = 2.0
    hash_key: int = 15485917
    context_width: int = 1

    def __post_init__(self) -> None:
        if not 0.0 < self.gamma < 1.0:
            raise ValueError("gamma 必须落在 (0, 1)")
        if self.context_width < 1:
            raise ValueError("context_width 至少为 1")


@dataclass
class DetectionResult:
    """检测输出。"""

    z_score: float
    p_value: float
    green_tokens: int
    scored_tokens: int
    green_fraction: float

    def is_watermarked(self, threshold: float = 4.0) -> bool:
        """z 超过阈值即判定为含水印；4.0 对应约 3e-5 的误报率。"""
        return self.z_score >= threshold

    def __str__(self) -> str:  # pragma: no cover - 展示用
        return (
            f"z={self.z_score:.3f} p={self.p_value:.3e} "
            f"绿token={self.green_tokens}/{self.scored_tokens} ({self.green_fraction:.1%})"
        )


class GreenListWatermark:
    """绿名单水印的生成端与检测端。

    实例本身就是一个 :data:`~dive.decoding.LogitsProcessor`，可以直接传给
    :func:`dive.decoding.generate`。
    """

    def __init__(self, vocab_size: int, config: WatermarkConfig | None = None) -> None:
        self.vocab_size = vocab_size
        self.config = config or WatermarkConfig()
        self.green_size = max(1, int(self.config.gamma * vocab_size))

    # ------------------------------------------------------------------
    def _seed(self, context: Sequence[int]) -> int:
        """由前若干个 token 派生伪随机种子。"""
        seed = self.config.hash_key
        for token in context:
            seed = (seed * _HASH_PRIME + int(token) + 1) % (2**61 - 1)
        return seed

    def green_ids(self, context: Sequence[int]) -> np.ndarray:
        """给定上文，返回绿名单 token id。"""
        rng = np.random.default_rng(self._seed(context))
        return rng.permutation(self.vocab_size)[: self.green_size]

    def green_mask(self, context: Sequence[int]) -> np.ndarray:
        mask = np.zeros(self.vocab_size, dtype=bool)
        mask[self.green_ids(context)] = True
        return mask

    # ------------------------------------------------------------------
    def __call__(self, ids: Sequence[int], logits: np.ndarray) -> np.ndarray:
        """作为 logits processor：给绿名单 token 加偏置 δ。"""
        width = self.config.context_width
        if len(ids) < width:
            return logits
        context = list(ids)[-width:]
        biased = np.asarray(logits, dtype=np.float64).copy()
        biased[self.green_ids(context)] += self.config.delta
        return biased

    # ------------------------------------------------------------------
    def detect(self, ids: Sequence[int]) -> DetectionResult:
        """统计 ``ids`` 中落在绿名单里的 token 并做 z 检验。"""
        tokens = [int(t) for t in ids]
        width = self.config.context_width
        green = 0
        scored = 0
        for index in range(width, len(tokens)):
            context = tokens[index - width : index]
            if self.green_mask(context)[tokens[index]]:
                green += 1
            scored += 1

        if scored == 0:
            return DetectionResult(0.0, 1.0, 0, 0, 0.0)

        gamma = self.config.gamma
        z = (green - gamma * scored) / math.sqrt(scored * gamma * (1 - gamma))
        p_value = 0.5 * math.erfc(z / math.sqrt(2))
        return DetectionResult(z, p_value, green, scored, green / scored)
