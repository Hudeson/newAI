from __future__ import annotations

import hashlib
from pathlib import Path

from shared.config import get_settings


class LocalObjectStorage:
    def __init__(self, root: str | Path | None = None) -> None:
        settings = get_settings()
        self.root = Path(root or settings.local_storage_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, object_key: str, data: bytes) -> str:
        path = self.root / object_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return object_key

    def exists(self, object_key: str) -> bool:
        return (self.root / object_key).is_file()

    def get_bytes(self, object_key: str) -> bytes:
        return (self.root / object_key).read_bytes()

    @staticmethod
    def sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()


def get_storage() -> LocalObjectStorage:
    return LocalObjectStorage()
