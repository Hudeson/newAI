"""实验脚本共用的数据与训练工具的冒烟测试。

这里不跑完整实验（那是 ``labs/`` 的事），只保证数据构造与训练接口不退化：
一旦这些性质被破坏，各章实验得出的结论就不再可信。
"""

from __future__ import annotations

import numpy as np
import pytest

from labs._corpus import SLOTS, build_slot_corpus, mean_entropy, train_slot_lm
from labs._tasks import ArithmeticTask, build_sentiment_task, train_on_task


# ----------------------------------------------------------------------
# 情感分类任务
# ----------------------------------------------------------------------
def test_sentiment_task_test_set_is_held_out():
    """测试集必须由训练中从未同现的「主语 + 情感词」组合构成。"""
    task = build_sentiment_task()
    assert task.train_examples and task.test_examples
    train_prompts = {prompt for prompt, _ in task.train_examples}
    assert not train_prompts & {prompt for prompt, _ in task.test_examples}
    assert set(label for _, label in task.test_examples) == {"正面", "负面"}


def test_sentiment_batches_mask_the_prompt():
    from dive.training import IGNORE_INDEX

    task = build_sentiment_task()
    inputs, targets = task.batches(batch_size=8)[0]
    assert inputs.shape == targets.shape
    supervised = int((targets != IGNORE_INDEX).sum())
    assert 0 < supervised < targets.size


# ----------------------------------------------------------------------
# 加法任务
# ----------------------------------------------------------------------
def test_arithmetic_task_splits_do_not_overlap():
    task = ArithmeticTask(n_train=200, n_test=50, digits=2)
    assert len(task.train_pairs) == 200 and len(task.test_pairs) == 50
    assert not set(task.train_pairs) & set(task.test_pairs)


def test_arithmetic_prompt_and_gold_are_zero_padded():
    task = ArithmeticTask(n_train=10, n_test=2, digits=2)
    assert task.prompt(7, 5) == "07+05="
    assert task.gold(7, 5) == "012"
    assert task.gold(99, 99) == "198"


@pytest.mark.parametrize("style", ["direct", "reverse", "cot"])
def test_all_styles_end_with_the_same_answer(style: str):
    task = ArithmeticTask(n_train=10, n_test=2, digits=2, style=style)
    target = task.target(38, 47)
    assert target.endswith("085")
    assert task.answer_matches(target, "085")


def test_cot_reasoning_records_每位相加与进位():
    task = ArithmeticTask(n_train=10, n_test=2, digits=2, style="cot")
    # 38 + 47：个位 8+7=15（进 1），十位 3+4+1=8
    assert task.reasoning(38, 47) == "[8+7=5c1;3+4+1=8c0]"
    assert task.target(38, 47) == "[8+7=5c1;3+4+1=8c0]085"


def test_reverse_draft_is_the_answer_backwards():
    task = ArithmeticTask(n_train=10, n_test=2, digits=2, style="reverse")
    assert task.reverse_draft(38, 47) == "[580]"


def test_cot_targets_are_the_longest():
    lengths = {
        style: ArithmeticTask(n_train=10, n_test=2, digits=2, style=style).target_length
        for style in ("direct", "reverse", "cot")
    }
    assert lengths["direct"] < lengths["reverse"] < lengths["cot"]


def test_answer_matches_ignores_the_reasoning_prefix():
    task = ArithmeticTask(n_train=10, n_test=2, digits=2)
    assert task.answer_matches("[8+7=5c1;3+4+1=8c0]085", "085")
    assert not task.answer_matches("[8+7=5c1]086", "085")
    assert not task.answer_matches("没有数字", "085")


def test_arithmetic_task_rejects_unknown_style():
    with pytest.raises(ValueError):
        ArithmeticTask(style="magic")


def test_arithmetic_task_rejects_impossible_size():
    with pytest.raises(ValueError):
        ArithmeticTask(n_train=200, n_test=0, digits=1)


def test_to_sft_task_covers_every_character():
    task = ArithmeticTask(n_train=50, n_test=10, digits=2, style="cot")
    sft = task.to_sft_task()
    for prompt, target in sft.train_examples:
        assert sft.tokenizer.unk_id not in sft.tokenizer.encode(prompt + target)


def test_train_on_task_learns_a_trivial_task():
    """在极小任务上训练几轮就应该能背下来——用于守住训练接口本身。"""
    task = ArithmeticTask(n_train=24, n_test=6, digits=1, style="direct").to_sft_task()
    model = train_on_task(task, dim=32, n_layers=2, epochs=25, batch_size=24, verbose=False)
    assert task.accuracy(model, task.train_examples[:6]) >= 0.5


# ----------------------------------------------------------------------
# 水印 / 隐写用的槽位语料
# ----------------------------------------------------------------------
def test_slot_corpus_respects_the_slot_order():
    documents = build_slot_corpus(n_documents=8, clauses_per_document=3, seed=0)
    assert len(documents) == 8
    assert all(len(document) == 3 * len(SLOTS) for document in documents)
    for document in documents:
        for position, word in enumerate(document):
            assert word in SLOTS[position % len(SLOTS)]


def test_slot_width_one_makes_the_corpus_deterministic():
    documents = build_slot_corpus(n_documents=12, clauses_per_document=2, seed=0, slot_width=1)
    assert len({tuple(document) for document in documents}) == 1


def small_slot_lm(width: int):
    return train_slot_lm(
        n_documents=64,
        clauses_per_document=2,
        epochs=12,
        dim=48,
        n_layers=1,
        batch_size=32,
        seed=0,
        verbose=False,
        slot_width=width,
    )


def test_slot_width_controls_entropy():
    """槽位越宽，每步的可选项越多，熵越高——水印与隐写的容量就来自这里。"""
    entropies = []
    for width in (2, 8):
        tokenizer, model, documents = small_slot_lm(width)
        ids = tokenizer.encode(documents[0], bos=True, eos=True)
        entropies.append(mean_entropy(model, ids))
    assert 0.0 < entropies[0] < entropies[1]


def test_mean_entropy_is_finite_and_non_negative():
    tokenizer, model, documents = small_slot_lm(3)
    ids = tokenizer.encode(documents[0], bos=True, eos=True)
    entropy = mean_entropy(model, ids)
    assert entropy >= 0.0 and np.isfinite(entropy)
