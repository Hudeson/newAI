"""LoRA：冻结基座、可训练占比、零初始化等价性与精确合并。"""

from __future__ import annotations

import numpy as np
import pytest

from dive.autograd import Tensor, no_grad
from dive.lora import (
    LoRALinear,
    apply_lora,
    freeze,
    lora_state_dict,
    merge_lora,
    trainable_report,
)
from dive.nn import Linear
from dive.transformer import TinyLM, TinyLMConfig


def build_model() -> TinyLM:
    return TinyLM(
        TinyLMConfig(vocab_size=13, dim=16, n_layers=2, n_heads=2, max_seq_len=24, seed=1)
    )


def randomize_adapters(model: TinyLM, seed: int = 0) -> None:
    """把 ``lora_b`` 填成非零，模拟「已经训练过」的适配器。"""
    rng = np.random.default_rng(seed)
    for name, param in model.named_parameters():
        if name.endswith("lora_b"):
            param.data = rng.normal(0.0, 0.1, size=param.shape)


# ----------------------------------------------------------------------
# LoRALinear
# ----------------------------------------------------------------------
def test_lora_linear_starts_as_identity():
    base = Linear(6, 4, bias=False, rng=np.random.default_rng(0))
    x = Tensor(np.random.default_rng(1).normal(size=(3, 6)))
    expected = base(x).data.copy()
    wrapped = LoRALinear(base, rank=2)
    assert np.allclose(wrapped(x).data, expected)
    assert np.allclose(wrapped.delta(), 0.0)


def test_lora_linear_scaling_uses_alpha_over_rank():
    base = Linear(6, 4, bias=False)
    assert LoRALinear(base, rank=4).scaling == 1.0
    assert LoRALinear(Linear(6, 4, bias=False), rank=4, alpha=8).scaling == 2.0


def test_lora_linear_rejects_non_positive_rank():
    with pytest.raises(ValueError):
        LoRALinear(Linear(4, 4), rank=0)


def test_lora_linear_freezes_base_but_trains_adapters():
    base = Linear(6, 4, bias=False)
    wrapped = LoRALinear(base, rank=2)
    assert not base.weight.requires_grad
    assert wrapped.lora_a.requires_grad and wrapped.lora_b.requires_grad
    assert wrapped.in_features == 6 and wrapped.out_features == 4


def test_freeze_disables_all_gradients():
    model = build_model()
    freeze(model)
    assert model.trainable_parameters() == []


# ----------------------------------------------------------------------
# apply_lora
# ----------------------------------------------------------------------
def test_apply_lora_replaces_target_layers():
    model = build_model()
    replaced = apply_lora(model, rank=4, targets=("wq", "wv"))
    assert len(replaced) == 2 * model.config.n_layers
    assert all(name.endswith(("wq", "wv")) for name in replaced)
    assert all(isinstance(model.layers[i].attn.wq, LoRALinear) for i in range(model.config.n_layers))
    assert not isinstance(model.layers[0].attn.wk, LoRALinear)


def test_apply_lora_keeps_output_unchanged():
    model = build_model()
    ids = np.array([[1, 2, 3, 4]])
    with no_grad():
        before = model(ids).data.copy()
    apply_lora(model, rank=4)
    with no_grad():
        after = model(ids).data
    assert np.allclose(before, after, atol=1e-14)


def test_apply_lora_trainable_ratio_is_small():
    model = build_model()
    apply_lora(model, rank=4)
    report = trainable_report(model)
    assert 0.0 < report["trainable_ratio"] < 0.15
    assert report["trainable"] < report["total"]
    # 只有适配器参与训练
    assert all(
        name.endswith(("lora_a", "lora_b"))
        for name, param in model.named_parameters()
        if param.requires_grad
    )


def test_apply_lora_without_freezing_only_locks_wrapped_layers():
    """``freeze_base=False`` 时其余层仍可训练，但被包裹的基座权重一定被冻结。"""
    model = build_model()
    apply_lora(model, rank=2, freeze_base=False)
    assert trainable_report(model)["trainable_ratio"] > 0.8
    assert model.layers[0].attn.wk.weight.requires_grad
    assert not model.layers[0].attn.wq.base.weight.requires_grad


# ----------------------------------------------------------------------
# 合并与导出
# ----------------------------------------------------------------------
def test_merge_lora_is_numerically_exact():
    model = build_model()
    replaced = apply_lora(model, rank=4)
    randomize_adapters(model)

    ids = np.array([[1, 2, 3, 4, 5]])
    with no_grad():
        before = model(ids).data.copy()
    assert merge_lora(model) == len(replaced)
    with no_grad():
        after = model(ids).data

    error = float(np.max(np.abs(before - after)))
    assert error < 1e-12, f"合并前后输出偏差 {error:.3e}"
    assert all(not isinstance(model.layers[i].attn.wq, LoRALinear) for i in range(2))


def test_merge_lora_writes_delta_into_base_weight():
    base = Linear(6, 4, bias=False, rng=np.random.default_rng(0))
    original = base.weight.data.copy()
    wrapped = LoRALinear(base, rank=2)
    wrapped.lora_b.data = np.random.default_rng(2).normal(size=wrapped.lora_b.shape)
    delta = wrapped.delta().copy()
    merged = wrapped.merge()
    assert np.allclose(merged.weight.data, original + delta)
    # 合并后适配器归零，重复合并不会再次改动权重
    assert np.allclose(wrapped.delta(), 0.0)


def test_lora_state_dict_contains_only_adapters():
    model = build_model()
    replaced = apply_lora(model, rank=4)
    state = lora_state_dict(model)
    assert len(state) == 2 * len(replaced)
    assert all(name.endswith(("lora_a", "lora_b")) for name in state)
    assert all("weight" not in name for name in state)


def test_lora_state_dict_is_much_smaller_than_full_checkpoint():
    model = build_model()
    apply_lora(model, rank=4)
    adapter_size = sum(array.size for array in lora_state_dict(model).values())
    full_size = sum(array.size for array in model.state_dict().values())
    assert adapter_size < full_size * 0.15


def test_lora_gradients_flow_only_to_adapters():
    from dive.autograd import cross_entropy

    model = build_model()
    apply_lora(model, rank=4)
    ids = np.array([[1, 2, 3, 4]])
    cross_entropy(model(ids), np.array([[2, 3, 4, 5]])).backward()

    for name, param in model.named_parameters():
        if name.endswith(("lora_a", "lora_b")):
            assert param.grad is not None, name
        else:
            assert param.grad is None, name
