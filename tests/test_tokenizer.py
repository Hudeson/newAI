"""分词器：字符级、词级与从零训练的 BPE。"""

from __future__ import annotations

import pytest

from dive.tokenizer import END_OF_WORD, BPETokenizer, CharTokenizer, WordTokenizer

CORPUS = [
    "low low low low low",
    "lower lower newest newest newest",
    "newest newest newest widest widest widest",
]


# ----------------------------------------------------------------------
# 字符级
# ----------------------------------------------------------------------
def test_char_tokenizer_roundtrip():
    tokenizer = CharTokenizer(["大模型很有意思"])
    ids = tokenizer.encode("大模型")
    assert tokenizer.decode(ids) == "大模型"


def test_char_tokenizer_specials_come_first():
    tokenizer = CharTokenizer(["abc"])
    assert tokenizer.itos[:4] == ["<pad>", "<bos>", "<eos>", "<unk>"]
    assert tokenizer.vocab_size == 4 + 3
    assert (tokenizer.pad_id, tokenizer.bos_id, tokenizer.eos_id, tokenizer.unk_id) == (0, 1, 2, 3)


def test_char_tokenizer_bos_eos_and_skip_special():
    tokenizer = CharTokenizer(["abc"])
    ids = tokenizer.encode("ab", bos=True, eos=True)
    assert ids[0] == tokenizer.bos_id and ids[-1] == tokenizer.eos_id
    assert tokenizer.decode(ids) == "ab"
    assert tokenizer.decode(ids, skip_special=False) == "<bos>ab<eos>"


def test_char_tokenizer_maps_unknown_to_unk():
    tokenizer = CharTokenizer(["abc"])
    assert tokenizer.encode("z") == [tokenizer.unk_id]


# ----------------------------------------------------------------------
# 词级
# ----------------------------------------------------------------------
def test_word_tokenizer_roundtrip_with_separator():
    words = ["你好", "世界", "大模型"]
    tokenizer = WordTokenizer(words)
    ids = tokenizer.encode(["你好", "大模型"])
    assert tokenizer.decode(ids, sep=" ") == "你好 大模型"


def test_word_tokenizer_vocab_is_sorted_and_deduplicated():
    tokenizer = WordTokenizer(["b", "a", "b"])
    assert tokenizer.itos[4:] == ["a", "b"]
    assert tokenizer.vocab_size == 6


def test_word_tokenizer_unknown_word():
    tokenizer = WordTokenizer(["a"])
    assert tokenizer.encode(["未登录词"]) == [tokenizer.unk_id]


# ----------------------------------------------------------------------
# BPE
# ----------------------------------------------------------------------
def test_bpe_train_reaches_target_vocab_size():
    tokenizer = BPETokenizer.train(CORPUS, vocab_size=30)
    assert tokenizer.vocab_size == 30
    assert len(tokenizer.merges) > 0
    # 词表 = 特殊符号 + 基础字符 + 合并出来的新符号
    assert tokenizer.vocab_size == 4 + len({ch for text in CORPUS for ch in text if ch != " "}) + 1 + len(
        tokenizer.merges
    )


def test_bpe_first_merge_is_the_most_frequent_pair():
    """``est</w>`` 相关的对在语料里最高频，第一次合并必然落在其中。"""
    tokenizer = BPETokenizer.train(CORPUS, vocab_size=30)
    assert tokenizer.merges[0] in {("e", "s"), ("s", "t"), ("t", END_OF_WORD)}


def test_bpe_roundtrip():
    tokenizer = BPETokenizer.train(CORPUS, vocab_size=30)
    for text in ["low lower newest", "widest low", "newest newest"]:
        assert tokenizer.decode(tokenizer.encode(text)) == text


def test_bpe_merges_reduce_token_count():
    text = "newest newest newest"
    coarse = BPETokenizer.train(CORPUS, vocab_size=18)
    fine = BPETokenizer.train(CORPUS, vocab_size=30)
    assert len(fine.encode(text)) < len(coarse.encode(text))


def test_bpe_tokenize_keeps_end_of_word_marker():
    tokenizer = BPETokenizer.train(CORPUS, vocab_size=30)
    tokens = tokenizer.tokenize("low")
    assert "".join(tokens) == "low" + END_OF_WORD


def test_bpe_unknown_symbol_maps_to_unk():
    tokenizer = BPETokenizer.train(CORPUS, vocab_size=30)
    assert tokenizer.unk_id in tokenizer.encode("字")


def test_bpe_bos_eos():
    tokenizer = BPETokenizer.train(CORPUS, vocab_size=30)
    ids = tokenizer.encode("low", bos=True, eos=True)
    assert ids[0] == tokenizer.stoi["<bos>"] and ids[-1] == tokenizer.stoi["<eos>"]
    assert tokenizer.decode(ids) == "low"


def test_bpe_rejects_too_small_vocab():
    with pytest.raises(ValueError):
        BPETokenizer.train(CORPUS, vocab_size=3)


def test_bpe_training_is_deterministic():
    first = BPETokenizer.train(CORPUS, vocab_size=30)
    second = BPETokenizer.train(CORPUS, vocab_size=30)
    assert first.merges == second.merges
    assert first.itos == second.itos


def test_bpe_save_load_roundtrip(tmp_path):
    tokenizer = BPETokenizer.train(CORPUS, vocab_size=30)
    path = tmp_path / "bpe.json"
    tokenizer.save(path)
    restored = BPETokenizer.load(path)
    assert restored.merges == tokenizer.merges
    assert restored.itos == tokenizer.itos
    assert restored.encode("low lower") == tokenizer.encode("low lower")


def test_bpe_min_frequency_stops_early():
    tokenizer = BPETokenizer.train(CORPUS, vocab_size=200, min_frequency=1000)
    assert tokenizer.merges == []
