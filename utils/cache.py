from time import time
from typing import Any, Optional
from pathlib import Path

class FileCache:
    """
    Minimal in-memory cache that matches the interface your web providers expect:
      - FileCache(Path(...), enabled=True)
      - get_or_set(namespace, key, max_age_seconds, producer_callable)
      - get(key) / set(key, value, ttl) (optional)
    It does NOT touch disk; we just keep the same name so imports succeed.
    """
    def __init__(self, _path: Path | str = ".", enabled: bool = True):
        self._enabled = enabled
        self._store: dict[str, tuple[Any, Optional[float]]] = {}

    def _now(self) -> float:
        return time()

    def get(self, full_key: str) -> Any | None:
        rec = self._store.get(full_key)
        if not rec:
            return None
        val, exp = rec
        if exp is not None and exp < self._now():
            self._store.pop(full_key, None)
            return None
        return val

    def set(self, full_key: str, value: Any, ttl: float | None):
        exp = (self._now() + ttl) if ttl else None
        self._store[full_key] = (value, exp)

    def get_or_set(self, ns: str, key: str, max_age: float, producer):
        full_key = f"{ns}:{key}"
        if not self._enabled:
            return producer()
        val = self.get(full_key)
        if val is not None:
            return val
        val = producer()
        self.set(full_key, val, max_age)
        return val

# Some code imports a module-level "cache"
cache = FileCache(".")
