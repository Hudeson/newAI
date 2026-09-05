"""实验脚本共用的小工具：分节输出、计时、随机种子。"""

from __future__ import annotations

import random
import time
from contextlib import contextmanager
from typing import Iterator

import numpy as np

__all__ = ["section", "kv", "timer", "seed_everything", "bar"]

_WIDTH = 72


def section(title: str) -> None:
    """打印一个醒目的分节标题。"""
    print()
    print("=" * _WIDTH)
    print(f" {title}")
    print("=" * _WIDTH)


def kv(label: str, value: object, width: int = 32) -> None:
    """对齐打印一行 ``键: 值``。"""
    print(f"  {label:<{width}}{value}")


def bar(value: float, width: int = 30, cap: float = 1.0) -> str:
    """用字符画一个进度条，方便在终端里直观比较数值。"""
    filled = int(round(width * min(max(value / cap, 0.0), 1.0)))
    return "█" * filled + "·" * (width - filled)


@contextmanager
def timer(label: str) -> Iterator[None]:
    start = time.perf_counter()
    yield
    print(f"  [{label} 用时 {time.perf_counter() - start:.1f}s]")


def seed_everything(seed: int = 0) -> None:
    random.seed(seed)
    np.random.seed(seed)
