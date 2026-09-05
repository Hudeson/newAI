"""极简反向模式自动微分引擎（纯 NumPy）。

本模块是整个教程的计算基础。它只依赖 NumPy，因此可以在任何一台
没有 GPU、没有 PyTorch 的机器上运行，方便读者把注意力放在"大模型
到底在算什么"上，而不是框架细节上。

设计要点：

* :class:`Tensor` 同时持有 ``data``（前向值）与 ``grad``（梯度）；
* 每个算子在前向时记录一个 ``_backward`` 闭包，反向时按拓扑序回放；
* 广播由 :func:`_unbroadcast` 统一处理，使 ``+``/``*``/``@`` 的梯度形状
  始终与输入一致；
* ``softmax`` / ``log_softmax`` / ``cross_entropy`` 采用融合实现，
  既数值稳定又避免手工推导 ``max`` 的梯度。

>>> x = Tensor([[1.0, 2.0]], requires_grad=True)
>>> y = (x * x).sum()
>>> y.backward()
>>> x.grad
array([[2., 4.]])
"""

from __future__ import annotations

from typing import Callable, Iterable, Sequence

import numpy as np

__all__ = ["Tensor", "Parameter", "no_grad", "is_grad_enabled", "cat", "cross_entropy"]


_GRAD_ENABLED = True


class no_grad:
    """上下文管理器：在推理 / 生成阶段关闭计算图记录，节省内存。"""

    def __enter__(self) -> "no_grad":
        global _GRAD_ENABLED
        self._prev = _GRAD_ENABLED
        _GRAD_ENABLED = False
        return self

    def __exit__(self, *exc: object) -> None:
        global _GRAD_ENABLED
        _GRAD_ENABLED = self._prev


def is_grad_enabled() -> bool:
    return _GRAD_ENABLED


def _unbroadcast(grad: np.ndarray, shape: tuple[int, ...]) -> np.ndarray:
    """把广播后的梯度求和回原始 ``shape``。"""
    while grad.ndim > len(shape):
        grad = grad.sum(axis=0)
    for axis, size in enumerate(shape):
        if size == 1 and grad.shape[axis] != 1:
            grad = grad.sum(axis=axis, keepdims=True)
    return grad.reshape(shape)


def _as_array(value: object) -> np.ndarray:
    if isinstance(value, Tensor):
        return value.data
    return np.asarray(value, dtype=np.float64)


