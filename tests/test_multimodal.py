"""迷你 CLIP：L2 归一化、对比学习收敛与零样本 / 检索评测。"""

from __future__ import annotations

import numpy as np
import pytest

from dive.autograd import Tensor, no_grad
from dive.multimodal import (
    MiniCLIP,
    SyntheticImageText,
    l2_normalize,
    retrieval_at_k,
    train_clip,
    zero_shot_classify,
)

CLASSES = ["cat", "dog", "bird", "fish", "tree", "rock", "star", "boat"]


def build(seed: int = 0) -> tuple[MiniCLIP, SyntheticImageText]:
    dataset = SyntheticImageText(class_names=list(CLASSES), image_dim=16, noise=0.3, seed=seed)
    model = MiniCLIP(image_dim=dataset.image_dim, vocab_size=dataset.vocab_size, embed_dim=16, seed=seed)
    return model, dataset


# ----------------------------------------------------------------------
# 归一化
# ----------------------------------------------------------------------
def test_l2_normalize_gives_unit_norm():
    x = Tensor(np.random.default_rng(0).normal(size=(5, 7)) * 9.0)
    norms = np.linalg.norm(l2_normalize(x).data, axis=-1)
    assert np.allclose(norms, 1.0, atol=1e-6)


def test_l2_normalize_keeps_direction():
    x = Tensor(np.array([[3.0, 4.0]]))
    assert np.allclose(l2_normalize(x).data, [[0.6, 0.8]])


def test_l2_normalize_handles_zero_vector():
    assert np.isfinite(l2_normalize(Tensor(np.zeros((1, 4)))).data).all()


# ----------------------------------------------------------------------
# 数据与前向
# ----------------------------------------------------------------------
def test_dataset_shapes_and_vocabulary():
    _, dataset = build()
    images, tokens, labels = dataset.sample(6)
    assert images.shape == (6, dataset.image_dim)
    assert tokens.shape == (6, dataset.max_len)
    assert labels.shape == (6,)
    assert np.allclose(np.linalg.norm(images, axis=1), 1.0)
    assert dataset.class_token_matrix().shape == (len(CLASSES), dataset.max_len)
    assert 0 not in dataset.stoi.values(), "0 必须留给 padding"


def test_encoders_produce_normalized_features():
    model, dataset = build()
    images, tokens, _ = dataset.sample(4)
    with no_grad():
        image_features = model.encode_image(images).data
        text_features = model.encode_text(tokens).data
    assert image_features.shape == (4, 16)
    assert np.allclose(np.linalg.norm(image_features, axis=1), 1.0, atol=1e-6)
    assert np.allclose(np.linalg.norm(text_features, axis=1), 1.0, atol=1e-6)


def test_logits_are_scaled_cosine_similarities():
    model, dataset = build()
    images, tokens, _ = dataset.sample(3)
    with no_grad():
        logits = model.logits(images, tokens).data
        image_features = model.encode_image(images).data
        text_features = model.encode_text(tokens).data
    scale = float(np.exp(model.log_temperature.data))
    assert np.allclose(logits, scale * image_features @ text_features.T)
    assert np.abs(logits / scale).max() <= 1.0 + 1e-9


def test_infonce_loss_is_symmetric_and_finite():
    model, dataset = build()
    images, tokens, _ = dataset.sample(4)
    loss = model(images, tokens)
    assert loss.size == 1 and np.isfinite(loss.item())
    # 随机初始化下，对比损失应接近 log(batch_size)
    assert loss.item() < 3.0


# ----------------------------------------------------------------------
# 训练
# ----------------------------------------------------------------------
def test_training_improves_zero_shot_accuracy():
    model, dataset = build()
    before = zero_shot_classify(model, dataset, n=200)
    history = train_clip(model, dataset, steps=150, batch_size=8, lr=1e-2, verbose=False)
    after = zero_shot_classify(model, dataset, n=200)

    assert history[-1]["loss"] < history[0]["loss"]
    assert after > before + 0.3, f"零样本准确率只从 {before:.1%} 提到 {after:.1%}"
    assert after > 0.6


def test_retrieval_at_k_is_monotone_in_k():
    model, dataset = build()
    train_clip(model, dataset, steps=150, batch_size=8, lr=1e-2, verbose=False)
    at1 = retrieval_at_k(model, dataset, n=100, k=1)
    at3 = retrieval_at_k(model, dataset, n=100, k=3)
    assert at1 <= at3
    assert at3 > 0.8
    # 取遍所有类别时必然命中
    assert retrieval_at_k(model, dataset, n=50, k=len(CLASSES)) == pytest.approx(1.0)


def test_zero_shot_accuracy_is_a_fraction():
    model, dataset = build()
    accuracy = zero_shot_classify(model, dataset, n=50)
    assert 0.0 <= accuracy <= 1.0


def test_noise_level_controls_the_difficulty():
    """噪声越大，图文对齐越难——这是数据本身的上限，不是模型的问题。"""
    scores = []
    for noise in (0.2, 1.2):
        dataset = SyntheticImageText(class_names=list(CLASSES), image_dim=16, noise=noise, seed=0)
        model = MiniCLIP(image_dim=dataset.image_dim, vocab_size=dataset.vocab_size, embed_dim=16, seed=0)
        train_clip(model, dataset, steps=150, batch_size=8, lr=1e-2, verbose=False)
        scores.append(zero_shot_classify(model, dataset, n=200))
    assert scores[0] > scores[1]


def test_temperature_is_learnable():
    model, dataset = build()
    initial = float(model.log_temperature.data)
    train_clip(model, dataset, steps=60, batch_size=8, lr=1e-2, verbose=False)
    assert float(model.log_temperature.data) != initial
