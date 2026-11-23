"""Local Synta settings."""
from __future__ import annotations

import os
from pathlib import Path

OLLAMA_MODEL = "qwen2.5-coder:3b"
REQUEST_TIMEOUT_S = 180
MAX_CODE_CHARS = 12_000

HOTKEY_CHECK = "Ctrl+Alt+F8"
HOTKEY_ASK = "Ctrl+Alt+F9"

DIAGNOSTIC_DEFAULT = 25
DIAGNOSTIC_MIN, DIAGNOSTIC_MAX = 20, 30


def get_model() -> str:
    return os.environ.get("Synta_MODEL", "").strip() or OLLAMA_MODEL


def data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "Synta"