class Tensor:
    """带梯度追踪的多维数组。"""

    __slots__ = ("data", "grad", "requires_grad", "_backward", "_prev")

    def __init__(
        self,
        data: object,
        requires_grad: bool = False,
        _prev: Sequence["Tensor"] = (),
        _backward: Callable[[], None] | None = None,
    ) -> None:
        self.data = np.asarray(data, dtype=np.float64)
        self.requires_grad = requires_grad and _GRAD_ENABLED
        self.grad: np.ndarray | None = None
        self._prev: tuple[Tensor, ...] = tuple(_prev)
        self._backward: Callable[[], None] = _backward or (lambda: None)

    # ------------------------------------------------------------------
    # 基本属性
    # ------------------------------------------------------------------
    @property
    def shape(self) -> tuple[int, ...]:
        return self.data.shape

    @property
    def ndim(self) -> int:
        return self.data.ndim

    @property
    def size(self) -> int:
        return self.data.size

    def item(self) -> float:
        return float(self.data.reshape(()))

    def numpy(self) -> np.ndarray:
        return self.data

    def detach(self) -> "Tensor":
        """返回一个脱离计算图的副本（共享底层数据）。"""
        return Tensor(self.data, requires_grad=False)

    def zero_grad(self) -> None:
        self.grad = None

    def __repr__(self) -> str:  # pragma: no cover - 仅用于调试
        return f"Tensor(shape={self.shape}, requires_grad={self.requires_grad})"

    # ------------------------------------------------------------------
    # 计算图构造
    # ------------------------------------------------------------------
    def _make(
        self,
        data: np.ndarray,
        parents: Sequence["Tensor"],
        backward: Callable[[np.ndarray], None],
    ) -> "Tensor":
        """根据前向结果与反向规则创建输出张量。"""
        tracked = [p for p in parents if p.requires_grad]
        if not tracked or not _GRAD_ENABLED:
            return Tensor(data, requires_grad=False)

        out = Tensor(data, requires_grad=True, _prev=tracked)

        def _bw() -> None:
            assert out.grad is not None
            backward(out.grad)

        out._backward = _bw
        return out

    @staticmethod
    def _accumulate(tensor: "Tensor", grad: np.ndarray) -> None:
        if not tensor.requires_grad:
            return
        grad = _unbroadcast(grad, tensor.shape)
        tensor.grad = grad.copy() if tensor.grad is None else tensor.grad + grad

    # ------------------------------------------------------------------
    # 逐元素运算
    # ------------------------------------------------------------------
    def __add__(self, other: object) -> "Tensor":
        other_t = other if isinstance(other, Tensor) else Tensor(_as_array(other))
        a, b = self, other_t

        def bw(g: np.ndarray) -> None:
            self._accumulate(a, g)
            self._accumulate(b, g)

        return self._make(a.data + b.data, (a, b), bw)

    __radd__ = __add__

    def __neg__(self) -> "Tensor":
        return self._make(-self.data, (self,), lambda g: self._accumulate(self, -g))

    def __sub__(self, other: object) -> "Tensor":
        return self + (-(other if isinstance(other, Tensor) else Tensor(_as_array(other))))

    def __rsub__(self, other: object) -> "Tensor":
        return (-self) + other

    def __mul__(self, other: object) -> "Tensor":
        other_t = other if isinstance(other, Tensor) else Tensor(_as_array(other))
        a, b = self, other_t

        def bw(g: np.ndarray) -> None:
            self._accumulate(a, g * b.data)
            self._accumulate(b, g * a.data)

        return self._make(a.data * b.data, (a, b), bw)

    __rmul__ = __mul__

    def __truediv__(self, other: object) -> "Tensor":
        other_t = other if isinstance(other, Tensor) else Tensor(_as_array(other))
        a, b = self, other_t

        def bw(g: np.ndarray) -> None:
            self._accumulate(a, g / b.data)
            self._accumulate(b, -g * a.data / (b.data**2))

        return self._make(a.data / b.data, (a, b), bw)

    def __rtruediv__(self, other: object) -> "Tensor":
        other_t = other if isinstance(other, Tensor) else Tensor(_as_array(other))
        return other_t / self

    def __pow__(self, power: float) -> "Tensor":
        a = self

        def bw(g: np.ndarray) -> None:
            self._accumulate(a, g * power * a.data ** (power - 1))

        return self._make(a.data**power, (a,), bw)

    def exp(self) -> "Tensor":
        out_data = np.exp(self.data)
        a = self

        def bw(g: np.ndarray) -> None:
            self._accumulate(a, g * out_data)

        return self._make(out_data, (a,), bw)

    def log(self) -> "Tensor":
        a = self

        def bw(g: np.ndarray) -> None:
            self._accumulate(a, g / a.data)

        return self._make(np.log(self.data), (a,), bw)

    def sqrt(self) -> "Tensor":
        return self**0.5

    def rsqrt(self) -> "Tensor":
        return self**-0.5

    def tanh(self) -> "Tensor":
        out_data = np.tanh(self.data)
        a = self

        def bw(g: np.ndarray) -> None:
            self._accumulate(a, g * (1.0 - out_data**2))

        return self._make(out_data, (a,), bw)

    def sigmoid(self) -> "Tensor":
        out_data = 1.0 / (1.0 + np.exp(-self.data))
        a = self

        def bw(g: np.ndarray) -> None:
            self._accumulate(a, g * out_data * (1.0 - out_data))

        return self._make(out_data, (a,), bw)

    def relu(self) -> "Tensor":
        mask = (self.data > 0).astype(np.float64)
        a = self

        def bw(g: np.ndarray) -> None:
            self._accumulate(a, g * mask)

        return self._make(self.data * mask, (a,), bw)

    def silu(self) -> "Tensor":
        """SwiGLU 中使用的 SiLU / Swish 激活：``x * sigmoid(x)``。"""
        sig = 1.0 / (1.0 + np.exp(-self.data))
        a = self

        def bw(g: np.ndarray) -> None:
            self._accumulate(a, g * sig * (1.0 + a.data * (1.0 - sig)))

        return self._make(self.data * sig, (a,), bw)

    # ------------------------------------------------------------------
    # 归约与形变
    # ------------------------------------------------------------------
    def sum(self, axis: int | tuple[int, ...] | None = None, keepdims: bool = False) -> "Tensor":
        a = self

        def bw(g: np.ndarray) -> None:
            grad = g
            if axis is not None and not keepdims:
                grad = np.expand_dims(g, axis)
            self._accumulate(a, np.broadcast_to(grad, a.shape))

        return self._make(self.data.sum(axis=axis, keepdims=keepdims), (a,), bw)

    def mean(self, axis: int | tuple[int, ...] | None = None, keepdims: bool = False) -> "Tensor":
        count = self.data.size if axis is None else np.prod(np.array(self.shape)[list(_axes(axis))])
        return self.sum(axis=axis, keepdims=keepdims) / float(count)

    def reshape(self, *shape: int) -> "Tensor":
        target = shape[0] if len(shape) == 1 and isinstance(shape[0], tuple) else shape
        a = self

        def bw(g: np.ndarray) -> None:
            self._accumulate(a, g.reshape(a.shape))

        return self._make(self.data.reshape(target), (a,), bw)

    def transpose(self, *axes: int) -> "Tensor":
        order = axes if axes else tuple(reversed(range(self.ndim)))
        inverse = np.argsort(order)
        a = self

        def bw(g: np.ndarray) -> None:
            self._accumulate(a, g.transpose(inverse))

        return self._make(self.data.transpose(order), (a,), bw)

    def swapaxes(self, axis1: int, axis2: int) -> "Tensor":
        order = list(range(self.ndim))
        order[axis1], order[axis2] = order[axis2], order[axis1]
        return self.transpose(*order)

    def __getitem__(self, index: object) -> "Tensor":
        """支持整数数组索引，用于 Embedding 查表。"""
        idx = index.data.astype(np.int64) if isinstance(index, Tensor) else index
        a = self

        def bw(g: np.ndarray) -> None:
            if not a.requires_grad:
                return
            grad = np.zeros_like(a.data)
            np.add.at(grad, idx, g)
            self._accumulate(a, grad)

        return self._make(self.data[idx], (a,), bw)

    def masked_fill(self, mask: np.ndarray, value: float) -> "Tensor":
        """``mask`` 为 True 的位置替换为 ``value``（因果注意力掩码用）。"""
        mask = np.asarray(mask, dtype=bool)
        keep = (~mask).astype(np.float64)
        out_data = np.where(mask, value, self.data)
        a = self

        def bw(g: np.ndarray) -> None:
            self._accumulate(a, g * keep)

        return self._make(out_data, (a,), bw)

    def matmul(self, other: "Tensor") -> "Tensor":
        a, b = self, other
        if a.ndim < 2 or b.ndim < 2:
            raise ValueError("matmul 要求两个张量的维度都不小于 2")

        def bw(g: np.ndarray) -> None:
            self._accumulate(a, g @ np.swapaxes(b.data, -1, -2))
            self._accumulate(b, np.swapaxes(a.data, -1, -2) @ g)

        return self._make(a.data @ b.data, (a, b), bw)

    __matmul__ = matmul

    # ------------------------------------------------------------------
    # 概率相关的融合算子
    # ------------------------------------------------------------------
    def softmax(self, axis: int = -1) -> "Tensor":
        shifted = self.data - self.data.max(axis=axis, keepdims=True)
        exp = np.exp(shifted)
        out_data = exp / exp.sum(axis=axis, keepdims=True)
        a = self

        def bw(g: np.ndarray) -> None:
            dot = (g * out_data).sum(axis=axis, keepdims=True)
            self._accumulate(a, out_data * (g - dot))

        return self._make(out_data, (a,), bw)

    def log_softmax(self, axis: int = -1) -> "Tensor":
        shifted = self.data - self.data.max(axis=axis, keepdims=True)
        logsumexp = np.log(np.exp(shifted).sum(axis=axis, keepdims=True))
        out_data = shifted - logsumexp
        probs = np.exp(out_data)
        a = self

        def bw(g: np.ndarray) -> None:
            self._accumulate(a, g - probs * g.sum(axis=axis, keepdims=True))

        return self._make(out_data, (a,), bw)

    # ------------------------------------------------------------------
    # 反向传播
    # ------------------------------------------------------------------
    def backward(self, grad: np.ndarray | None = None) -> None:
        """从当前张量出发做一次反向传播。"""
        if grad is None:
            if self.size != 1:
                raise ValueError("只有标量才能在不提供 grad 的情况下 backward()")
            grad = np.ones_like(self.data)
        self.grad = np.asarray(grad, dtype=np.float64).reshape(self.shape)

        for node in reversed(_topological_order(self)):
            node._backward()


