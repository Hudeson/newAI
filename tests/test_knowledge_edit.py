"""知识编辑：秩一更新的有效性，以及协方差项对「不伤及无辜」的作用。"""

from __future__ import annotations

import numpy as np
import pytest

from dive.knowledge_edit import (
    AssociativeMemory,
    FactStore,
    evaluate_edit,
    finetune_edit,
    rome_edit,
)

FACTS = [
    ("埃菲尔铁塔位于", "巴黎"),
    ("故宫位于", "北京"),
    ("自由女神像位于", "纽约"),
    ("大本钟位于", "伦敦"),
    ("红场位于", "莫斯科"),
    ("交大位于", "上海"),
    ("金字塔位于", "开罗"),
    ("悉尼歌剧院位于", "悉尼"),
    ("泰姬陵位于", "阿格拉"),
    ("兵马俑位于", "西安"),
]


def build_store(dim: int = 32, correlation: float = 0.6) -> FactStore:
    store = FactStore(dim=dim, seed=0, correlation=correlation)
    store.add_many(FACTS)
    store.add("埃菲尔铁塔位于", "罗马", as_fact=False)  # 只登记新客体向量
    store.fit()
    return store


# ----------------------------------------------------------------------
# 关联记忆
# ----------------------------------------------------------------------
def test_memory_fit_recalls_training_facts():
    store = build_store()
    for subject, obj in FACTS:
        assert store.recall(subject) == obj


def test_memory_shapes_and_copy():
    memory = AssociativeMemory(np.zeros((5, 3)))
    assert (memory.d_key, memory.d_value) == (5, 3)
    clone = memory.copy()
    clone.weight[0, 0] = 1.0
    assert memory.weight[0, 0] == 0.0


def test_fact_store_rejects_invalid_correlation():
    for correlation in (-0.1, 1.0, 1.5):
        with pytest.raises(ValueError):
            FactStore(correlation=correlation)


def test_fact_store_requires_fit_before_recall():
    store = FactStore(dim=8)
    store.add_many(FACTS[:2])
    with pytest.raises(RuntimeError):
        store.recall("故宫位于")


def test_covariance_is_symmetric_positive_semidefinite():
    covariance = build_store().covariance()
    assert np.allclose(covariance, covariance.T)
    assert (np.linalg.eigvalsh(covariance) > -1e-9).all()


# ----------------------------------------------------------------------
# ROME
# ----------------------------------------------------------------------
def test_rome_edit_is_effective_and_rank_one():
    store = build_store()
    key = store.subject_vectors["埃菲尔铁塔位于"]
    value = store.object_vectors["罗马"]
    edited = rome_edit(store.memory, key, value, covariance=store.covariance())

    report = evaluate_edit(store.memory, edited, key, value, store.keys())
    assert report.efficacy > 0.999, f"编辑没生效：efficacy={report.efficacy}"
    assert report.rank == 1, f"ΔW 的秩应为 1，实际 {report.rank}"
    assert store.recall("埃菲尔铁塔位于", edited) == "罗马"


def test_rome_edit_satisfies_the_constraint_exactly():
    """闭式解要保证 ``W' k* = v*`` 精确成立。"""
    rng = np.random.default_rng(0)
    memory = AssociativeMemory(rng.normal(size=(12, 7)))
    key = rng.normal(size=12)
    value = rng.normal(size=7)
    edited = rome_edit(memory, key, value)
    assert np.allclose(edited.recall(key), value, atol=1e-10)


def test_covariance_improves_locality():
    """协方差项把更新推向「最不干扰其他知识」的方向。"""
    store = build_store()
    key = store.subject_vectors["埃菲尔铁塔位于"]
    value = store.object_vectors["罗马"]
    others = store.keys([s for s, _ in FACTS if s != "埃菲尔铁塔位于"])

    plain = evaluate_edit(
        store.memory, rome_edit(store.memory, key, value), key, value, others
    )
    with_cov = evaluate_edit(
        store.memory,
        rome_edit(store.memory, key, value, covariance=store.covariance()),
        key,
        value,
        others,
    )

    assert plain.efficacy > 0.999 and with_cov.efficacy > 0.999
    assert with_cov.locality > plain.locality
    assert with_cov.max_drift < plain.max_drift


