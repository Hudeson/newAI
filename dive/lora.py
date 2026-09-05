"""LoRA：低秩适配（Low-Rank Adaptation）。

全参数微调要为每个下游任务保存一份完整权重，代价高昂。LoRA 的想法是
冻结原权重 ``W``，只学习一个低秩增量：

.. math:: h = xW + \\frac{\\alpha}{r}\\,(xA)B

其中 ``A`` 形状 ``(in, r)``、``B`` 形状 ``(r, out)``，``r`` 远小于
``in``/``out``。``B`` 初始化为 0，保证训练开始时模型输出与原模型完全一致；
训练完成后可以把 ``AB`` 合并回 ``W``，推理时零额外开销。
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from .autograd import Parameter, Tensor
from .nn import Linear, Module

__all__ = ["LoRALinear", "freeze", "apply_lora", "merge_lora", "lora_state_dict", "trainable_report"]


class LoRALinear(Module):
    """给一个已有的 :class:`~dive.nn.Linear` 挂上低秩旁路。"""

    def __init__(
        self,
        base: Linear,
        rank: int = 4,
        alpha: float | None = None,
        rng: np.random.Generator | None = None,
    ) -> None:
        super().__init__()
        if rank <= 0:
            raise ValueError("rank 必须为正整数")
        rng = rng or np.random.default_rng(0)
        self.base = base
        self.rank = rank
        self.alpha = float(alpha if alpha is not None else rank)
        self.scaling = self.alpha / rank

        freeze(base)
        in_features, out_features = base.weight.shape
        # A 用小随机数、B 用零：训练起点等价于原模型
        self.lora_a = Parameter(rng.normal(0.0, 1.0 / np.sqrt(in_features), size=(in_features, rank)))
        self.lora_b = Parameter(np.zeros((rank, out_features)))

    @property
    def in_features(self) -> int:
        return int(self.base.weight.shape[0])

    @property
    def out_features(self) -> int:
        return int(self.base.weight.shape[1])

    def delta(self) -> np.ndarray:
        """当前低秩增量 ``ΔW``。"""
        return self.scaling * (self.lora_a.data @ self.lora_b.data)

    def forward(self, x: Tensor) -> Tensor:
        return self.base(x) + ((x @ self.lora_a) @ self.lora_b) * self.scaling

    def merge(self) -> Linear:
        """把 ``ΔW`` 写回基座权重，返回可独立使用的 :class:`Linear`。"""
        self.base.weight.data = self.base.weight.data + self.delta()
        self.lora_b.data = np.zeros_like(self.lora_b.data)
        return self.base


def freeze(module: Module) -> Module:
    """冻结模块下的全部参数。"""
    for param in module.parameters():
        param.requires_grad = False
    return module


def apply_lora(
    model: Module,
    rank: int = 4,
    alpha: float | None = None,
    targets: Sequence[str] = ("wq", "wv"),
    freeze_base: bool = True,
    seed: int = 0,
) -> list[str]:
    """把模型中名字命中 ``targets`` 的线性层替换为 LoRA 层。

    默认只适配注意力的 ``wq``/``wv``，这是 LoRA 论文中性价比最高的配置。
    返回被替换的层名列表。
    """
    if freeze_base:
        freeze(model)

    rng = np.random.default_rng(seed)
    replaced: list[str] = []
    for prefix, module in list(model.named_modules()):
        for name, child in list(module._modules.items()):
            if name in targets and isinstance(child, Linear):
                setattr(module, name, LoRALinear(child, rank=rank, alpha=alpha, rng=rng))
                replaced.append(f"{prefix}.{name}" if prefix else name)
    return replaced


def merge_lora(model: Module) -> int:
    """把模型中所有 LoRA 层合并回基座，返回合并的层数。"""
    count = 0
    for _, module in list(model.named_modules()):
        for name, child in list(module._modules.items()):
            if isinstance(child, LoRALinear):
                setattr(module, name, child.merge())
                count += 1
    return count


def lora_state_dict(model: Module) -> dict[str, np.ndarray]:
    """只导出 LoRA 参数——这正是"一个任务只需存几 MB"的来源。"""
    return {
        name: param.data.copy()
        for name, param in model.named_parameters()
        if ".lora_a" in name or ".lora_b" in name or name.startswith(("lora_a", "lora_b"))
    }


def trainable_report(model: Module) -> dict[str, float]:
    """统计可训练参数占比。"""
    total = model.num_parameters()
    trainable = model.num_parameters(trainable_only=True)
    return {
        "total": float(total),
        "trainable": float(trainable),
        "trainable_ratio": trainable / total if total else 0.0,
    }
