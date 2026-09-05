"""实验用的合成任务与训练/评测工具。

两个任务贯穿多个章节：

* :func:`build_sentiment_task`：中文情感分类，用于第 1 章的指令微调与 LoRA；
* :class:`ArithmeticTask`：两位数加法，用于第 2 章（思维链、自洽投票）
  与第 4 章（推理蒸馏）。它的关键性质是**可以程序化地生成正确的推理过程**，
  于是我们能在完全离线的条件下研究"有没有推理过程"带来的差异。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np

from dive.decoding import SamplingConfig, generate
from dive.tokenizer import CharTokenizer
from dive.training import TrainConfig, sft_batch, train_causal_lm
from dive.transformer import TinyLM, TinyLMConfig

__all__ = ["SFTTask", "build_sentiment_task", "ArithmeticTask", "train_on_task"]


@dataclass
class SFTTask:
    """一个已经切分好、编码好的指令微调任务。"""

    name: str
    tokenizer: CharTokenizer
    train_examples: list[tuple[str, str]]
    test_examples: list[tuple[str, str]]
    max_new_tokens: int
    max_seq_len: int = 64

    def batches(self, batch_size: int = 32) -> list[tuple[np.ndarray, np.ndarray]]:
        sequences, prompt_lengths = [], []
        for prompt, answer in self.train_examples:
            prompt_ids = self.tokenizer.encode(prompt, bos=True)
            sequences.append(prompt_ids + self.tokenizer.encode(answer, eos=True))
            prompt_lengths.append(len(prompt_ids))
        return [
            sft_batch(
                sequences[i : i + batch_size],
                prompt_lengths[i : i + batch_size],
                self.tokenizer.pad_id,
            )
            for i in range(0, len(sequences), batch_size)
        ]

    def predict(
        self,
        model: TinyLM,
        prompt: str,
        temperature: float = 0.0,
        rng: np.random.Generator | None = None,
    ) -> str:
        ids = self.tokenizer.encode(prompt, bos=True)
        out = generate(
            model,
            ids,
            max_new_tokens=self.max_new_tokens,
            config=SamplingConfig(temperature=temperature),
            stop_ids=[self.tokenizer.eos_id],
            rng=rng,
        )
        return self.tokenizer.decode(out)

    def accuracy(
        self,
        model: TinyLM,
        examples: Sequence[tuple[str, str]] | None = None,
        temperature: float = 0.0,
        match: Callable[[str, str], bool] | None = None,
        rng: np.random.Generator | None = None,
    ) -> float:
        examples = examples if examples is not None else self.test_examples
        match = match or (lambda pred, gold: pred.strip() == gold.strip())
        correct = sum(
            1
            for prompt, gold in examples
            if match(self.predict(model, prompt, temperature=temperature, rng=rng), gold)
        )
        return correct / len(examples)


# ----------------------------------------------------------------------
# 任务一：情感分类
# ----------------------------------------------------------------------
_SUBJECTS = ["这部电影", "这家餐厅", "这本书", "这个游戏"]
_DEGREES = ["真的", "特别", "非常"]
_POSITIVE = ["精彩", "出色", "惊艳"]
_NEGATIVE = ["无聊", "糟糕", "乏味"]

_HELD_OUT_PAIRS = {("这本书", "惊艳"), ("这个游戏", "糟糕"), ("这家餐厅", "乏味")}


def build_sentiment_task() -> SFTTask:
    """构造情感分类任务。

    测试集刻意由**训练中从未同时出现过的"主语 + 情感词"组合**构成，
    因此高准确率只能来自组合泛化，而不是死记硬背。
    """
    examples: list[tuple[tuple[str, str], str, str]] = []
    for subject in _SUBJECTS:
        for degree in _DEGREES:
            for word in _POSITIVE + _NEGATIVE:
                prompt = f"评论:{subject}{degree}{word}\n情感:"
                label = "正面" if word in _POSITIVE else "负面"
                examples.append(((subject, word), prompt, label))

    train = [(p, l) for key, p, l in examples if key not in _HELD_OUT_PAIRS]
    test = [(p, l) for key, p, l in examples if key in _HELD_OUT_PAIRS]

    tokenizer = CharTokenizer([p + l for _, p, l in examples])
    return SFTTask(
        name="情感分类",
        tokenizer=tokenizer,
        train_examples=train,
        test_examples=test,
        max_new_tokens=3,
        max_seq_len=48,
    )


# ----------------------------------------------------------------------
# 任务二：两位数加法（可生成推理过程）
# ----------------------------------------------------------------------
@dataclass
class ArithmeticTask:
    """多位数加法，支持三种"思考长度"的输出格式。

    ============  ======================================================
    ``style``     目标输出
    ============  ======================================================
    ``direct``    直接给答案：``0579``
    ``reverse``   先倒序写出各位结果当草稿，再给答案：``[975]0579``
    ``cot``       逐位列出加法与进位，再给答案：``[3+6=9c0;2+5=7c0;1+4=5c0]0579``
    ============  ======================================================

    三者的信息量完全相同，区别只在于模型被允许用多少个 token 来完成计算。
    """

    n_train: int = 1200
    n_test: int = 200
    seed: int = 0
    style: str = "cot"
    digits: int = 2

    train_pairs: list[tuple[int, int]] = field(default_factory=list, repr=False)
    test_pairs: list[tuple[int, int]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self.style not in {"direct", "reverse", "cot"}:
            raise ValueError(f"未知的 style：{self.style}")
        limit = 10**self.digits
        rng = np.random.default_rng(self.seed)
        total = self.n_train + self.n_test
        if total > limit * limit:
            raise ValueError("题目数量超过了该位数下的所有组合")
        # 位数大时全枚举不现实，改为不放回地随机抽取
        flat = rng.choice(limit * limit, size=total, replace=False)
        pairs = [(int(v // limit), int(v % limit)) for v in flat]
        self.train_pairs = pairs[: self.n_train]
        self.test_pairs = pairs[self.n_train :]

    # ------------------------------------------------------------------
    def prompt(self, a: int, b: int) -> str:
        return f"{a:0{self.digits}d}+{b:0{self.digits}d}="

    def gold(self, a: int, b: int) -> str:
        return f"{a + b:0{self.digits + 1}d}"

    def reasoning(self, a: int, b: int) -> str:
        """程序化生成「教师」的推理过程：从个位开始逐位相加并记录进位。"""
        steps = []
        carry = 0
        for position in range(self.digits):
            left = (a // 10**position) % 10
            right = (b // 10**position) % 10
            total = left + right + carry
            steps.append(f"{left}+{right}{f'+{carry}' if carry else ''}={total % 10}c{total // 10}")
            carry = total // 10
        return "[" + ";".join(steps) + "]"

    def reverse_draft(self, a: int, b: int) -> str:
        """倒序草稿：把答案按从低位到高位的顺序先写一遍。"""
        return "[" + self.gold(a, b)[::-1] + "]"

    def target(self, a: int, b: int) -> str:
        if self.style == "direct":
            return self.gold(a, b)
        if self.style == "reverse":
            return self.reverse_draft(a, b) + self.gold(a, b)
        return self.reasoning(a, b) + self.gold(a, b)

    @property
    def target_length(self) -> int:
        a, b = self.train_pairs[0] if self.train_pairs else (0, 0)
        return len(self.target(a, b))

    # ------------------------------------------------------------------
    def to_sft_task(self, extra_examples: Sequence[tuple[str, str]] = ()) -> SFTTask:
        train = [(self.prompt(a, b), self.target(a, b)) for a, b in self.train_pairs]
        train.extend(extra_examples)
        test = [(self.prompt(a, b), self.gold(a, b)) for a, b in self.test_pairs]
        charset = [p + t for p, t in train] + [p + t for p, t in test]
        longest = max(len(p) + len(t) for p, t in train) + 4
        return SFTTask(
            name=f"{self.digits}位数加法({self.style})",
            tokenizer=CharTokenizer(charset),
            train_examples=train,
            test_examples=test,
            max_new_tokens=max(len(t) for _, t in train) + 2,
            max_seq_len=max(longest, 48),
        )

    def answer_matches(self, prediction: str, gold: str) -> bool:
        """只看末尾的答案位，忽略中间推理过程。"""
        digits = "".join(ch for ch in prediction if ch.isdigit())
        width = self.digits + 1
        return digits[-width:] == gold if len(digits) >= width else False


def train_on_task(
    task: SFTTask,
    dim: int = 96,
    n_layers: int = 3,
    n_heads: int = 4,
    epochs: int = 30,
    lr: float = 3e-3,
    batch_size: int = 64,
    seed: int = 0,
    verbose: bool = True,
    log_every: int = 10,
) -> TinyLM:
    """在任务上从零训练一个 TinyLM。"""
    config = TinyLMConfig(
        vocab_size=task.tokenizer.vocab_size,
        dim=dim,
        n_layers=n_layers,
        n_heads=n_heads,
        max_seq_len=task.max_seq_len,
        seed=seed,
    )
    model = TinyLM(config)
    train_causal_lm(
        model,
        task.batches(batch_size=batch_size),
        TrainConfig(epochs=epochs, lr=lr, seed=seed, verbose=verbose, log_every=log_every),
    )
    return model
