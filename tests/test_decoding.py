"""解码策略：贪心、温度、Top-k、Top-p、重复惩罚与集束搜索。"""

from __future__ import annotations

import numpy as np
import pytest

from dive.autograd import no_grad
from dive.decoding import (
    NEG_INF,
    SamplingConfig,
    apply_repetition_penalty,
    beam_search,
    generate,
    prepare_distribution,
    softmax,
    top_k_filter,
    top_p_filter,
)
from dive.transformer import TinyLM, TinyLMConfig

from .conftest import ToyLM


# ----------------------------------------------------------------------
# 基础工具
# ----------------------------------------------------------------------
def test_softmax_is_normalized_and_stable():
    probs = softmax(np.array([1000.0, 1001.0, 999.0]))
    assert probs.sum() == pytest.approx(1.0)
    assert np.isfinite(probs).all()
    assert np.argmax(probs) == 1


def test_sampling_config_greedy_flag():
    assert SamplingConfig(temperature=0.0).greedy
    assert SamplingConfig(temperature=-1.0).greedy
    assert not SamplingConfig(temperature=0.7).greedy


def test_top_k_filter_keeps_exactly_k_candidates():
    logits = np.array([0.1, 3.0, 2.0, -1.0, 0.5])
    filtered = top_k_filter(logits, 2)
    assert (filtered > NEG_INF / 2).sum() == 2
    assert filtered[1] == 3.0 and filtered[2] == 2.0
    assert filtered[0] == NEG_INF


def test_top_k_filter_is_noop_for_degenerate_k():
    logits = np.array([0.1, 3.0, 2.0])
    assert np.allclose(top_k_filter(logits, 0), logits)
    assert np.allclose(top_k_filter(logits, 5), logits)


def test_top_p_filter_keeps_minimal_nucleus():
    # 概率约为 [0.6439, 0.2369, 0.0871, 0.0321]
    logits = np.log(np.array([0.64, 0.24, 0.09, 0.03]))
    kept = top_p_filter(logits, 0.85) > NEG_INF / 2
    assert kept.tolist() == [True, True, False, False]


def test_top_p_filter_always_keeps_at_least_one():
    logits = np.log(np.array([0.97, 0.02, 0.01]))
    kept = top_p_filter(logits, 0.5) > NEG_INF / 2
    assert kept.sum() == 1 and kept[0]


def test_top_p_filter_is_noop_outside_open_interval():
    logits = np.array([1.0, 2.0, 3.0])
    assert np.allclose(top_p_filter(logits, 0.0), logits)
    assert np.allclose(top_p_filter(logits, 1.0), logits)


def test_repetition_penalty_pushes_seen_tokens_down():
    logits = np.array([2.0, -2.0, 0.5])
    penalized = apply_repetition_penalty(logits, [0, 1], penalty=2.0)
    assert penalized[0] == 1.0  # 正 logit 被除
    assert penalized[1] == -4.0  # 负 logit 被乘，更不可能
    assert penalized[2] == 0.5  # 没出现过的 token 不动


def test_repetition_penalty_is_noop_when_disabled():
    logits = np.array([2.0, -2.0])
    assert np.allclose(apply_repetition_penalty(logits, [0], 1.0), logits)
    assert np.allclose(apply_repetition_penalty(logits, [], 2.0), logits)


def test_prepare_distribution_temperature_sharpens_and_flattens():
    logits = np.array([1.0, 2.0, 3.0])
    cold = prepare_distribution(logits, config=SamplingConfig(temperature=0.2))
    hot = prepare_distribution(logits, config=SamplingConfig(temperature=5.0))
    assert cold.sum() == pytest.approx(1.0) and hot.sum() == pytest.approx(1.0)
    assert cold.max() > hot.max()
    assert np.argmax(cold) == np.argmax(hot) == 2


def test_prepare_distribution_top_k_one_is_argmax():
    probs = prepare_distribution(np.array([1.0, 5.0, 2.0]), config=SamplingConfig(top_k=1))
    assert np.argmax(probs) == 1
    assert probs[1] == pytest.approx(1.0)


# ----------------------------------------------------------------------
# generate
# ----------------------------------------------------------------------
def test_greedy_generate_is_deterministic(toy_lm: ToyLM):
    config = SamplingConfig(temperature=0.0)
    first = generate(toy_lm, [1, 2], max_new_tokens=8, config=config)
    second = generate(toy_lm, [1, 2], max_new_tokens=8, config=config)
    assert first == second
    assert len(first) == 8


