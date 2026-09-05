"""TinyLM：形状、配置校验、KV Cache 等价性与端到端参数梯度检查。"""

from __future__ import annotations

import numpy as np
import pytest

from dive.autograd import cross_entropy, no_grad
from dive.nn import Embedding, Linear, RMSNorm
from dive.transformer import TinyLM, TinyLMConfig, rope_tables


def tiny_config(**kwargs: object) -> TinyLMConfig:
    base = dict(vocab_size=11, dim=8, n_layers=2, n_heads=2, max_seq_len=12, seed=3)
    base.update(kwargs)
    return TinyLMConfig(**base)  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# 配置
# ----------------------------------------------------------------------
def test_config_rejects_indivisible_dim():
    with pytest.raises(ValueError):
        TinyLMConfig(vocab_size=8, dim=10, n_heads=4)


def test_config_rejects_odd_head_dim():
    with pytest.raises(ValueError):
        TinyLMConfig(vocab_size=8, dim=6, n_heads=2, n_layers=1)


def test_config_derives_swiglu_hidden_size():
    config = TinyLMConfig(vocab_size=8, dim=64, n_heads=4)
    assert config.head_dim == 16
    # LLaMA 的规则：4*dim 乘 2/3 后向上对齐到 8 的倍数
    assert config.ffn_hidden == 176
    assert config.ffn_hidden % 8 == 0


# ----------------------------------------------------------------------
# 形状
# ----------------------------------------------------------------------
def test_forward_shapes():
    config = tiny_config()
    model = TinyLM(config)
    ids = np.array([[1, 2, 3, 4], [5, 6, 7, 8]])
    logits = model(ids)
    assert logits.shape == (2, 4, config.vocab_size)


def test_next_token_logits_is_one_dimensional():
    model = TinyLM(tiny_config())
    logits = model.next_token_logits([1, 2, 3])
    assert logits.shape == (11,)
    assert np.isfinite(logits).all()


def test_logprobs_for_sequence_length_and_range():
    model = TinyLM(tiny_config())
    ids = [1, 4, 2, 7, 3]
    log_probs = model.logprobs_for_sequence(ids)
    assert log_probs.shape == (len(ids) - 1,)
    assert (log_probs <= 0).all()


def test_tied_embeddings_share_weights():
    tied = TinyLM(tiny_config(tie_embeddings=True))
    untied = TinyLM(tiny_config(tie_embeddings=False))
    assert tied.lm_head is None
    assert untied.lm_head is not None
    assert untied.num_parameters() > tied.num_parameters()


def test_max_seq_len_guard():
    model = TinyLM(tiny_config(max_seq_len=6))
    model(np.arange(6).reshape(1, 6))  # 刚好等于上限，允许
    with pytest.raises(ValueError):
        model(np.arange(7).reshape(1, 7))


def test_max_seq_len_guard_accounts_for_offset():
    model = TinyLM(tiny_config(max_seq_len=6))
    with pytest.raises(ValueError):
        model(np.array([[1]]), caches=model.empty_caches(), offset=6)


# ----------------------------------------------------------------------
# RoPE
# ----------------------------------------------------------------------
def test_rope_tables_shapes_and_first_position():
    cos, sin = rope_tables(seq_len=5, head_dim=8)
    assert cos.shape == (5, 4) and sin.shape == (5, 4)
    # 位置 0 的旋转角为 0：cos=1、sin=0
    assert np.allclose(cos[0], 1.0)
    assert np.allclose(sin[0], 0.0)
    assert np.allclose(cos**2 + sin**2, 1.0)


def test_rope_makes_attention_position_aware():
    """同一个 token 出现在不同位置时，模型输出应当不同。"""
    model = TinyLM(tiny_config())
    first = model.next_token_logits([5])
    later = model.next_token_logits([1, 2, 5])
    assert not np.allclose(first, later)


# ----------------------------------------------------------------------
# 因果性与 KV Cache
# ----------------------------------------------------------------------
def test_causal_mask_blocks_future_tokens():
    """改动第 t 个 token 不能影响第 t-1 个位置的输出。"""
    model = TinyLM(tiny_config())
    with no_grad():
        original = model(np.array([[1, 2, 3, 4]])).data
        modified = model(np.array([[1, 2, 3, 9]])).data
    assert np.allclose(original[0, :3], modified[0, :3])
    assert not np.allclose(original[0, 3], modified[0, 3])


