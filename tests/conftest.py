"""测试共用的工具：有限差分梯度检查与确定性玩具模型。"""

from __future__ import annotations

from typing import Callable, Sequence

import numpy as np
import pytest

from dive.autograd import Tensor


def numeric_grad(
    value_fn: Callable[[list[np.ndarray]], float],
    arrays: list[np.ndarray],
    eps: float = 1e-6,
    indices: Sequence[Sequence[tuple[int, ...]]] | None = None,
) -> list[np.ndarray]:
    """用中心差分估计 ``value_fn`` 对每个输入数组的梯度。"""
    grads = [np.zeros_like(array) for array in arrays]
    for slot, array in enumerate(arrays):
        positions = (
            list(np.ndindex(array.shape)) if indices is None else list(indices[slot])
        )
        for index in positions:
            original = array[index]
            array[index] = original + eps
            plus = value_fn(arrays)
            array[index] = original - eps
            minus = value_fn(arrays)
            array[index] = original
            grads[slot][index] = (plus - minus) / (2 * eps)
    return grads


def check_grad(
    build: Callable[..., Tensor],
    inputs: Sequence[np.ndarray],
    tol: float = 1e-6,
    eps: float = 1e-6,
) -> None:
    """比较自动微分梯度与有限差分梯度。

    ``build(*tensors)`` 必须返回一个标量 :class:`~dive.autograd.Tensor`。
    """
    arrays = [np.array(item, dtype=np.float64) for item in inputs]

    tensors = [Tensor(array.copy(), requires_grad=True) for array in arrays]
    output = build(*tensors)
    assert output.size == 1, "check_grad 只支持标量输出"
    output.backward()
    analytic = [tensor.grad for tensor in tensors]

    def value(current: list[np.ndarray]) -> float:
        plain = [Tensor(array.copy()) for array in current]
        return float(build(*plain).data.reshape(()))

    numeric = numeric_grad(value, arrays, eps=eps)

    for slot, (auto, approx) in enumerate(zip(analytic, numeric)):
        assert auto is not None, f"第 {slot} 个输入没有拿到梯度"
        error = float(np.max(np.abs(auto - approx)))
        assert error < tol, f"第 {slot} 个输入梯度误差 {error:.3e} 超过阈值 {tol:.3e}"


class ToyLM:
    """确定性玩具语言模型：下一个 token 的 logits 只取决于最后一个 token。

    它满足 :class:`dive.decoding.SupportsLogits` 协议，因此可以直接喂给
    ``generate`` / ``beam_search`` / ``HuffmanStego``，而且没有任何训练开销。
    """

    def __init__(self, vocab_size: int = 12, seed: int = 0, scale: float = 1.5) -> None:
        self.vocab_size = vocab_size
        rng = np.random.default_rng(seed)
        self.table = scale * rng.normal(size=(vocab_size, vocab_size))

    def next_token_logits(self, ids: Sequence[int]) -> np.ndarray:
        last = int(ids[-1]) % self.vocab_size if len(ids) else 0
        return self.table[last].copy()

    def logprobs_for_sequence(self, ids: Sequence[int]) -> np.ndarray:
        ids = [int(token) for token in ids]
        out = []
        for position in range(1, len(ids)):
            logits = self.next_token_logits(ids[:position])
            shifted = logits - logits.max()
            log_probs = shifted - np.log(np.exp(shifted).sum())
            out.append(log_probs[ids[position]])
        return np.array(out)


class UniformLM:
    """所有 token 概率相同的模型：熵最大，最适合观察水印与隐写的上限。"""

    def __init__(self, vocab_size: int = 40) -> None:
        self.vocab_size = vocab_size

    def next_token_logits(self, ids: Sequence[int]) -> np.ndarray:
        return np.zeros(self.vocab_size)


@pytest.fixture
def toy_lm() -> ToyLM:
    return ToyLM()


@pytest.fixture
def uniform_lm() -> UniformLM:
    return UniformLM()
