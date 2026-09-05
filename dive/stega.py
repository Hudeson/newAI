"""大模型隐写：基于 Huffman 编码的可逆信息隐藏。

隐写与水印的目标正好相反：水印要让人**能**检测出来，隐写要让人**看不出**
文本里藏了东西，同时接收方能精确还原。

做法（对应 RNN-Stega 一类方法）：每生成一个 token 时，取模型概率最高的
``top_k`` 个候选，按概率给它们建一棵 Huffman 树；然后用待隐藏的比特流在树上
走一条路径，走到哪个叶子就输出哪个 token。高概率候选的编码更短，因此文本
读起来依然自然，而每个 token 平均能携带接近 Huffman 熵那么多比特。

解码方只要拥有**同一个模型**和**同一段前缀**，就能在每一步重建出完全相同的
Huffman 树，从观察到的 token 反推出它的编码，从而无损还原比特流。
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .decoding import SupportsLogits, softmax

__all__ = [
    "bytes_to_bits",
    "bits_to_bytes",
    "build_huffman_codes",
    "HuffmanStego",
    "StegoPayload",
]


def bytes_to_bits(data: bytes) -> list[int]:
    """字节串 -> 比特列表（高位在前）。"""
    return [(byte >> shift) & 1 for byte in data for shift in range(7, -1, -1)]


def bits_to_bytes(bits: Sequence[int]) -> bytes:
    """比特列表 -> 字节串（末尾不足 8 位的部分补零丢弃）。"""
    out = bytearray()
    for index in range(0, len(bits) - len(bits) % 8, 8):
        byte = 0
        for bit in bits[index : index + 8]:
            byte = (byte << 1) | int(bit)
        out.append(byte)
    return bytes(out)


def build_huffman_codes(tokens: Sequence[int], probs: Sequence[float]) -> dict[int, str]:
    """为候选 token 构造 Huffman 编码表，返回 ``{token: "0101"}``。

    构造过程完全确定：合并时按 ``(权重, 入队序号)`` 排序，因此编码方与
    解码方在相同输入下必然得到同一棵树。
    """
    if len(tokens) == 0:
        raise ValueError("候选集不能为空")
    if len(tokens) == 1:
        return {int(tokens[0]): ""}

    counter = 0
    heap: list[tuple[float, int, object]] = []
    for token, prob in zip(tokens, probs):
        heapq.heappush(heap, (float(prob), counter, int(token)))
        counter += 1

    while len(heap) > 1:
        left_w, _, left = heapq.heappop(heap)
        right_w, _, right = heapq.heappop(heap)
        heapq.heappush(heap, (left_w + right_w, counter, (left, right)))
        counter += 1

    codes: dict[int, str] = {}

    def walk(node: object, prefix: str) -> None:
        if isinstance(node, tuple):
            walk(node[0], prefix + "0")
            walk(node[1], prefix + "1")
        else:
            codes[int(node)] = prefix

    walk(heap[0][2], "")
    return codes


@dataclass
class StegoPayload:
    """一次隐写的产物。"""

    token_ids: list[int]
    n_bits: int
    steps: int

    @property
    def bits_per_token(self) -> float:
        return self.n_bits / self.steps if self.steps else 0.0


class HuffmanStego:
    """Huffman 隐写的编码器与解码器。"""

    def __init__(self, model: SupportsLogits, top_k: int = 8, temperature: float = 1.0) -> None:
        if top_k < 1:
            raise ValueError("top_k 至少为 1")
        self.model = model
        self.top_k = top_k
        self.temperature = temperature

    # ------------------------------------------------------------------
    def _candidates(self, ids: Sequence[int]) -> tuple[np.ndarray, np.ndarray]:
        """返回按概率降序排列的 top-k 候选及其概率。"""
        logits = np.asarray(self.model.next_token_logits(list(ids)), dtype=np.float64)
        probs = softmax(logits / self.temperature)
        k = min(self.top_k, probs.size)
        top = np.argpartition(probs, -k)[-k:]
        # 以 (概率, token id) 排序，保证编解码两端顺序完全一致
        order = sorted(top.tolist(), key=lambda t: (-probs[t], t))
        tokens = np.array(order, dtype=np.int64)
        return tokens, probs[tokens]

    # ------------------------------------------------------------------
    def encode(
        self,
        prompt_ids: Sequence[int],
        message: bytes,
        max_tokens: int = 256,
    ) -> StegoPayload:
        """把 ``message`` 嵌入到续写的 token 序列中。"""
        bits = bytes_to_bits(message)
        total_bits = len(bits)
        cursor = 0
        context = [int(t) for t in prompt_ids]
        produced: list[int] = []

        while cursor < total_bits and len(produced) < max_tokens:
            tokens, probs = self._candidates(context)
            codes = build_huffman_codes(tokens, probs)
            # 沿着比特流在树上下降，不足的位用 0 补齐（解码时按 n_bits 截断）
            remaining = bits[cursor:]
            chosen = _match_code(codes, remaining)
            code = codes[chosen]
            cursor += len(code)
            produced.append(chosen)
            context.append(chosen)

        if cursor < total_bits:
            raise ValueError(
                f"max_tokens={max_tokens} 不足以嵌入 {total_bits} 比特，已嵌入 {cursor} 比特"
            )
        return StegoPayload(token_ids=produced, n_bits=total_bits, steps=len(produced))

    # ------------------------------------------------------------------
    def decode(self, prompt_ids: Sequence[int], payload: StegoPayload) -> bytes:
        """从隐写文本中还原原始字节串。"""
        context = [int(t) for t in prompt_ids]
        bits: list[int] = []
        for token in payload.token_ids:
            tokens, probs = self._candidates(context)
            codes = build_huffman_codes(tokens, probs)
            if int(token) not in codes:
                raise ValueError("观测到的 token 不在候选集中，模型或前缀不一致")
            bits.extend(int(bit) for bit in codes[int(token)])
            context.append(int(token))
        return bits_to_bytes(bits[: payload.n_bits])


def _match_code(codes: dict[int, str], bits: Sequence[int]) -> int:
    """找出编码与 ``bits`` 前缀一致的 token；比特不够时按补零处理。"""
    bit_string = "".join(str(int(bit)) for bit in bits)
    for token, code in codes.items():
        if code == "":
            return token
        if bit_string.startswith(code):
            return token
    # 剩余比特比某些码字还短：补零后再匹配，保证一定能选出一个叶子
    padded = bit_string + "0" * max(len(code) for code in codes.values())
    for token, code in codes.items():
        if padded.startswith(code):
            return token
    raise RuntimeError("Huffman 编码表不完备")  # pragma: no cover