def test_kv_cache_matches_full_forward():
    model = TinyLM(tiny_config())
    ids = [1, 4, 2, 7, 3, 5]

    with no_grad():
        full = model(np.array([ids])).data[0]

    caches = model.empty_caches()
    with no_grad():
        out = model(np.array([ids[:2]]), caches=caches, offset=0)
        incremental = [out.data[0, -1]]
        for position, token in enumerate(ids[2:], start=2):
            out = model(np.array([[token]]), caches=caches, offset=position)
            incremental.append(out.data[0, -1])

    assert np.allclose(full[1], incremental[0], atol=1e-12)
    assert np.allclose(full[-1], incremental[-1], atol=1e-12)
    error = float(np.max(np.abs(full[-1] - incremental[-1])))
    assert error < 1e-12, f"KV Cache 与完整前向偏差 {error:.3e}"


def test_cache_grows_by_one_per_step():
    config = tiny_config()
    model = TinyLM(config)
    caches = model.empty_caches()
    assert len(caches) == config.n_layers
    with no_grad():
        model(np.array([[1, 2, 3]]), caches=caches, offset=0)
        assert caches[0]["k"].shape == (1, config.n_heads, 3, config.head_dim)
        model(np.array([[4]]), caches=caches, offset=3)
        assert caches[0]["k"].shape == (1, config.n_heads, 4, config.head_dim)


# ----------------------------------------------------------------------
# 端到端梯度检查
# ----------------------------------------------------------------------
def test_end_to_end_parameter_gradcheck():
    """对每个参数抽查若干分量，与有限差分比对。

    抽查而非全量检查是为了让测试保持秒级；被抽到的分量覆盖了
    Embedding、注意力四个投影、SwiGLU 三个投影与两处 RMSNorm。
    """
    model = TinyLM(tiny_config(dim=8, n_layers=1, n_heads=2))
    ids = np.array([[1, 3, 5, 2]])
    targets = np.array([[3, 5, 2, 4]])
    eps = 1e-6
    rng = np.random.default_rng(0)

    model.zero_grad()
    loss = cross_entropy(model(ids), targets)
    loss.backward()
    analytic = {name: param.grad.copy() for name, param in model.named_parameters()}

    def loss_value() -> float:
        with no_grad():
            return cross_entropy(model(ids), targets).item()

    checked = 0
    for name, param in model.named_parameters():
        flat = param.data.reshape(-1)
        picks = rng.choice(flat.size, size=min(3, flat.size), replace=False)
        for index in picks:
            original = flat[index]
            flat[index] = original + eps
            plus = loss_value()
            flat[index] = original - eps
            minus = loss_value()
            flat[index] = original
            approx = (plus - minus) / (2 * eps)
            exact = analytic[name].reshape(-1)[index]
            assert abs(exact - approx) < 1e-6, f"{name}[{index}] 解析 {exact} vs 数值 {approx}"
            checked += 1

    assert checked >= 20


# ----------------------------------------------------------------------
# 基础层
# ----------------------------------------------------------------------
def test_linear_shapes_and_bias():
    layer = Linear(4, 3, rng=np.random.default_rng(0))
    assert layer.weight.shape == (4, 3)
    assert layer.bias is not None and np.allclose(layer.bias.data, 0.0)
    assert Linear(4, 3, bias=False).bias is None


def test_rmsnorm_normalizes_to_unit_rms():
    layer = RMSNorm(6)
    from dive.autograd import Tensor

    out = layer(Tensor(np.random.default_rng(0).normal(size=(4, 6)) * 7.0))
    rms = np.sqrt((out.data**2).mean(axis=-1))
    assert np.allclose(rms, 1.0, atol=1e-4)


def test_embedding_lookup_matches_table():
    table = Embedding(5, 3, rng=np.random.default_rng(0))
    ids = np.array([[0, 4], [2, 2]])
    assert np.allclose(table(ids).data, table.weight.data[ids])


def test_state_dict_roundtrip():
    model = TinyLM(tiny_config())
    other = TinyLM(tiny_config(seed=99))
    assert not np.allclose(model.next_token_logits([1, 2]), other.next_token_logits([1, 2]))
    other.load_state_dict(model.state_dict())
    assert np.allclose(model.next_token_logits([1, 2]), other.next_token_logits([1, 2]))


def test_load_state_dict_rejects_unknown_key():
    model = TinyLM(tiny_config())
    with pytest.raises(KeyError):
        model.load_state_dict({"不存在的参数": np.zeros(3)})
