"""多模态：一个可训练的迷你 CLIP。

多模态大模型的第一步永远是**对齐**：把图像和文本投影到同一个向量空间，
让配对的图文互相靠近、不配对的互相远离。CLIP 用对比学习（InfoNCE）做这件事：

.. math::
   \\mathcal{L} = \\tfrac12\\big[\\mathrm{CE}(\\tau\\,I T^{\\top}, \\mathrm{diag})
                 + \\mathrm{CE}(\\tau\\,T I^{\\top}, \\mathrm{diag})\\big]

一个 batch 里的 N 个图文对互为负样本，因此 batch 越大对比信号越强。
对齐完成后就能"零样本分类"：把类别名写成文本，看哪个文本与图像最近。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .autograd import Tensor, cross_entropy, no_grad
from .nn import AdamW, Embedding, Linear, Module, clip_grad_norm
from .autograd import Parameter

__all__ = ["MiniCLIP", "SyntheticImageText", "train_clip", "zero_shot_classify", "retrieval_at_k"]


def l2_normalize(x: Tensor, eps: float = 1e-8) -> Tensor:
    """按最后一维做 L2 归一化，使内积等于余弦相似度。"""
    return x / ((x * x).sum(axis=-1, keepdims=True) + eps).sqrt()


class MiniCLIP(Module):
    """双塔结构：图像塔是线性投影，文本塔是词嵌入 + 平均池化 + 投影。"""

    def __init__(
        self,
        image_dim: int,
        vocab_size: int,
        embed_dim: int = 32,
        text_dim: int = 32,
        seed: int = 0,
    ) -> None:
        super().__init__()
        rng = np.random.default_rng(seed)
        self.image_proj = Linear(image_dim, embed_dim, bias=False, rng=rng)
        self.token_embed = Embedding(vocab_size, text_dim, rng=rng)
        self.text_proj = Linear(text_dim, embed_dim, bias=False, rng=rng)
        # 可学习温度，与 CLIP 一致地在对数空间参数化
        self.log_temperature = Parameter(np.array(np.log(1 / 0.07)))

    def encode_image(self, images: np.ndarray) -> Tensor:
        return l2_normalize(self.image_proj(Tensor(np.asarray(images, dtype=np.float64))))

    def encode_text(self, token_ids: np.ndarray) -> Tensor:
        ids = np.atleast_2d(np.asarray(token_ids, dtype=np.int64))
        return l2_normalize(self.text_proj(self.token_embed(ids).mean(axis=1)))

    def logits(self, images: np.ndarray, token_ids: np.ndarray) -> Tensor:
        image_features = self.encode_image(images)
        text_features = self.encode_text(token_ids)
        scale = self.log_temperature.exp()
        return (image_features @ text_features.transpose()) * scale

    def forward(self, images: np.ndarray, token_ids: np.ndarray) -> Tensor:
        """对称 InfoNCE 损失。"""
        logits = self.logits(images, token_ids)
        targets = np.arange(logits.shape[0])
        return (cross_entropy(logits, targets) + cross_entropy(logits.transpose(), targets)) * 0.5


@dataclass
class SyntheticImageText:
    """合成图文数据集。

    每个类别有一个原型向量，"图像"是原型加噪声；"文本"是该类别名称的
    字符 id 序列。这样既有可学的结构，又不需要下载任何数据。
    """

    class_names: list[str]
    image_dim: int = 24
    noise: float = 0.35
    seed: int = 0

    def __post_init__(self) -> None:
        rng = np.random.default_rng(self.seed)
        self.rng = rng
        self.prototypes = rng.normal(size=(len(self.class_names), self.image_dim))
        self.prototypes /= np.linalg.norm(self.prototypes, axis=1, keepdims=True)

        charset = sorted({ch for name in self.class_names for ch in name})
        self.stoi = {ch: index + 1 for index, ch in enumerate(charset)}  # 0 留给 padding
        self.vocab_size = len(self.stoi) + 1
        self.max_len = max(len(name) for name in self.class_names)

    def encode_text(self, name: str) -> list[int]:
        ids = [self.stoi[ch] for ch in name]
        return ids + [0] * (self.max_len - len(ids))

    def class_token_matrix(self) -> np.ndarray:
        return np.array([self.encode_text(name) for name in self.class_names], dtype=np.int64)

    def sample(self, n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """返回 ``(图像特征, 文本 token, 类别下标)``。"""
        labels = self.rng.integers(0, len(self.class_names), size=n)
        images = self.prototypes[labels] + self.noise * self.rng.normal(size=(n, self.image_dim))
        images /= np.linalg.norm(images, axis=1, keepdims=True)
        tokens = np.array([self.encode_text(self.class_names[label]) for label in labels], dtype=np.int64)
        return images, tokens, labels


def train_clip(
    model: MiniCLIP,
    dataset: SyntheticImageText,
    steps: int = 200,
    batch_size: int = 16,
    lr: float = 5e-3,
    verbose: bool = True,
    log_every: int = 50,
) -> list[dict[str, float]]:
    """对比学习训练循环。

    注意：一个 batch 内若出现同类别的重复文本，会构成"假负样本"——同一个
    正确答案被当成负例去推远。这里按类别去重采样来规避；真实 CLIP 中每条
    caption 都不相同，天然没有这个问题。
    """
    optimizer = AdamW(model.trainable_parameters(), lr=lr)
    history: list[dict[str, float]] = []
    n_classes = len(dataset.class_names)
    batch_size = min(batch_size, n_classes)

    for step in range(1, steps + 1):
        labels = dataset.rng.permutation(n_classes)[:batch_size]
        images = dataset.prototypes[labels] + dataset.noise * dataset.rng.normal(
            size=(batch_size, dataset.image_dim)
        )
        images /= np.linalg.norm(images, axis=1, keepdims=True)
        tokens = np.array(
            [dataset.encode_text(dataset.class_names[label]) for label in labels], dtype=np.int64
        )

        optimizer.zero_grad()
        loss = model(images, tokens)
        loss.backward()
        clip_grad_norm(model.trainable_parameters(), 1.0)
        optimizer.step()

        if step % log_every == 0 or step == 1:
            accuracy = zero_shot_classify(model, dataset, n=200)
            history.append({"step": float(step), "loss": loss.item(), "zero_shot_acc": accuracy})
            if verbose:
                print(f"  step {step:4d} | InfoNCE loss {loss.item():.4f} | 零样本准确率 {accuracy:.1%}")
    return history


def zero_shot_classify(model: MiniCLIP, dataset: SyntheticImageText, n: int = 200) -> float:
    """零样本分类：图像与所有类别名文本比相似度，取最近的那个。"""
    images, _, labels = dataset.sample(n)
    with no_grad():
        image_features = model.encode_image(images).data
        text_features = model.encode_text(dataset.class_token_matrix()).data
    predictions = np.argmax(image_features @ text_features.T, axis=1)
    return float(np.mean(predictions == labels))


def retrieval_at_k(model: MiniCLIP, dataset: SyntheticImageText, n: int = 100, k: int = 1) -> float:
    """图搜文 R@k：正确类别的文本是否落在前 k 个最相似结果里。"""
    images, _, labels = dataset.sample(n)
    with no_grad():
        image_features = model.encode_image(images).data
        text_features = model.encode_text(dataset.class_token_matrix()).data
    scores = image_features @ text_features.T
    top_k = np.argsort(-scores, axis=1)[:, :k]
    return float(np.mean([labels[i] in top_k[i] for i in range(n)]))
