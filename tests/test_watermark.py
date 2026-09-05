"""KGW 绿名单水印：可打上、可检出、可复现，且低熵时必然失效。"""

from __future__ import annotations

import numpy as np
import pytest

from dive.decoding import SamplingConfig, generate
from dive.watermark import DetectionResult, GreenListWatermark, WatermarkConfig

from .conftest import UniformLM

VOCAB = 64


# ----------------------------------------------------------------------
# 配置与绿名单
# ----------------------------------------------------------------------
def test_config_rejects_invalid_gamma():
    for gamma in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError):
            WatermarkConfig(gamma=gamma)


def test_config_rejects_non_positive_context_width():
    with pytest.raises(ValueError):
        WatermarkConfig(context_width=0)


def test_green_list_size_follows_gamma():
    mark = GreenListWatermark(VOCAB, WatermarkConfig(gamma=0.25))
    assert mark.green_size == 16
    assert mark.green_ids([3]).shape == (16,)
    assert int(mark.green_mask([3]).sum()) == 16


def test_green_list_depends_on_context_and_is_reproducible():
    mark = GreenListWatermark(VOCAB)
    assert set(mark.green_ids([7]).tolist()) == set(mark.green_ids([7]).tolist())
    assert set(mark.green_ids([7]).tolist()) != set(mark.green_ids([8]).tolist())


def test_green_list_depends_on_hash_key():
    first = GreenListWatermark(VOCAB, WatermarkConfig(hash_key=1))
    second = GreenListWatermark(VOCAB, WatermarkConfig(hash_key=2))
    assert set(first.green_ids([5]).tolist()) != set(second.green_ids([5]).tolist())


def test_processor_adds_delta_only_to_green_tokens():
    mark = GreenListWatermark(VOCAB, WatermarkConfig(gamma=0.25, delta=3.0))
    logits = np.zeros(VOCAB)
    biased = mark([9], logits)
    green = mark.green_mask([9])
    assert np.allclose(biased[green], 3.0)
    assert np.allclose(biased[~green], 0.0)
    assert np.allclose(logits, 0.0), "processor 不应原地修改输入"


def test_processor_is_noop_before_enough_context():
    mark = GreenListWatermark(VOCAB, WatermarkConfig(context_width=2))
    logits = np.arange(VOCAB, dtype=np.float64)
    assert np.allclose(mark([1], logits), logits)


# ----------------------------------------------------------------------
# 检测
# ----------------------------------------------------------------------
def test_detect_is_deterministic():
    mark = GreenListWatermark(VOCAB)
    ids = list(np.random.default_rng(0).integers(0, VOCAB, size=50))
    first, second = mark.detect(ids), mark.detect(ids)
    assert (first.z_score, first.green_tokens) == (second.z_score, second.green_tokens)


def test_detect_on_empty_and_short_input():
    mark = GreenListWatermark(VOCAB)
    result = mark.detect([1])
    assert result.scored_tokens == 0 and result.z_score == 0.0


def test_detect_z_score_matches_formula():
    mark = GreenListWatermark(VOCAB, WatermarkConfig(gamma=0.25))
    ids = list(np.random.default_rng(1).integers(0, VOCAB, size=80))
    result = mark.detect(ids)
    gamma, scored, green = 0.25, result.scored_tokens, result.green_tokens
    expected = (green - gamma * scored) / np.sqrt(scored * gamma * (1 - gamma))
    assert result.z_score == pytest.approx(expected)
    assert result.green_fraction == pytest.approx(green / scored)


def test_all_green_text_gives_maximal_z():
    """人工构造一条全绿序列，z 应等于 sqrt(T(1-γ)/γ)。"""
    mark = GreenListWatermark(VOCAB, WatermarkConfig(gamma=0.25))
    ids = [0]
    for _ in range(40):
        ids.append(int(mark.green_ids(ids[-1:])[0]))
    result = mark.detect(ids)
    assert result.green_fraction == 1.0
    assert result.z_score == pytest.approx(np.sqrt(40 * 0.75 / 0.25))


def test_detection_result_threshold():
    assert DetectionResult(5.0, 0.0, 40, 50, 0.8).is_watermarked()
    assert not DetectionResult(1.2, 0.1, 15, 50, 0.3).is_watermarked()
    assert DetectionResult(3.0, 0.0, 30, 50, 0.6).is_watermarked(threshold=2.0)


# ----------------------------------------------------------------------
# 端到端：生成 + 检测
# ----------------------------------------------------------------------
def test_watermarked_text_scores_far_above_clean_text(uniform_lm: UniformLM):
    mark = GreenListWatermark(uniform_lm.vocab_size, WatermarkConfig(gamma=0.25, delta=4.0))
    config = SamplingConfig(temperature=1.0, seed=0)

    watermarked = generate(uniform_lm, [1], max_new_tokens=120, config=config, processors=[mark])
    clean = generate(uniform_lm, [1], max_new_tokens=120, config=config)

    marked_z = mark.detect([1] + watermarked).z_score
    clean_z = mark.detect([1] + clean).z_score

    assert marked_z > 8.0, f"含水印文本 z={marked_z:.2f} 偏低"
    assert clean_z < 4.0, f"无水印文本 z={clean_z:.2f} 触发误报"
    assert marked_z > clean_z + 5.0
    assert mark.detect([1] + watermarked).is_watermarked()
    assert not mark.detect([1] + clean).is_watermarked()


def test_larger_delta_gives_stronger_watermark(uniform_lm: UniformLM):
    scores = []
    for delta in (0.5, 2.0, 6.0):
        mark = GreenListWatermark(uniform_lm.vocab_size, WatermarkConfig(gamma=0.25, delta=delta))
        tokens = generate(
            uniform_lm,
            [1],
            max_new_tokens=100,
            config=SamplingConfig(temperature=1.0, seed=3),
            processors=[mark],
        )
        scores.append(mark.detect([1] + tokens).z_score)
    assert scores[0] < scores[1] < scores[2]


def test_watermark_fails_on_deterministic_low_entropy_model():
    """熵为零时水印无处可藏：模型只有一个可选 token，加多大的 δ 都改不了。"""

    class DeterministicLM:
        vocab_size = 40

        def next_token_logits(self, ids):
            logits = np.full(self.vocab_size, -50.0)
            logits[(int(ids[-1]) + 1) % self.vocab_size] = 50.0
            return logits

    model = DeterministicLM()
    mark = GreenListWatermark(model.vocab_size, WatermarkConfig(gamma=0.25, delta=4.0))
    tokens = generate(
        model, [1], max_new_tokens=100, config=SamplingConfig(temperature=1.0, seed=0), processors=[mark]
    )
    assert not mark.detect([1] + tokens).is_watermarked()


def test_replacing_tokens_degrades_but_does_not_erase_the_watermark(uniform_lm: UniformLM):
    mark = GreenListWatermark(uniform_lm.vocab_size, WatermarkConfig(gamma=0.25, delta=4.0))
    tokens = [1] + generate(
        uniform_lm,
        [1],
        max_new_tokens=200,
        config=SamplingConfig(temperature=1.0, seed=1),
        processors=[mark],
    )
    intact = mark.detect(tokens).z_score

    rng = np.random.default_rng(0)
    attacked = list(tokens)
    for position in rng.choice(range(1, len(attacked)), size=len(attacked) // 5, replace=False):
        attacked[int(position)] = int(rng.integers(0, uniform_lm.vocab_size))
    degraded = mark.detect(attacked).z_score

    assert degraded < intact
    assert degraded > 4.0, "改写 20% 的 token 还不该让水印彻底消失"
