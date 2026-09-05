"""神经网络层与优化器（构建在 :mod:`dive.autograd` 之上）。

提供大模型所需的最小算子集合：

* :class:`Linear` / :class:`Embedding`：线性投影与词表查找；
* :class:`RMSNorm`：LLaMA 系列使用的归一化层（比 LayerNorm 少一个均值项）；
* :class:`SGD` / :class:`AdamW`：优化器，配合 :func:`clip_grad_norm` 做梯度裁剪。
"""

from __future__ import annotations

from typing import Iterator

import numpy as np

from .autograd import Parameter, Tensor

__all__ = [
    "Module",
    "ModuleList",
    "Linear",
    "Embedding",
    "RMSNorm",
    "Optimizer",
    "SGD",
    "AdamW",
    "clip_grad_norm",
]


class Module:
    """所有网络层的基类，负责参数与子模块的注册和遍历。"""

    def __init__(self) -> None:
        object.__setattr__(self, "_parameters", {})
        object.__setattr__(self, "_modules", {})

    def __setattr__(self, name: str, value: object) -> None:
        if isinstance(value, Parameter):
            self._parameters[name] = value
        elif isinstance(value, Module):
            self._modules[name] = value
        object.__setattr__(self, name, value)

    def named_parameters(self, prefix: str = "") -> Iterator[tuple[str, Parameter]]:
        for name, param in self._parameters.items():
            yield f"{prefix}{name}", param
        for name, module in self._modules.items():
            yield from module.named_parameters(f"{prefix}{name}.")

    def parameters(self) -> list[Parameter]:
        return [param for _, param in self.named_parameters()]

    def trainable_parameters(self) -> list[Parameter]:
        return [param for param in self.parameters() if param.requires_grad]

    def named_modules(self, prefix: str = "") -> Iterator[tuple[str, "Module"]]:
        yield prefix.rstrip("."), self
        for name, module in self._modules.items():
            yield from module.named_modules(f"{prefix}{name}.")

    def zero_grad(self) -> None:
        for param in self.parameters():
            param.zero_grad()

    def num_parameters(self, trainable_only: bool = False) -> int:
        params = self.trainable_parameters() if trainable_only else self.parameters()
        return int(sum(param.size for param in params))

    def state_dict(self) -> dict[str, np.ndarray]:
        return {name: param.data.copy() for name, param in self.named_parameters()}

    def load_state_dict(self, state: dict[str, np.ndarray]) -> None:
        params = dict(self.named_parameters())
        for name, value in state.items():
            if name not in params:
                raise KeyError(f"未知参数：{name}")
            if params[name].shape != value.shape:
                raise ValueError(f"参数 {name} 形状不匹配")
            params[name].data = np.asarray(value, dtype=np.float64).copy()

    def __call__(self, *args: object, **kwargs: object) -> Tensor:
        return self.forward(*args, **kwargs)

    def forward(self, *args: object, **kwargs: object) -> Tensor:  # pragma: no cover
        raise NotImplementedError


class ModuleList(Module):
    """按顺序存放子模块，行为类似 ``list``。"""

    def __init__(self, modules: list[Module] | None = None) -> None:
        super().__init__()
        self._items: list[Module] = []
        for module in modules or []:
            self.append(module)

    def append(self, module: Module) -> None:
        self._modules[str(len(self._items))] = module
        self._items.append(module)

    def __iter__(self) -> Iterator[Module]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, index: int) -> Module:
        return self._items[index]


class Linear(Module):
    """全连接层 ``y = x W + b``。

    权重按 ``(in_features, out_features)`` 存放，因此前向就是一次
    ``x @ W``，无需转置——这让后面的 LoRA 旁路更直观。
    """

    def __init__(
        self,
        in_features: int,
        out_features: int,
        bias: bool = True,
        rng: np.random.Generator | None = None,
    ) -> None:
        super().__init__()
        rng = rng or np.random.default_rng(0)
        scale = 1.0 / np.sqrt(in_features)
        self.in_features = in_features
        self.out_features = out_features
        self.weight = Parameter(rng.normal(0.0, scale, size=(in_features, out_features)))
        self.bias = Parameter(np.zeros(out_features)) if bias else None

    def forward(self, x: Tensor) -> Tensor:
        out = x @ self.weight
        if self.bias is not None:
            out = out + self.bias
        return out


