"""分词器：字符级与 BPE（Byte Pair Encoding）。

大模型看不到"字"，只看到 token id。理解分词是理解大模型行为
（比如为什么它数不清字母、为什么中文更"贵"）的第一步。

:class:`BPETokenizer` 从零实现了 GPT 系列使用的 BPE 算法：

1. 预分词：按空白切成词，词内拆成字符，并在词尾加上 ``</w>`` 标记；
2. 统计相邻符号对的频次，把出现最多的一对合并成新符号；
3. 重复第 2 步直到达到目标词表大小，合并顺序即为 ``merges``；
4. 编码时按同样的顺序在每个词内部重放这些合并。
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Iterable, Sequence

__all__ = ["CharTokenizer", "BPETokenizer", "END_OF_WORD"]

END_OF_WORD = "</w>"

_DEFAULT_SPECIALS = ("<pad>", "<bos>", "<eos>", "<unk>")


class CharTokenizer:
    """字符级分词器：词表小、无 OOV，适合玩具语言模型。"""

    def __init__(self, corpus: Iterable[str], specials: Sequence[str] = _DEFAULT_SPECIALS) -> None:
        chars = sorted({ch for text in corpus for ch in text})
        self.specials = list(specials)
        self.itos = self.specials + chars
        self.stoi = {token: index for index, token in enumerate(self.itos)}

    @property
    def vocab_size(self) -> int:
        return len(self.itos)

    @property
    def pad_id(self) -> int:
        return self.stoi["<pad>"]

    @property
    def bos_id(self) -> int:
        return self.stoi["<bos>"]

    @property
    def eos_id(self) -> int:
        return self.stoi["<eos>"]

    @property
    def unk_id(self) -> int:
        return self.stoi["<unk>"]

    def encode(self, text: str, bos: bool = False, eos: bool = False) -> list[int]:
        ids = [self.stoi.get(ch, self.unk_id) for ch in text]
        if bos:
            ids = [self.bos_id] + ids
        if eos:
            ids = ids + [self.eos_id]
        return ids

    def decode(self, ids: Iterable[int], skip_special: bool = True) -> str:
        pieces = []
        for index in ids:
            token = self.itos[int(index)]
            if skip_special and token in self.specials:
                continue
            pieces.append(token)
        return "".join(pieces)


class BPETokenizer:
    """从零实现的 BPE 分词器。"""

    def __init__(
        self,
        merges: Sequence[tuple[str, str]] | None = None,
        vocab: Sequence[str] | None = None,
        specials: Sequence[str] = _DEFAULT_SPECIALS,
    ) -> None:
        self.specials = list(specials)
        self.merges: list[tuple[str, str]] = [tuple(pair) for pair in (merges or [])]
        self.ranks = {pair: rank for rank, pair in enumerate(self.merges)}
        self.itos: list[str] = list(vocab or self.specials)
        self.stoi = {token: index for index, token in enumerate(self.itos)}

    # ------------------------------------------------------------------
    # 训练
    # ------------------------------------------------------------------
    @classmethod
    def train(
        cls,
        corpus: Iterable[str],
        vocab_size: int = 256,
        specials: Sequence[str] = _DEFAULT_SPECIALS,
        min_frequency: int = 1,
    ) -> "BPETokenizer":
        """在 ``corpus`` 上学习合并规则，直到词表达到 ``vocab_size``。"""
        word_freq: Counter[tuple[str, ...]] = Counter()
        for text in corpus:
            for word in text.split():
                if word:
                    word_freq[tuple(word) + (END_OF_WORD,)] += 1

        alphabet = sorted({symbol for word in word_freq for symbol in word})
        vocab = list(specials) + alphabet
        if vocab_size < len(vocab):
            raise ValueError(f"vocab_size 至少要能容纳 {len(vocab)} 个基础符号")

        merges: list[tuple[str, str]] = []
        while len(vocab) < vocab_size:
            pair_freq: Counter[tuple[str, str]] = Counter()
            for word, freq in word_freq.items():
                for left, right in zip(word, word[1:]):
                    pair_freq[(left, right)] += freq
            if not pair_freq:
                break
            best, freq = pair_freq.most_common(1)[0]
            if freq < min_frequency:
                break
            merges.append(best)
            merged_symbol = best[0] + best[1]
            vocab.append(merged_symbol)
            word_freq = Counter(
                {_merge_word(word, best): freq for word, freq in word_freq.items()}
            )

        return cls(merges=merges, vocab=vocab, specials=specials)

    # ------------------------------------------------------------------
    # 编解码
    # ------------------------------------------------------------------
    @property
    def vocab_size(self) -> int:
        return len(self.itos)

    @property
    def unk_id(self) -> int:
        return self.stoi["<unk>"]

    def tokenize(self, text: str) -> list[str]:
        """把文本切成 BPE 子词（保留 ``</w>`` 词尾标记）。"""
        tokens: list[str] = []
        for word in text.split():
            if word:
                tokens.extend(self._bpe(tuple(word) + (END_OF_WORD,)))
        return tokens

    def _bpe(self, word: tuple[str, ...]) -> tuple[str, ...]:
        symbols = word
        while len(symbols) > 1:
            candidates = [
                (self.ranks[pair], pair)
                for pair in zip(symbols, symbols[1:])
                if pair in self.ranks
            ]
            if not candidates:
                break
            _, best = min(candidates)
            symbols = _merge_word(symbols, best)
        return symbols

    def encode(self, text: str, bos: bool = False, eos: bool = False) -> list[int]:
        ids = [self.stoi.get(token, self.unk_id) for token in self.tokenize(text)]
        if bos:
            ids = [self.stoi["<bos>"]] + ids
        if eos:
            ids = ids + [self.stoi["<eos>"]]
        return ids

    def decode(self, ids: Iterable[int], skip_special: bool = True) -> str:
        pieces: list[str] = []
        for index in ids:
            token = self.itos[int(index)]
            if skip_special and token in self.specials:
                continue
            pieces.append(token)
        text = "".join(pieces)
        return text.replace(END_OF_WORD, " ").strip()

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def save(self, path: str | Path) -> None:
        payload = {
            "specials": self.specials,
            "merges": [list(pair) for pair in self.merges],
            "vocab": self.itos,
        }
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "BPETokenizer":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            merges=[tuple(pair) for pair in payload["merges"]],
            vocab=payload["vocab"],
            specials=payload["specials"],
        )


def _merge_word(word: tuple[str, ...], pair: tuple[str, str]) -> tuple[str, ...]:
    """把 ``word`` 中所有相邻的 ``pair`` 合并为一个符号。"""
    merged: list[str] = []
    index = 0
    while index < len(word):
        if index < len(word) - 1 and (word[index], word[index + 1]) == pair:
            merged.append(pair[0] + pair[1])
            index += 2
        else:
            merged.append(word[index])
            index += 1
    return tuple(merged)
