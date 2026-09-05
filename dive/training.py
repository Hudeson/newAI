"""训练循环：因果语言建模预训练与指令微调（SFT）。

指令微调与预训练的唯一区别，是"哪些位置参与损失"：预训练对每个
token 都算损失，而 SFT 只对**回答**部分算损失，提示词部分用
``IGNORE_INDEX`` 掩掉。本模块把这件事显式地做出来。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np

from .autograd import Tensor, cross_entropy, no_grad
from .nn import AdamW, Module, clip_grad_norm

__all__ = [
    "IGNORE_INDEX",
    "TrainConfig",
    "pad_sequences",
    "causal_batch",
    "sft_batch",
    "train_causal_lm",
    "evaluate_loss",
    "perplexity",
]

IGNORE_INDEX = -100


@dataclass
class TrainConfig:
    """训练超参数。"""

    epochs: int = 20
    batch_size: int = 8
    lr: float = 3e-3
    weight_decay: float = 0.0
    grad_clip: float = 1.0
    seed: int = 0
    log_every: int = 5
    verbose: bool = True
    history: list[dict[str, float]] = field(default_factory=list)


def pad_sequences(sequences: Sequence[Sequence[int]], pad_id: int) -> np.ndarray:
    """右侧补齐成 ``(batch, max_len)`` 矩阵。"""
    max_len = max(len(seq) for seq in sequences)
    out = np.full((len(sequences), max_len), pad_id, dtype=np.int64)
    for row, seq in enumerate(sequences):
        out[row, : len(seq)] = np.asarray(seq, dtype=np.int64)
    return out


def causal_batch(
    sequences: Sequence[Sequence[int]], pad_id: int
) -> tuple[np.ndarray, np.ndarray]:
    """构造预训练 batch：输入右移一位预测下一个 token。"""
    padded = pad_sequences(sequences, pad_id)
    inputs = padded[:, :-1]
    targets = padded[:, 1:].copy()
    lengths = np.array([len(seq) for seq in sequences])
    positions = np.arange(targets.shape[1])[None, :]
    targets[positions >= (lengths[:, None] - 1)] = IGNORE_INDEX
    return inputs, targets


def sft_batch(
    sequences: Sequence[Sequence[int]],
    prompt_lengths: Sequence[int],
    pad_id: int,
) -> tuple[np.ndarray, np.ndarray]:
    """构造 SFT batch：只对回答部分计算损失。

    ``prompt_lengths[i]`` 是第 i 条样本中提示词占用的 token 数。
    """
    inputs, targets = causal_batch(sequences, pad_id)
    positions = np.arange(targets.shape[1])[None, :]
    prompt_len = np.asarray(prompt_lengths)[:, None]
    # targets[t] 对应原序列的第 t+1 个 token，提示词内部的预测不计损失
    targets = np.where(positions < prompt_len - 1, IGNORE_INDEX, targets)
    return inputs, targets


def train_causal_lm(
    model: Module,
    batches: Sequence[tuple[np.ndarray, np.ndarray]],
    config: TrainConfig | None = None,
    optimizer: AdamW | None = None,
    on_epoch_end: Callable[[int, float], None] | None = None,
) -> list[dict[str, float]]:
    """在给定 batch 上训练模型，返回每个 epoch 的损失历史。"""
    config = config or TrainConfig()
    params = model.trainable_parameters()
    optimizer = optimizer or AdamW(params, lr=config.lr, weight_decay=config.weight_decay)
    rng = np.random.default_rng(config.seed)
    history: list[dict[str, float]] = []

    for epoch in range(1, config.epochs + 1):
        order = rng.permutation(len(batches))
        total = 0.0
        for index in order:
            inputs, targets = batches[index]
            optimizer.zero_grad()
            logits = model(inputs)
            loss = cross_entropy(logits, targets, ignore_index=IGNORE_INDEX)
            loss.backward()
            if config.grad_clip:
                clip_grad_norm(params, config.grad_clip)
            optimizer.step()
            total += loss.item()

        mean_loss = total / len(batches)
        record = {"epoch": float(epoch), "loss": mean_loss, "ppl": float(np.exp(min(mean_loss, 20)))}
        history.append(record)
        if config.verbose and (epoch % config.log_every == 0 or epoch == 1):
            print(f"  epoch {epoch:3d} | loss {mean_loss:.4f} | ppl {record['ppl']:8.2f}")
        if on_epoch_end is not None:
            on_epoch_end(epoch, mean_loss)

    config.history = history
    return history


def evaluate_loss(model: Module, batches: Sequence[tuple[np.ndarray, np.ndarray]]) -> float:
    """在不构建计算图的情况下评估平均损失。"""
    total = 0.0
    for inputs, targets in batches:
        with no_grad():
            logits = model(inputs)
        log_probs = logits.log_softmax(axis=-1).data
        flat_logp = log_probs.reshape(-1, log_probs.shape[-1])
        flat_targets = np.asarray(targets).reshape(-1)
        valid = flat_targets != IGNORE_INDEX
        picked = flat_logp[np.arange(flat_targets.size)[valid], flat_targets[valid]]
        total += float(-picked.mean())
    return total / len(batches)


def perplexity(model: Module, batches: Sequence[tuple[np.ndarray, np.ndarray]]) -> float:
    """困惑度 = exp(平均交叉熵)，衡量模型对数据的"意外程度"。"""
    return float(np.exp(evaluate_loss(model, batches)))


def as_tensor(array: np.ndarray) -> Tensor:
    return Tensor(array)
