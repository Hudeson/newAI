"""一个"槽位语言"语料，以及在其上训练词级语言模型的工具。

水印（第 5 章）、越狱防御中的困惑度过滤（第 6 章）和隐写（第 7 章）都需要
一个满足两个条件的模型：

1. **有确定的结构**——否则困惑度过滤无从谈起；
2. **每一步都有真实的不确定性**——否则水印无处可藏、隐写无容量可用。

真实大模型正是如此：语法几乎确定，用词有很大自由。这里用一个"槽位语言"
来复现这种性质：句子由固定顺序的槽位构成（时间→主体→地点→动作→修饰→
对象→结尾），但每个槽位有十几种可选的词。于是模型能学会**顺序**，
却无法预测**选词**，每个位置都保留约 2.5 nats 的熵。

注意：字符级语料在这里是行不通的。模板化文本被字符模型拟合后困惑度会低到
1.5 左右，几乎没有熵，δ=2 的水印偏置根本推不动分布——这本身就是水印方法
的一个真实限制：**低熵文本无法承载水印**。
"""

from __future__ import annotations

import numpy as np

from dive.decoding import softmax
from dive.tokenizer import WordTokenizer
from dive.training import TrainConfig, causal_batch, train_causal_lm
from dive.transformer import TinyLM, TinyLMConfig

__all__ = ["SLOTS", "build_slot_corpus", "train_slot_lm", "mean_entropy"]

SLOTS: list[list[str]] = [
    ["今天", "昨天", "上周", "月初", "去年", "清晨", "傍晚", "刚才", "年底", "上月"],
    ["研究员", "工程师", "同学", "实习生", "团队", "老师", "作者", "评审", "用户", "客户"],
    ["在实验室", "在会议室", "在机房", "在教室", "在工位", "在食堂", "在图书馆", "在园区"],
    ["训练", "部署", "评测", "微调", "压缩", "重构", "复现", "调试", "标注", "发布"],
    ["更快", "更小", "更稳", "更强", "更省", "更准", "更轻", "更好"],
    ["语言模型", "多模态模型", "翻译系统", "推荐系统", "对话助手", "检索引擎", "问答系统", "编码器"],
    ["，效果不错。", "，还在调参。", "，准备开源。", "，写进了报告。", "，需要复测。", "，指标持平。"],
]
"""槽位顺序固定，槽内取值自由——模型学得会前者，猜不到后者。"""


def build_slot_corpus(
    n_documents: int = 320,
    clauses_per_document: int = 8,
    seed: int = 0,
    slot_width: int | None = None,
) -> list[list[str]]:
    """生成若干文档，每篇由多个分句拼接而成。

    ``slot_width`` 限制每个槽位可选词的数量，用来直接控制语料的熵：
    取 1 时语料退化成一句话不断重复，模型输出完全确定。
    """
    rng = np.random.default_rng(seed)
    slots = [slot[:slot_width] if slot_width else slot for slot in SLOTS]
    documents: list[list[str]] = []
    for _ in range(n_documents):
        tokens: list[str] = []
        for _ in range(clauses_per_document):
            tokens.extend(str(rng.choice(slot)) for slot in slots)
        documents.append(tokens)
    return documents


def train_slot_lm(
    n_documents: int = 320,
    clauses_per_document: int = 8,
    epochs: int = 12,
    dim: int = 96,
    n_layers: int = 2,
    batch_size: int = 32,
    lr: float = 3e-3,
    seed: int = 0,
    verbose: bool = True,
    slot_width: int | None = None,
) -> tuple[WordTokenizer, TinyLM, list[list[str]]]:
    """在槽位语料上训练一个词级语言模型。"""
    documents = build_slot_corpus(
        n_documents, clauses_per_document, seed=seed, slot_width=slot_width
    )
    vocabulary = [word for slot in SLOTS for word in slot]
    tokenizer = WordTokenizer(vocabulary)

    sequences = [tokenizer.encode(document, bos=True, eos=True) for document in documents]
    batches = [
        causal_batch(sequences[i : i + batch_size], tokenizer.pad_id)
        for i in range(0, len(sequences), batch_size)
    ]

    max_len = max(len(seq) for seq in sequences)
    model = TinyLM(
        TinyLMConfig(
            vocab_size=tokenizer.vocab_size,
            dim=dim,
            n_layers=n_layers,
            n_heads=4,
            max_seq_len=max_len + 128,
            seed=seed,
        )
    )
    train_causal_lm(
        model,
        batches,
        TrainConfig(epochs=epochs, lr=lr, seed=seed, verbose=verbose, log_every=max(1, epochs // 3)),
    )
    return tokenizer, model, documents


def mean_entropy(model: TinyLM, ids: list[int]) -> float:
    """给定序列，计算模型在每一步预测分布上的平均熵（nats）。"""
    entropies = []
    for position in range(1, len(ids)):
        probs = softmax(model.next_token_logits(ids[:position]))
        entropies.append(float(-(probs * np.log(probs + 1e-12)).sum()))
    return float(np.mean(entropies))