def _axes(axis: int | tuple[int, ...]) -> tuple[int, ...]:
    return (axis,) if isinstance(axis, int) else tuple(axis)


def _topological_order(root: Tensor) -> list[Tensor]:
    """迭代式拓扑排序，避免深层计算图触发递归深度限制。"""
    order: list[Tensor] = []
    visited: set[int] = set()
    stack: list[tuple[Tensor, bool]] = [(root, False)]
    while stack:
        node, expanded = stack.pop()
        if expanded:
            order.append(node)
            continue
        if id(node) in visited:
            continue
        visited.add(id(node))
        stack.append((node, True))
        for parent in node._prev:
            if id(parent) not in visited:
                stack.append((parent, False))
    return order


class Parameter(Tensor):
    """可训练参数。

    与普通 :class:`Tensor` 不同，``Parameter`` 的 ``requires_grad`` 不受
    :class:`no_grad` 影响——在 ``no_grad`` 里构造模型不应让它永久失去
    训练能力。
    """

    __slots__ = ()

    def __init__(self, data: object) -> None:
        super().__init__(data, requires_grad=True)
        self.requires_grad = True


def cat(tensors: Sequence[Tensor], axis: int = -1) -> Tensor:
    """沿 ``axis`` 拼接多个张量（RoPE 的旋转半分实现会用到）。"""
    if not tensors:
        raise ValueError("cat 至少需要一个张量")
    parts = list(tensors)
    out_data = np.concatenate([t.data for t in parts], axis=axis)
    sizes = [t.shape[axis] for t in parts]
    bounds = np.cumsum([0] + sizes)

    def bw(g: np.ndarray) -> None:
        axis_norm = axis % g.ndim
        for index, tensor in enumerate(parts):
            slicer: list[slice] = [slice(None)] * g.ndim
            slicer[axis_norm] = slice(int(bounds[index]), int(bounds[index + 1]))
            Tensor._accumulate(tensor, g[tuple(slicer)])

    return parts[0]._make(out_data, parts, bw)


def cross_entropy(
    logits: Tensor,
    targets: Iterable[int] | np.ndarray,
    ignore_index: int = -100,
) -> Tensor:
    """交叉熵损失，对最后一维做 softmax。

    ``logits`` 形状为 ``(..., vocab)``，``targets`` 形状为 ``(...)``。
    值等于 ``ignore_index`` 的位置不参与损失与梯度（用于 padding 或
    只对回答部分计算损失的指令微调）。
    """
    targets = np.asarray(targets, dtype=np.int64)
    vocab = logits.shape[-1]
    flat_logits = logits.reshape(-1, vocab)
    flat_targets = targets.reshape(-1)
    if flat_logits.shape[0] != flat_targets.shape[0]:
        raise ValueError("logits 与 targets 的样本数不一致")

    valid = flat_targets != ignore_index
    n_valid = int(valid.sum())
    if n_valid == 0:
        raise ValueError("targets 中没有有效位置")

    log_probs = flat_logits.log_softmax(axis=-1)
    rows = np.arange(flat_targets.shape[0])
    safe_targets = np.where(valid, flat_targets, 0)
    picked = log_probs[(rows, safe_targets)]
    mask = Tensor(valid.astype(np.float64))
    return -(picked * mask).sum() / float(n_valid)
