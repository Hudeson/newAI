"""自动微分引擎的有限差分梯度检查。

每个算子都用中心差分独立验证一次——这是整个仓库正确性的地基：
只要这些检查通过，后面所有训练结果才有意义。
"""

from __future__ import annotations

import numpy as np
import pytest

from dive.autograd import Tensor, cat, cross_entropy, is_grad_enabled, no_grad

from .conftest import check_grad

RNG = np.random.default_rng(20240905)


def test_docstring_example():
    x = Tensor([[1.0, 2.0]], requires_grad=True)
    y = (x * x).sum()
    y.backward()
    assert np.allclose(x.grad, [[2.0, 4.0]])


# ----------------------------------------------------------------------
# 逐算子梯度检查
# ----------------------------------------------------------------------
def test_grad_mul_sum():
    check_grad(lambda a, b: (a * b).sum(), [RNG.normal(size=(3, 4)), RNG.normal(size=(3, 4))])


def test_grad_broadcast_add():
    check_grad(
        lambda a, b: ((a + b) * (a + b)).sum(),
        [RNG.normal(size=(3, 4)), RNG.normal(size=(1, 4))],
    )


def test_grad_div_and_pow():
    check_grad(
        lambda a, b: (a / (b * b + 2.0) + a**3).sum(),
        [RNG.normal(size=(2, 3)), RNG.normal(size=(2, 3))],
    )


def test_grad_exp_log_tanh_sigmoid_relu():
    weights = Tensor(RNG.normal(size=(3, 4)))

    def build(x: Tensor) -> Tensor:
        positive = x * x + 0.5
        total = x.exp() + positive.log() + x.tanh() + x.sigmoid() + x.relu()
        return (total * weights).sum()

    check_grad(build, [RNG.normal(size=(3, 4))])


def test_grad_silu():
    weights = Tensor(RNG.normal(size=(4, 5)))
    check_grad(lambda x: (x.silu() * weights).sum(), [RNG.normal(size=(4, 5))])


def test_grad_softmax():
    weights = Tensor(RNG.normal(size=(3, 6)))
    check_grad(lambda x: (x.softmax(axis=-1) * weights).sum(), [RNG.normal(size=(3, 6))])


def test_grad_log_softmax():
    weights = Tensor(RNG.normal(size=(3, 6)))
    check_grad(lambda x: (x.log_softmax(axis=-1) * weights).sum(), [RNG.normal(size=(3, 6))])


def test_grad_rsqrt_rmsnorm_style():
    """RMSNorm 的核心表达式 ``x * rsqrt(mean(x^2) + eps)``。"""
    weights = Tensor(RNG.normal(size=(3, 5)))

    def build(x: Tensor) -> Tensor:
        mean_square = (x * x).mean(axis=-1, keepdims=True)
        return (x * (mean_square + 1e-6).rsqrt() * weights).sum()

    check_grad(build, [RNG.normal(size=(3, 5))])


def test_grad_matmul():
    weights = Tensor(RNG.normal(size=(3, 5)))
    check_grad(
        lambda a, b: ((a @ b) * weights).sum(),
        [RNG.normal(size=(3, 4)), RNG.normal(size=(4, 5))],
    )


def test_grad_batched_matmul():
    weights = Tensor(RNG.normal(size=(2, 3, 3)))
    check_grad(
        lambda a, b: ((a @ b.swapaxes(-1, -2)) * weights).sum(),
        [RNG.normal(size=(2, 3, 4)), RNG.normal(size=(2, 3, 4))],
    )


def test_grad_cat_and_slice():
    """RoPE 用到的「切一半、旋转、再拼回去」模式。"""
    weights = Tensor(RNG.normal(size=(2, 6)))

    def build(x: Tensor) -> Tensor:
        first, second = x[..., :3], x[..., 3:]
        rotated = cat([first * 0.8 - second * 0.6, second * 0.8 + first * 0.6], axis=-1)
        return (rotated * weights).sum()

    check_grad(build, [RNG.normal(size=(2, 6))])


