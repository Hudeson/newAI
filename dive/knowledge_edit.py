"""知识编辑：ROME 风格的秩一更新。

大模型学到的一条事实（"埃菲尔铁塔位于巴黎"）如果过时了，重新训练一遍
显然不现实。ROME（*Locating and Editing Factual Associations in GPT*）
指出：Transformer 中 FFN 的第二个线性层可以看作一个**线性关联记忆**——
它把"主语的表示"（key）映射到"客体的表示"（value）。

于是改一条事实就变成一个带约束的最小二乘问题：在"新事实成立"
（``W' k* = v*``）的前提下，让权重改动对其他 key 的影响最小。它有闭式解：

.. math:: W' = W + \\frac{(v^* - Wk^*)\\,(C^{-1}k^*)^{\\top}}{(C^{-1}k^*)^{\\top}k^*}

其中 ``C = E[kk^T]`` 是 key 的二阶矩，由一批"我们不想破坏"的知识估计而来。
本模块实现了这个更新，并提供朴素梯度微调作为对照——你会看到后者虽然也能
改对目标事实，却会显著破坏其他知识。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np

__all__ = ["AssociativeMemory", "FactStore", "rome_edit", "finetune_edit", "EditReport"]


class AssociativeMemory:
    """线性关联记忆 ``v = W^T k``（``W`` 形状为 ``(d_key, d_value)``）。"""

    def __init__(self, weight: np.ndarray) -> None:
        self.weight = np.asarray(weight, dtype=np.float64)

    @property
    def d_key(self) -> int:
        return self.weight.shape[0]

    @property
    def d_value(self) -> int:
        return self.weight.shape[1]

    @classmethod
    def fit(cls, keys: np.ndarray, values: np.ndarray, ridge: float = 1e-6) -> "AssociativeMemory":
        """用岭回归把 ``keys -> values`` 压进一个权重矩阵（模拟"预训练"）。"""
        keys = np.asarray(keys, dtype=np.float64)
        values = np.asarray(values, dtype=np.float64)
        gram = keys.T @ keys + ridge * np.eye(keys.shape[1])
        return cls(np.linalg.solve(gram, keys.T @ values))

    def recall(self, keys: np.ndarray) -> np.ndarray:
        return np.asarray(keys, dtype=np.float64) @ self.weight

    def copy(self) -> "AssociativeMemory":
        return AssociativeMemory(self.weight.copy())


@dataclass
class EditReport:
    """一次编辑的效果评估。"""

    efficacy: float
    """新事实的召回相似度（越接近 1 越好）。"""

    locality: float
    """其余事实的平均召回相似度（越接近 1 说明副作用越小）。"""

    max_drift: float
    """其余事实中被破坏得最厉害的一条的偏移量。"""

    weight_change: float
    """权重改动的 Frobenius 范数。"""

    rank: int
    """权重改动的秩。"""

    extras: dict[str, float] = field(default_factory=dict)

    def __str__(self) -> str:  # pragma: no cover - 展示用
        return (
            f"efficacy={self.efficacy:.4f} locality={self.locality:.4f} "
            f"max_drift={self.max_drift:.4f} |ΔW|={self.weight_change:.4f} rank(ΔW)={self.rank}"
        )


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(a @ b / denom) if denom else 0.0


def rome_edit(
    memory: AssociativeMemory,
    key: np.ndarray,
    value: np.ndarray,
    covariance: np.ndarray | None = None,
    ridge: float = 1e-4,
) -> AssociativeMemory:
    """对 ``memory`` 施加一次秩一编辑，使 ``key`` 召回 ``value``。

    ``covariance`` 是"不希望被破坏的知识"的二阶矩 ``E[kk^T]``；缺省时退化为
    单位阵，此时更新方向就是 ``key`` 本身（等价于最小 L2 改动）。
    """
    key = np.asarray(key, dtype=np.float64).reshape(-1)
    value = np.asarray(value, dtype=np.float64).reshape(-1)
    if key.shape[0] != memory.d_key or value.shape[0] != memory.d_value:
        raise ValueError("key / value 维度与记忆矩阵不匹配")

    if covariance is None:
        direction = key
    else:
        cov = np.asarray(covariance, dtype=np.float64)
        cov = cov + ridge * np.trace(cov) / cov.shape[0] * np.eye(cov.shape[0])
        direction = np.linalg.solve(cov, key)

    denom = float(direction @ key)
    if abs(denom) < 1e-12:
        raise ValueError("更新方向与 key 正交，无法完成编辑")

    residual = value - memory.recall(key)
    delta = np.outer(direction / denom, residual)
    return AssociativeMemory(memory.weight + delta)


def finetune_edit(
    memory: AssociativeMemory,
    key: np.ndarray,
    value: np.ndarray,
    steps: int = 200,
    lr: float = 0.1,
) -> AssociativeMemory:
    """对照组：只用目标事实做梯度下降，不做任何保护。"""
    key = np.asarray(key, dtype=np.float64).reshape(-1)
    value = np.asarray(value, dtype=np.float64).reshape(-1)
    weight = memory.weight.copy()
    for _ in range(steps):
        residual = key @ weight - value
        weight -= lr * np.outer(key, residual)
    return AssociativeMemory(weight)


def evaluate_edit(
    before: AssociativeMemory,
    after: AssociativeMemory,
    edit_key: np.ndarray,
    edit_value: np.ndarray,
    other_keys: np.ndarray,
) -> EditReport:
    """比较编辑前后：目标事实是否改对、其他事实是否被殃及。"""
    edit_key = np.asarray(edit_key, dtype=np.float64).reshape(-1)
    edit_value = np.asarray(edit_value, dtype=np.float64).reshape(-1)
    other_keys = np.asarray(other_keys, dtype=np.float64)

    efficacy = _cosine(after.recall(edit_key), edit_value)

    old = before.recall(other_keys)
    new = after.recall(other_keys)
    sims = np.array([_cosine(old[i], new[i]) for i in range(other_keys.shape[0])])
    drift = np.linalg.norm(new - old, axis=1) / (np.linalg.norm(old, axis=1) + 1e-12)

    delta = after.weight - before.weight
    return EditReport(
        efficacy=float(efficacy),
        locality=float(sims.mean()),
        max_drift=float(drift.max()),
        weight_change=float(np.linalg.norm(delta)),
        rank=int(np.linalg.matrix_rank(delta, tol=1e-8)),
    )


class FactStore:
    """把"文字事实"映射成可编辑的向量记忆，让实验读起来像真的知识库。

    每个主语和每个客体都被分配一个固定的随机向量；``fit`` 之后，
    ``recall("埃菲尔铁塔位于")`` 会返回最接近的客体名称。
    """

    def __init__(self, dim: int = 64, seed: int = 0, correlation: float = 0.0) -> None:
        """``correlation`` 控制主语向量之间的相关性。

        真实模型里不同主语的表示远非正交（它们共享大量语言学结构），
        正是这种相关性让"改一条事实"会牵连到别的事实。把 correlation 调到
        0 会让各条知识互不干扰，ROME 的协方差项也就失去意义了。
        """
        if not 0.0 <= correlation < 1.0:
            raise ValueError("correlation 必须落在 [0, 1)")
        self.dim = dim
        self.correlation = correlation
        self.rng = np.random.default_rng(seed)
        shared = self.rng.normal(size=dim)
        self._shared = shared / np.linalg.norm(shared)
        self.subject_vectors: dict[str, np.ndarray] = {}
        self.object_vectors: dict[str, np.ndarray] = {}
        self.facts: list[tuple[str, str]] = []
        self.memory: AssociativeMemory | None = None

    def _vector(
        self, table: dict[str, np.ndarray], name: str, correlated: bool = False
    ) -> np.ndarray:
        if name not in table:
            vec = self.rng.normal(size=self.dim)
            if correlated and self.correlation > 0:
                vec = vec / np.linalg.norm(vec)
                vec = self.correlation * self._shared + np.sqrt(1 - self.correlation**2) * vec
            table[name] = vec / np.linalg.norm(vec)
        return table[name]

    def add(self, subject: str, obj: str, as_fact: bool = True) -> None:
        """登记一条事实；``as_fact=False`` 只注册向量而不加入知识库。"""
        self._vector(self.subject_vectors, subject, correlated=True)
        self._vector(self.object_vectors, obj)
        if as_fact:
            self.facts.append((subject, obj))

    def add_many(self, facts: Iterable[tuple[str, str]]) -> None:
        for subject, obj in facts:
            self.add(subject, obj)

    def keys(self, subjects: Sequence[str] | None = None) -> np.ndarray:
        names = subjects if subjects is not None else [s for s, _ in self.facts]
        return np.stack([self.subject_vectors[name] for name in names])

    def values(self) -> np.ndarray:
        return np.stack([self.object_vectors[o] for _, o in self.facts])

    def fit(self, ridge: float = 1e-6) -> AssociativeMemory:
        self.memory = AssociativeMemory.fit(self.keys(), self.values(), ridge=ridge)
        return self.memory

    def covariance(self) -> np.ndarray:
        keys = self.keys()
        return keys.T @ keys / keys.shape[0]

    def recall(self, subject: str, memory: AssociativeMemory | None = None) -> str:
        """返回与召回向量最相似的客体名称。"""
        memory = memory or self.memory
        if memory is None:
            raise RuntimeError("请先调用 fit()")
        query = memory.recall(self.subject_vectors[subject])
        names = list(self.object_vectors)
        sims = [_cosine(query, self.object_vectors[name]) for name in names]
        return names[int(np.argmax(sims))]

    def accuracy(self, memory: AssociativeMemory, skip: str | None = None) -> float:
        """除 ``skip`` 之外，有多少条事实仍然召回正确。"""
        items = [(s, o) for s, o in self.facts if s != skip]
        correct = sum(1 for subject, obj in items if self.recall(subject, memory) == obj)
        return correct / len(items) if items else 1.0
