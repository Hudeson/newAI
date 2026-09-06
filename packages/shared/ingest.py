from __future__ import annotations

import hashlib
import math
import re


_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text) if t.strip()]


def chunk_text(text: str, *, chunk_size: int = 400, overlap: int = 60) -> list[str]:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []
    # Prefer paragraph splits, then hard window by characters (proxy for tokens).
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    units: list[str] = []
    for para in paragraphs:
        if len(para) <= chunk_size:
            units.append(para)
            continue
        start = 0
        while start < len(para):
            end = min(len(para), start + chunk_size)
            units.append(para[start:end])
            if end >= len(para):
                break
            start = max(end - overlap, start + 1)
    # Merge tiny leftovers
    merged: list[str] = []
    buf = ""
    for u in units:
        if not buf:
            buf = u
        elif len(buf) + 1 + len(u) <= chunk_size:
            buf = f"{buf}\n{u}"
        else:
            merged.append(buf)
            buf = u
    if buf:
        merged.append(buf)
    return merged


def embed_text(text: str, *, dims: int = 64) -> list[float]:
    """Deterministic bag-of-tokens hashing embedder (no external model required)."""
    vec = [0.0] * dims
    tokens = tokenize(text)
    if not tokens:
        return vec
    for tok in tokens:
        h = hashlib.sha256(tok.encode("utf-8")).digest()
        idx = int.from_bytes(h[:4], "big") % dims
        sign = 1.0 if h[4] % 2 == 0 else -1.0
        vec[idx] += sign
    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True))