def test_rome_beats_naive_finetuning_on_locality():
    store = build_store()
    key = store.subject_vectors["埃菲尔铁塔位于"]
    value = store.object_vectors["罗马"]
    others = store.keys([s for s, _ in FACTS if s != "埃菲尔铁塔位于"])

    rome = evaluate_edit(
        store.memory,
        rome_edit(store.memory, key, value, covariance=store.covariance()),
        key,
        value,
        others,
    )
    tuned = evaluate_edit(
        store.memory, finetune_edit(store.memory, key, value), key, value, others
    )

    assert tuned.efficacy > 0.99, "对照组也应该改对目标事实"
    assert rome.locality > tuned.locality


def test_sequential_rome_edits_keep_other_facts_alive():
    """连续编辑三条事实后，其余事实的召回准确率不应崩塌。"""
    store = build_store()
    memory = store.memory
    covariance = store.covariance()
    targets = [("故宫位于", "罗马"), ("红场位于", "巴黎"), ("交大位于", "伦敦")]

    for subject, new_object in targets:
        memory = rome_edit(
            memory,
            store.subject_vectors[subject],
            store.object_vectors[new_object],
            covariance=covariance,
        )
        assert store.recall(subject, memory) == new_object

    untouched = [s for s, _ in FACTS if s not in dict(targets)]
    correct = sum(1 for subject in untouched if store.recall(subject, memory) == dict(FACTS)[subject])
    assert correct == len(untouched)


def test_rome_rejects_dimension_mismatch():
    memory = AssociativeMemory(np.zeros((6, 4)))
    with pytest.raises(ValueError):
        rome_edit(memory, np.zeros(5), np.zeros(4))
    with pytest.raises(ValueError):
        rome_edit(memory, np.zeros(6), np.zeros(3))


def test_rome_rejects_orthogonal_update_direction():
    memory = AssociativeMemory(np.zeros((3, 2)))
    with pytest.raises(ValueError):
        rome_edit(memory, np.zeros(3), np.ones(2))


# ----------------------------------------------------------------------
# 评测口径
# ----------------------------------------------------------------------
def test_evaluate_edit_reports_zero_change_for_identity_edit():
    store = build_store()
    key = store.subject_vectors["故宫位于"]
    value = store.object_vectors["北京"]
    report = evaluate_edit(store.memory, store.memory.copy(), key, value, store.keys())
    assert report.weight_change == pytest.approx(0.0)
    assert report.rank == 0
    assert report.locality == pytest.approx(1.0)
    assert report.max_drift == pytest.approx(0.0)


def test_accuracy_can_skip_the_edited_fact():
    store = build_store()
    assert store.accuracy(store.memory) == 1.0
    assert store.accuracy(store.memory, skip="故宫位于") == 1.0


def test_zero_correlation_makes_covariance_irrelevant():
    """主语向量互相正交时，协方差退化为单位阵的倍数，两种更新方向一致。"""
    store = FactStore(dim=64, seed=1, correlation=0.0)
    store.add_many(FACTS)
    store.add("故宫位于", "罗马", as_fact=False)
    store.fit()

    key = store.subject_vectors["故宫位于"]
    value = store.object_vectors["罗马"]
    others = store.keys([s for s, _ in FACTS if s != "故宫位于"])

    plain = evaluate_edit(store.memory, rome_edit(store.memory, key, value), key, value, others)
    with_cov = evaluate_edit(
        store.memory,
        rome_edit(store.memory, key, value, covariance=store.covariance()),
        key,
        value,
        others,
    )
    assert abs(with_cov.locality - plain.locality) < 0.05
