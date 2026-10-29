"""Rotating file + console logging.

Never log tokens, secrets, private keys, patient names, identifiers or query
strings. Log counts, resource types, status codes and request ids instead.
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"


def setup_logging(level: str = "INFO", directory: str = "logs", filename: str = "app.log",
                  max_bytes: int = 2_000_000, backup_count: int = 5, to_console: bool = True) -> None:
    root = logging.getLogger()
    if getattr(root, "_fhir_bridge_configured", False):
        return
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    formatter = logging.Formatter(_FORMAT)
    os.makedirs(directory, exist_ok=True)
    fh = RotatingFileHandler(os.path.join(directory, filename), maxBytes=max_bytes,
                             backupCount=backup_count, encoding="utf-8")
    fh.setFormatter(formatter)
    root.addHandler(fh)
    if to_console:
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        root.addHandler(ch)
    if root.level > logging.DEBUG:  # httpx logs full URLs (with query) at INFO
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
    root._fhir_bridge_configured = True  # type: ignore[attr-defined]


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
