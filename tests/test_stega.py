"""Huffman 隐写：比特流与字节流互转、编码表性质、无损往返与容量上界。"""

from __future__ import annotations

import numpy as np
import pytest

from dive.stega import (
    HuffmanStego,
    StegoPayload,
    bits_to_bytes,
    build_huffman_codes,
    bytes_to_bits,
)

from .conftest import ToyLM, UniformLM

MESSAGES = [b"hi", b"\x00\xff", b"dive", "交大".encode("utf-8")]


# ----------------------------------------------------------------------
# 比特工具
# ----------------------------------------------------------------------
def test_bytes_to_bits_is_big_endian():
    assert bytes_to_bits(b"\x01") == [0, 0, 0, 0, 0, 0, 0, 1]
    assert bytes_to_bits(b"\x80") == [1, 0, 0, 0, 0, 0, 0, 0]


def test_bits_bytes_roundtrip():
    for message in MESSAGES:
        assert bits_to_bytes(bytes_to_bits(message)) == message


def test_bits_to_bytes_drops_incomplete_tail():
    assert bits_to_bytes([1, 0, 1]) == b""
    assert bits_to_bytes(bytes_to_bits(b"\xaa") + [1, 1, 1]) == b"\xaa"


# ----------------------------------------------------------------------
# Huffman 编码表
# ----------------------------------------------------------------------
def test_huffman_codes_are_prefix_free():
    tokens = [10, 11, 12, 13, 14]
    probs = [0.5, 0.2, 0.15, 0.1, 0.05]
    codes = build_huffman_codes(tokens, probs)
    assert set(codes) == set(tokens)
    items = sorted(codes.items())
    for position, (_, code) in enumerate(items):
        for _, other in items[position + 1 :]:
            assert not other.startswith(code) and not code.startswith(other)


def test_huffman_gives_shorter_codes_to_likely_tokens():
    codes = build_huffman_codes([1, 2, 3, 4], [0.7, 0.15, 0.1, 0.05])
    assert len(codes[1]) <= len(codes[2]) <= len(codes[4])


def test_huffman_is_deterministic():
    tokens, probs = [3, 1, 2], [0.4, 0.35, 0.25]
    assert build_huffman_codes(tokens, probs) == build_huffman_codes(tokens, probs)


def test_huffman_uniform_distribution_gives_fixed_length_codes():
    codes = build_huffman_codes(list(range(8)), [0.125] * 8)
    assert {len(code) for code in codes.values()} == {3}


def test_huffman_single_candidate_carries_no_information():
    assert build_huffman_codes([5], [1.0]) == {5: ""}


def test_huffman_rejects_empty_candidate_set():
    with pytest.raises(ValueError):
        build_huffman_codes([], [])


# ----------------------------------------------------------------------
# 端到端隐写
# ----------------------------------------------------------------------
@pytest.mark.parametrize("top_k", [2, 4, 8])
def test_roundtrip_is_lossless(toy_lm: ToyLM, top_k: int):
    stego = HuffmanStego(toy_lm, top_k=top_k)
    prompt = [1, 2]
    for message in MESSAGES:
        payload = stego.encode(prompt, message, max_tokens=400)
        assert stego.decode(prompt, payload) == message


def test_payload_reports_capacity(uniform_lm: UniformLM):
    stego = HuffmanStego(uniform_lm, top_k=8)
    payload = stego.encode([1], b"dive into llms", max_tokens=200)
    assert payload.n_bits == 8 * len("dive into llms")
    assert payload.steps == len(payload.token_ids)
    assert payload.bits_per_token == pytest.approx(payload.n_bits / payload.steps)


def test_capacity_saturates_at_model_entropy(uniform_lm: UniformLM):
    """均匀分布下 top_k 个候选的 Huffman 熵为 log2(top_k)，容量不可能更高。"""
    for top_k in (2, 4, 8):
        stego = HuffmanStego(uniform_lm, top_k=top_k)
        payload = stego.encode([1], b"dive into large language models", max_tokens=400)
        assert payload.bits_per_token == pytest.approx(np.log2(top_k), abs=0.05)


def _try_decode(stego: HuffmanStego, prompt: list[int], payload: StegoPayload) -> bytes | None:
    """密钥（模型 + 前缀）不匹配时，解码要么报错、要么给出错误结果。"""
    try:
        return stego.decode(prompt, payload)
    except ValueError:
        return None


def test_decoding_needs_the_same_prefix(toy_lm: ToyLM):
    stego = HuffmanStego(toy_lm, top_k=4)
    payload = stego.encode([1, 2], b"secret", max_tokens=200)
    assert stego.decode([1, 2], payload) == b"secret"
    assert _try_decode(stego, [3, 4], payload) != b"secret"


def test_decoding_needs_the_same_model(toy_lm: ToyLM):
    stego = HuffmanStego(toy_lm, top_k=4)
    payload = stego.encode([1, 2], b"secret", max_tokens=200)
    other = HuffmanStego(ToyLM(vocab_size=toy_lm.vocab_size, seed=99), top_k=4)
    assert _try_decode(other, [1, 2], payload) != b"secret"


def test_single_token_corruption_destroys_recovery(toy_lm: ToyLM):
    """隐写没有纠错能力：改一个 token 就会让后续比特流全部错位。"""
    stego = HuffmanStego(toy_lm, top_k=4)
    prompt = [1, 2]
    payload = stego.encode(prompt, b"fragile message", max_tokens=400)
    corrupted = StegoPayload(
        token_ids=list(payload.token_ids), n_bits=payload.n_bits, steps=payload.steps
    )
    original = corrupted.token_ids[0]
    top4 = np.argsort(-toy_lm.next_token_logits(prompt))[:4].tolist()
    corrupted.token_ids[0] = int(next(token for token in top4 if token != original))
    assert _try_decode(stego, prompt, corrupted) != b"fragile message"


def test_top_k_one_cannot_embed_anything(uniform_lm: UniformLM):
    stego = HuffmanStego(uniform_lm, top_k=1)
    with pytest.raises(ValueError):
        stego.encode([1], b"x", max_tokens=8)


def test_rejects_invalid_top_k(uniform_lm: UniformLM):
    with pytest.raises(ValueError):
        HuffmanStego(uniform_lm, top_k=0)


def test_encode_raises_when_budget_is_too_small(toy_lm: ToyLM):
    stego = HuffmanStego(toy_lm, top_k=4)
    with pytest.raises(ValueError):
        stego.encode([1], b"a much longer secret message", max_tokens=3)


def test_empty_message_produces_no_tokens(toy_lm: ToyLM):
    payload = HuffmanStego(toy_lm, top_k=4).encode([1], b"")
    assert payload.token_ids == [] and payload.n_bits == 0
