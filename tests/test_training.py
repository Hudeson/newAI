"""训练循环：batch 构造（尤其是 SFT 的提示词掩码）与损失下降。"""

from __future__ import annotations

import numpy as np
import pytest

from dive.training import (
    IGNORE_INDEX,
    TrainConfig,
    causal_batch,
    evaluate_loss,
    pad_sequences,
    perplexity,
    sft_batch,
    train_causal_lm,
)
from dive.transformer import TinyLM, TinyLMConfig


# ----------------------------------------------------------------------
# batch 构造
# ----------------------------------------------------------------------
def test_pad_sequences_right_pads():
    padded = pad_sequences([[1, 2, 3], [4]], pad_id=0)
    assert padded.tolist() == [[1, 2, 3], [4, 0, 0]]


def test_causal_batch_shifts_by_one():
    inputs, targets = causal_batch([[1, 2, 3, 4]], pad_id=0)
    assert inputs.tolist() == [[1, 2, 3]]
    assert targets.tolist() == [[2, 3, 4]]


def test_causal_batch_masks_padding_tail():
    inputs, targets = causal_batch([[1, 2, 3, 4], [5, 6]], pad_id=0)
    assert inputs.tolist() == [[1, 2, 3], [5, 6, 0]]
    # 第二条只有 5->6 这一个真实预测，补齐位置全部忽略
    assert targets.tolist() == [[2, 3, 4], [6, IGNORE_INDEX, IGNORE_INDEX]]


def test_sft_batch_masks_exactly_the_prompt_positions():
    """提示词内部的预测不参与损失，回答的第一个 token 必须参与。"""
    prompt = [1, 2, 3, 4]  # 4 个提示 token
    answer = [7, 8, 9]
    sequence = prompt + answer
    inputs, targets = sft_batch([sequence], prompt_lengths=[len(prompt)], pad_id=0)

    assert inputs.tolist() == [[1, 2, 3, 4, 7, 8]]
    # targets[t] 预测原序列第 t+1 个 token；前 len(prompt)-1 个位置被掩掉
    assert targets.tolist() == [[IGNORE_INDEX, IGNORE_INDEX, IGNORE_INDEX, 7, 8, 9]]
    assert int((targets[0] != IGNORE_INDEX).sum()) == len(answer)


def test_sft_batch_supervises_only_the_answer_tokens():
    prompt_lengths = [3, 5]
    sequences = [[1, 2, 3, 40, 41], [1, 2, 3, 4, 5, 60, 61, 62]]
    _, targets = sft_batch(sequences, prompt_lengths, pad_id=0)
    for row, (sequence, prompt_len) in enumerate(zip(sequences, prompt_lengths)):
        supervised = targets[row][targets[row] != IGNORE_INDEX].tolist()
        assert supervised == sequence[prompt_len:]


def test_sft_batch_differs_from_causal_batch():
    sequences = [[1, 2, 3, 4, 5]]
    _, causal = causal_batch(sequences, pad_id=0)
    _, sft = sft_batch(sequences, [3], pad_id=0)
    assert int((causal != IGNORE_INDEX).sum()) > int((sft != IGNORE_INDEX).sum())


# ----------------------------------------------------------------------
# 训练
# ----------------------------------------------------------------------
def tiny_setup() -> tuple[TinyLM, list[tuple[np.ndarray, np.ndarray]]]:
    """一个可以被完美记住的迷你语料。

    三条序列的每个前缀都唯一决定下一个 token，因此理论最优损失为 0——
    这样「损失下降」才是一个干净的信号，不会被数据本身的歧义拖住。
    """
    sequences = [[1, 2, 3, 4], [5, 6, 7, 8], [2, 9, 1, 3]] * 4
    batches = [causal_batch(sequences[i : i + 3], pad_id=0) for i in range(0, len(sequences), 3)]
    model = TinyLM(TinyLMConfig(vocab_size=10, dim=16, n_layers=2, n_heads=2, max_seq_len=16, seed=0))
    return model, batches


def test_train_causal_lm_reduces_loss():
    model, batches = tiny_setup()
    history = train_causal_lm(
        model, batches, TrainConfig(epochs=15, lr=5e-3, verbose=False)
    )
    assert len(history) == 15
    assert history[-1]["loss"] < history[0]["loss"]
    assert history[-1]["loss"] < 0.5
    assert history[-1]["ppl"] == pytest.approx(np.exp(history[-1]["loss"]))


def test_train_causal_lm_records_history_on_config():
    model, batches = tiny_setup()
    config = TrainConfig(epochs=3, verbose=False)
    train_causal_lm(model, batches, config)
    assert [record["epoch"] for record in config.history] == [1.0, 2.0, 3.0]


def test_on_epoch_end_callback_is_invoked():
    model, batches = tiny_setup()
    seen: list[int] = []
    train_causal_lm(
        model,
        batches,
        TrainConfig(epochs=4, verbose=False),
        on_epoch_end=lambda epoch, loss: seen.append(epoch),
    )
    assert seen == [1, 2, 3, 4]


def test_evaluate_loss_and_perplexity_are_consistent():
    model, batches = tiny_setup()
    loss = evaluate_loss(model, batches)
    assert perplexity(model, batches) == pytest.approx(np.exp(loss))


def test_evaluate_loss_drops_after_training():
    model, batches = tiny_setup()
    before = evaluate_loss(model, batches)
    train_causal_lm(model, batches, TrainConfig(epochs=15, lr=5e-3, verbose=False))
    assert evaluate_loss(model, batches) < before


def test_untrained_perplexity_is_near_vocab_size():
    """随机初始化的模型对 V 个 token 一视同仁，困惑度应接近 V。"""
    model, batches = tiny_setup()
    assert 5.0 < perplexity(model, batches) < 20.0
