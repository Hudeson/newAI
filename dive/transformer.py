"""一个可训练的迷你 Decoder-only Transformer（LLaMA 风格）。

结构与主流开源大模型保持一致，只是把规模缩到了 CPU 秒级可训练：

* Pre-Norm + RMSNorm
* 旋转位置编码 RoPE（不引入可学习的位置向量）
* 多头因果自注意力，支持 KV Cache 增量解码
* SwiGLU 前馈网络
* 词嵌入与输出头权重共享（tie embeddings）

>>> cfg = TinyLMConfig(vocab_size=32, dim=32, n_layers=2, n_heads=4)
>>> model = TinyLM(cfg)
>>> logits = model.next_token_logits([1, 2, 3])
>>> logits.shape
(32,)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .autograd import Tensor, cat, no_grad
from .nn import Embedding, Linear, Module, ModuleList, RMSNorm

__all__ = ["TinyLMConfig", "TinyLM", "CausalSelfAttention", "SwiGLU", "Block", "rope_tables"]


@dataclass
class TinyLMConfig:
    """迷你语言模型的超参数。"""

    vocab_size: int
    dim: int = 64
    n_layers: int = 2
    n_heads: int = 4
    max_seq_len: int = 256
    ffn_hidden: int | None = None
    rope_base: float = 10000.0
    tie_embeddings: bool = True
    seed: int = 0

    def __post_init__(self) -> None:
        if self.dim % self.n_heads != 0:
            raise ValueError("dim 必须能被 n_heads 整除")
        if self.head_dim % 2 != 0:
            raise ValueError("head_dim 必须是偶数，RoPE 需要成对旋转")
        if self.ffn_hidden is None:
            # LLaMA 的做法：4*dim 再乘 2/3（因为 SwiGLU 有两个输入投影），并对齐到 8
            hidden = int(2 * (4 * self.dim) / 3)
            self.ffn_hidden = ((hidden + 7) // 8) * 8

    @property
    def head_dim(self) -> int:
        return self.dim // self.n_heads


def rope_tables(seq_len: int, head_dim: int, base: float = 10000.0) -> tuple[np.ndarray, np.ndarray]:
    """预计算 RoPE 的 cos / sin 表，形状均为 ``(seq_len, head_dim // 2)``。"""
    half = head_dim // 2
    inv_freq = 1.0 / (base ** (np.arange(half, dtype=np.float64) / half))
    positions = np.arange(seq_len, dtype=np.float64)
    angles = np.outer(positions, inv_freq)
    return np.cos(angles), np.sin(angles)


def apply_rope(x: Tensor, cos: np.ndarray, sin: np.ndarray) -> Tensor:
    """对 ``(B, H, T, head_dim)`` 的张量施加旋转位置编码。

    采用与 HuggingFace / LLaMA 一致的"前后半分"约定：把 head_dim 的
    前一半与后一半配成复数的实部与虚部，再整体旋转一个与位置成正比的角度。
    """
    half = x.shape[-1] // 2
    cos_t = Tensor(cos.reshape(1, 1, *cos.shape))
    sin_t = Tensor(sin.reshape(1, 1, *sin.shape))
    first = x[..., :half]
    second = x[..., half:]
    return cat([first * cos_t - second * sin_t, second * cos_t + first * sin_t], axis=-1)


class CausalSelfAttention(Module):
    """多头因果自注意力。"""

    def __init__(self, config: TinyLMConfig, rng: np.random.Generator) -> None:
        super().__init__()
        self.config = config
        self.n_heads = config.n_heads
        self.head_dim = config.head_dim
        self.wq = Linear(config.dim, config.dim, bias=False, rng=rng)
        self.wk = Linear(config.dim, config.dim, bias=False, rng=rng)
        self.wv = Linear(config.dim, config.dim, bias=False, rng=rng)
        self.wo = Linear(config.dim, config.dim, bias=False, rng=rng)

    def _split_heads(self, x: Tensor, batch: int, seq: int) -> Tensor:
        return x.reshape(batch, seq, self.n_heads, self.head_dim).transpose(0, 2, 1, 3)

    def forward(
        self,
        x: Tensor,
        cos: np.ndarray,
        sin: np.ndarray,
        cache: dict[str, Tensor] | None = None,
    ) -> Tensor:
        batch, seq, _ = x.shape
        q = self._split_heads(self.wq(x), batch, seq)
        k = self._split_heads(self.wk(x), batch, seq)
        v = self._split_heads(self.wv(x), batch, seq)

        q = apply_rope(q, cos, sin)
        k = apply_rope(k, cos, sin)

        if cache is not None and "k" in cache:
            k = cat([cache["k"], k], axis=2)
            v = cat([cache["v"], v], axis=2)
        if cache is not None:
            cache["k"], cache["v"] = k, v

        total = k.shape[2]
        scores = (q @ k.swapaxes(-1, -2)) * (1.0 / np.sqrt(self.head_dim))

        # 因果掩码：查询位置 i（绝对位置 total-seq+i）只能看到 <= 自己的键
        query_pos = np.arange(total - seq, total)[:, None]
        key_pos = np.arange(total)[None, :]
        mask = key_pos > query_pos
        if mask.any():
            scores = scores.masked_fill(mask.reshape(1, 1, seq, total), -1e9)

        attn = scores.softmax(axis=-1)
        out = attn @ v
        out = out.transpose(0, 2, 1, 3).reshape(batch, seq, self.n_heads * self.head_dim)
        return self.wo(out)


class SwiGLU(Module):
    """SwiGLU 前馈网络：``W2(silu(W1 x) * W3 x)``。"""

    def __init__(self, config: TinyLMConfig, rng: np.random.Generator) -> None:
        super().__init__()
        hidden = int(config.ffn_hidden or config.dim * 4)
        self.w1 = Linear(config.dim, hidden, bias=False, rng=rng)
        self.w3 = Linear(config.dim, hidden, bias=False, rng=rng)
        self.w2 = Linear(hidden, config.dim, bias=False, rng=rng)

    def forward(self, x: Tensor) -> Tensor:
        return self.w2(self.w1(x).silu() * self.w3(x))


class Block(Module):
    """一个 Transformer 层（Pre-Norm 残差结构）。"""

    def __init__(self, config: TinyLMConfig, rng: np.random.Generator) -> None:
        super().__init__()
        self.attn_norm = RMSNorm(config.dim)
        self.attn = CausalSelfAttention(config, rng)
        self.ffn_norm = RMSNorm(config.dim)
        self.ffn = SwiGLU(config, rng)

    def forward(
        self,
        x: Tensor,
        cos: np.ndarray,
        sin: np.ndarray,
        cache: dict[str, Tensor] | None = None,
    ) -> Tensor:
        x = x + self.attn(self.attn_norm(x), cos, sin, cache)
        return x + self.ffn(self.ffn_norm(x))


class TinyLM(Module):
    """迷你自回归语言模型。"""

    def __init__(self, config: TinyLMConfig) -> None:
        super().__init__()
        self.config = config
        rng = np.random.default_rng(config.seed)
        self.tok_embeddings = Embedding(config.vocab_size, config.dim, rng=rng)
        self.layers = ModuleList([Block(config, rng) for _ in range(config.n_layers)])
        self.norm = RMSNorm(config.dim)
        self.lm_head = (
            None if config.tie_embeddings else Linear(config.dim, config.vocab_size, bias=False, rng=rng)
        )
        self._cos, self._sin = rope_tables(config.max_seq_len, config.head_dim, config.rope_base)

    # ------------------------------------------------------------------
    def forward(
        self,
        ids: np.ndarray,
        caches: list[dict[str, Tensor]] | None = None,
        offset: int = 0,
    ) -> Tensor:
        """返回形状 ``(batch, seq, vocab)`` 的 logits。"""
        ids = np.atleast_2d(np.asarray(ids, dtype=np.int64))
        seq = ids.shape[1]
        if offset + seq > self.config.max_seq_len:
            raise ValueError(
                f"序列长度 {offset + seq} 超过 max_seq_len={self.config.max_seq_len}"
            )
        cos = self._cos[offset : offset + seq]
        sin = self._sin[offset : offset + seq]

        h = self.tok_embeddings(ids)
        for index, layer in enumerate(self.layers):
            cache = caches[index] if caches is not None else None
            h = layer(h, cos, sin, cache)
        h = self.norm(h)
        if self.lm_head is not None:
            return self.lm_head(h)
        return h @ self.tok_embeddings.weight.transpose()

    def empty_caches(self) -> list[dict[str, Tensor]]:
        return [{} for _ in range(self.config.n_layers)]

    def next_token_logits(self, ids: list[int] | np.ndarray) -> np.ndarray:
        """给定前缀，返回下一个 token 的 logits（一维 numpy 数组）。"""
        with no_grad():
            logits = self.forward(np.asarray(ids, dtype=np.int64)[None, :])
        return logits.data[0, -1]

    def logprobs_for_sequence(self, ids: list[int] | np.ndarray) -> np.ndarray:
        """返回 ``ids[1:]`` 每个 token 在其前缀条件下的对数概率。"""
        ids = np.asarray(ids, dtype=np.int64)
        with no_grad():
            logits = self.forward(ids[None, :])
        log_probs = logits.log_softmax(axis=-1).data[0]
        return log_probs[np.arange(len(ids) - 1), ids[1:]]
