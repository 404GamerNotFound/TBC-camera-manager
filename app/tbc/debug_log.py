from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime
from typing import Any


class RingBufferLogHandler(logging.Handler):
    def __init__(self, capacity: int = 600) -> None:
        super().__init__(level=logging.DEBUG)
        self.capacity = capacity
        self._entries: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "created_at": datetime.fromtimestamp(record.created).isoformat(timespec="seconds"),
                "level": record.levelname.lower(),
                "logger": record.name,
                "message": self.format(record),
            }
            with self._lock:
                self._entries.append(entry)
        except Exception:
            self.handleError(record)

    def entries(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            rows = list(self._entries)
        return rows[-max(1, min(limit, self.capacity)) :]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_HANDLER: RingBufferLogHandler | None = None


def install_debug_log() -> RingBufferLogHandler:
    global _HANDLER
    if _HANDLER is not None:
        return _HANDLER
    handler = RingBufferLogHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger("app.tbc").setLevel(logging.DEBUG)
    logging.getLogger("tbc").setLevel(logging.DEBUG)
    _HANDLER = handler
    logging.getLogger(__name__).info("Debug Log gestartet")
    return handler


def list_entries(limit: int = 200) -> list[dict[str, Any]]:
    return install_debug_log().entries(limit)


def clear_entries() -> None:
    install_debug_log().clear()
    logging.getLogger(__name__).info("Debug Log geleert")
