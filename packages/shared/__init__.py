"""Shared settings, errors, logging, and DB base for the KB agent."""

from shared.config import get_settings
from shared.errors import AppError, ErrorCode
from shared.logging import configure_logging, get_logger

__all__ = [
    "AppError",
    "ErrorCode",
    "configure_logging",
    "get_logger",
    "get_settings",
]
