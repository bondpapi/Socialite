from time import time
from typing import Any, Optional, Tuple

# simple in-memory TTL cache
_store: dict[str, Tuple[Any, Optional[float]]] = {}

def get(key: str) -> Any:
    rec = _store.get(key)
    if not rec:
        return None
    val, exp = rec
    if exp is not None and exp < time():
        _store.pop(key, None)
        return None
    return val

def set(key: str, value: Any, ttl: int = 300) -> None:
    _store[key] = (value, time() + ttl if ttl else None)

def clear() -> None:
    _store.clear()