def test_grad_getitem_with_repeated_indices():
    """Embedding 查表：同一行被查多次时梯度必须累加。"""
    index = np.array([[0, 2, 2], [1, 0, 2]])
    weights = Tensor(RNG.normal(size=(2, 3, 4)))
    check_grad(lambda table: (table[index] * weights).sum(), [RNG.normal(size=(3, 4))])


def test_grad_reshape_transpose_masked_fill():
    mask = np.array([[False, True, False, False], [True, False, False, True]])
    weights = Tensor(RNG.normal(size=(4, 2)))

    def build(x: Tensor) -> Tensor:
        # 这里用 -3.0 而不是真实的 -1e9：有限差分在巨大常数上会被浮点抵消吃掉精度
        filled = x.masked_fill(mask, -3.0)
        return (filled.transpose() * weights).sum()

    check_grad(build, [RNG.normal(size=(2, 4))])


def test_grad_cross_entropy():
    targets = np.array([2, 0, 5, 1])
    check_grad(lambda logits: cross_entropy(logits, targets), [RNG.normal(size=(4, 6))])


def test_grad_cross_entropy_with_ignore_index():
    targets = np.array([2, -100, 5, -100])
    check_grad(
        lambda logits: cross_entropy(logits, targets, ignore_index=-100),
        [RNG.normal(size=(4, 6))],
    )


# ----------------------------------------------------------------------
# 语义与边界
# ----------------------------------------------------------------------
def test_cross_entropy_ignores_masked_positions():
    logits = Tensor(RNG.normal(size=(3, 5)), requires_grad=True)
    loss = cross_entropy(logits, np.array([1, -100, 3]), ignore_index=-100)
    loss.backward()
    assert np.allclose(logits.grad[1], 0.0)
    assert not np.allclose(logits.grad[0], 0.0)


def test_cross_entropy_matches_manual_value():
    logits = np.array([[1.0, 2.0, 3.0], [0.5, -1.0, 0.25]])
    targets = np.array([2, 0])
    shifted = logits - logits.max(axis=-1, keepdims=True)
    log_probs = shifted - np.log(np.exp(shifted).sum(axis=-1, keepdims=True))
    expected = -np.mean([log_probs[0, 2], log_probs[1, 0]])
    assert cross_entropy(Tensor(logits), targets).item() == pytest.approx(expected)


def test_cross_entropy_rejects_all_masked():
    with pytest.raises(ValueError):
        cross_entropy(Tensor(RNG.normal(size=(2, 4))), np.array([-100, -100]))


def test_cross_entropy_rejects_shape_mismatch():
    with pytest.raises(ValueError):
        cross_entropy(Tensor(RNG.normal(size=(2, 4))), np.array([1, 2, 3]))


def test_backward_requires_scalar():
    tensor = Tensor(np.ones((2, 2)), requires_grad=True)
    with pytest.raises(ValueError):
        tensor.backward()


def test_no_grad_disables_tracking_and_restores_state():
    x = Tensor(np.ones(3), requires_grad=True)
    assert is_grad_enabled()
    with no_grad():
        assert not is_grad_enabled()
        out = (x * 2.0).sum()
        assert not out.requires_grad
    assert is_grad_enabled()
    assert (x * 2.0).sum().requires_grad


def test_shared_node_accumulates_gradient_once_per_path():
    """菱形计算图：``y = x*x + x`` 的梯度应为 ``2x + 1``。"""
    x = Tensor(np.array([1.0, -2.0, 3.0]), requires_grad=True)
    ((x * x) + x).sum().backward()
    assert np.allclose(x.grad, 2 * np.array([1.0, -2.0, 3.0]) + 1)


def test_cat_requires_at_least_one_tensor():
    with pytest.raises(ValueError):
        cat([])


def test_matmul_requires_2d():
    with pytest.raises(ValueError):
        Tensor(np.ones(3)) @ Tensor(np.ones(3))


def test_deep_graph_does_not_hit_recursion_limit():
    """拓扑排序是迭代实现的，几千层链式计算也不该栈溢出。"""
    x = Tensor(np.array([0.5]), requires_grad=True)
    node = x
    for _ in range(3000):
        node = node * 1.0001
    node.sum().backward()
    assert x.grad is not None
    assert np.isfinite(x.grad).all()
