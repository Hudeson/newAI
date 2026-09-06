"""Hugging Face Hub / Inference integration for newAI."""

from .chat import ChatSession
from .client import HuggingFaceClient, HuggingFaceError
from .config import Settings, load_settings

__all__ = [
    "ChatSession",
    "HuggingFaceClient",
    "HuggingFaceError",
    "Settings",
    "load_settings",
]

__version__ = "0.1.0"