class Embedding(Module):
    """词嵌入表。"""

    def __init__(self, num_embeddings: int, dim: int, rng: np.random.Generator | None = None) -> None:
        super().__init__()
        rng = rng or np.random.default_rng(0)
        self.num_embeddings = num_embeddings
        self.dim = dim
        self.weight = Parameter(rng.normal(0.0, 0.02, size=(num_embeddings, dim)))

    def forward(self, ids: np.ndarray) -> Tensor:
        return self.weight[np.asarray(ids, dtype=np.int64)]


class RMSNorm(Module):
    """Root Mean Square 归一化：``x / rms(x) * g``。"""

    def __init__(self, dim: int, eps: float = 1e-6) -> None:
        super().__init__()
        self.eps = eps
        self.weight = Parameter(np.ones(dim))

    def forward(self, x: Tensor) -> Tensor:
        mean_square = (x * x).mean(axis=-1, keepdims=True)
        return x * (mean_square + self.eps).rsqrt() * self.weight


# ----------------------------------------------------------------------
# 优化器
# ----------------------------------------------------------------------
class Optimizer:
    """优化器基类。"""

    def __init__(self, params: list[Parameter], lr: float) -> None:
        self.params = [p for p in params if p.requires_grad]
        self.lr = lr

    def zero_grad(self) -> None:
        for param in self.params:
            param.zero_grad()

    def step(self) -> None:  # pragma: no cover
        raise NotImplementedError


class SGD(Optimizer):
    """带动量的随机梯度下降。"""

    def __init__(self, params: list[Parameter], lr: float = 0.1, momentum: float = 0.0) -> None:
        super().__init__(params, lr)
        self.momentum = momentum
        self._velocity = [np.zeros_like(p.data) for p in self.params]

    def step(self) -> None:
        for index, param in enumerate(self.params):
            if param.grad is None:
                continue
            self._velocity[index] = self.momentum * self._velocity[index] + param.grad
            param.data -= self.lr * self._velocity[index]


class AdamW(Optimizer):
    """AdamW：Adam + 解耦权重衰减，是训练大模型的默认选择。"""

    def __init__(
        self,
        params: list[Parameter],
        lr: float = 1e-3,
        betas: tuple[float, float] = (0.9, 0.999),
        eps: float = 1e-8,
        weight_decay: float = 0.0,
    ) -> None:
        super().__init__(params, lr)
        self.beta1, self.beta2 = betas
        self.eps = eps
        self.weight_decay = weight_decay
        self._m = [np.zeros_like(p.data) for p in self.params]
        self._v = [np.zeros_like(p.data) for p in self.params]
        self._t = 0

    def step(self) -> None:
        self._t += 1
        for index, param in enumerate(self.params):
            if param.grad is None:
                continue
            grad = param.grad
            self._m[index] = self.beta1 * self._m[index] + (1 - self.beta1) * grad
            self._v[index] = self.beta2 * self._v[index] + (1 - self.beta2) * grad**2
            m_hat = self._m[index] / (1 - self.beta1**self._t)
            v_hat = self._v[index] / (1 - self.beta2**self._t)
            if self.weight_decay:
                param.data -= self.lr * self.weight_decay * param.data
            param.data -= self.lr * m_hat / (np.sqrt(v_hat) + self.eps)


def clip_grad_norm(params: list[Parameter], max_norm: float) -> float:
    """全局梯度裁剪，返回裁剪前的梯度范数。"""
    total = 0.0
    for param in params:
        if param.grad is not None:
            total += float((param.grad**2).sum())
    norm = float(np.sqrt(total))
    if norm > max_norm and norm > 0:
        scale = max_norm / norm
        for param in params:
            if param.grad is not None:
                param.grad = param.grad * scale
    return norm
