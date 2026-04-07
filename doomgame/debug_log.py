from __future__ import annotations

from datetime import datetime
from pathlib import Path


LOG_PATH = Path(__file__).resolve().parent.parent / "runtime_debug.log"


def clear_debug_log() -> None:
    LOG_PATH.write_text("", encoding="utf-8")


def append_debug_log(message: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] {message}\n")