def test_greedy_generate_matches_manual_argmax(toy_lm: ToyLM):
    out = generate(toy_lm, [3], max_new_tokens=3, config=SamplingConfig(temperature=0.0))
    ids = [3]
    expected = []
    for _ in range(3):
        expected.append(int(np.argmax(toy_lm.next_token_logits(ids))))
        ids.append(expected[-1])
    assert out == expected


def test_sampling_is_reproducible_with_seed(toy_lm: ToyLM):
    config = SamplingConfig(temperature=1.0, seed=7)
    assert generate(toy_lm, [1], max_new_tokens=10, config=config) == generate(
        toy_lm, [1], max_new_tokens=10, config=config
    )


def test_stop_ids_terminate_generation(toy_lm: ToyLM):
    target = int(np.argmax(toy_lm.next_token_logits([1])))
    out = generate(
        toy_lm, [1], max_new_tokens=8, config=SamplingConfig(temperature=0.0), stop_ids=[target]
    )
    assert out == [target]


def test_processors_can_ban_tokens(toy_lm: ToyLM):
    banned = int(np.argmax(toy_lm.next_token_logits([1])))

    def ban(ids, logits):
        out = np.asarray(logits, dtype=np.float64).copy()
        out[banned] = NEG_INF
        return out

    out = generate(
        toy_lm, [1], max_new_tokens=6, config=SamplingConfig(temperature=0.0), processors=[ban]
    )
    assert banned not in out


def test_selector_hook_overrides_choice(toy_lm: ToyLM):
    out = generate(
        toy_lm, [1], max_new_tokens=4, selector=lambda ids, probs, rng: 5, use_cache=False
    )
    assert out == [5, 5, 5, 5]


def test_generate_with_and_without_cache_agree():
    """真实模型上，带 KV Cache 与每步重算必须给出同一条序列。"""
    model = TinyLM(TinyLMConfig(vocab_size=13, dim=8, n_layers=2, n_heads=2, max_seq_len=24, seed=5))
    config = SamplingConfig(temperature=0.0)
    cached = generate(model, [1, 2, 3], max_new_tokens=10, config=config, use_cache=True)
    plain = generate(model, [1, 2, 3], max_new_tokens=10, config=config, use_cache=False)
    assert cached == plain


# ----------------------------------------------------------------------
# beam search
# ----------------------------------------------------------------------
def _sequence_logprob(model: ToyLM, prompt: list[int], tokens: list[int]) -> float:
    total = 0.0
    ids = list(prompt)
    for token in tokens:
        probs = softmax(model.next_token_logits(ids))
        total += float(np.log(probs[token] + 1e-30))
        ids.append(token)
    return total


def test_beam_search_returns_sorted_candidates(toy_lm: ToyLM):
    beams = beam_search(toy_lm, [1], max_new_tokens=4, beam_width=3)
    assert len(beams) == 3
    assert all(len(tokens) == 4 for tokens in beams)
    scores = [_sequence_logprob(toy_lm, [1], tokens) for tokens in beams]
    assert scores == sorted(scores, reverse=True)


def test_beam_search_beats_greedy_on_total_logprob(toy_lm: ToyLM):
    """集束搜索的目标是整条序列的似然，因此不会差于贪心。"""
    greedy = generate(toy_lm, [1], max_new_tokens=5, config=SamplingConfig(temperature=0.0))
    best = beam_search(toy_lm, [1], max_new_tokens=5, beam_width=4)[0]
    assert _sequence_logprob(toy_lm, [1], best) >= _sequence_logprob(toy_lm, [1], greedy) - 1e-9


def test_beam_search_stops_at_eos(toy_lm: ToyLM):
    """遇到 eos 的候选会被冻结：eos 只能出现在序列末尾，且不再被延长。"""
    eos = int(np.argmax(toy_lm.next_token_logits([1])))
    beams = beam_search(toy_lm, [1], max_new_tokens=6, beam_width=3, eos_id=eos)
    assert any(tokens and tokens[-1] == eos for tokens in beams)
    assert all(eos not in tokens[:-1] for tokens in beams)
    assert all(len(tokens) <= 6 for tokens in beams)


def test_beam_search_width_one_is_greedy(toy_lm: ToyLM):
    beam = beam_search(toy_lm, [2], max_new_tokens=4, beam_width=1)[0]
    greedy = generate(toy_lm, [2], max_new_tokens=4, config=SamplingConfig(temperature=0.0))
    assert beam == greedy


def test_no_grad_generation_leaves_no_graph():
    model = TinyLM(TinyLMConfig(vocab_size=13, dim=8, n_layers=1, n_heads=2, max_seq_len=24))
    with no_grad():
        logits = model(np.array([[1, 2]]))
    assert not logits.requires_grad
