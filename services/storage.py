from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


def _default_db_path() -> Path:
    root = Path(os.environ.get("SOCIALITE_DB_DIR", Path.home() / ".socialite"))
    root.mkdir(parents=True, exist_ok=True)
    return root / "saved.json"


class SavedStore:
    """
    A tiny, threadsafe JSON store for saved events.
    Schema:
      {
        "items": [
          { "id": "<stable-hash>", "saved_at": 1700000000, "data": {...event...} }
        ]
      }
    """
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else _default_db_path()
        self._lock = threading.Lock()
        if not self.path.exists():
            self._write({"items": []})

    # ---------- internal IO ----------

    def _read(self) -> Dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8")
            return json.loads(raw) if raw else {"items": []}
        except FileNotFoundError:
            return {"items": []}

    def _write(self, obj: Dict[str, Any]) -> None:
        self.path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- public API ----------

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._read().get("items", []))

    def _index_of(self, event_id: str) -> int:
        data = self._read()
        for i, row in enumerate(data.get("items", [])):
            if row.get("id") == event_id:
                return i
        return -1

    def upsert(self, event_id: str, event_data: Dict[str, Any]) -> None:
        with self._lock:
            data = self._read()
            idx = self._index_of(event_id)
            row = {"id": event_id, "saved_at": int(time.time()), "data": event_data}
            if idx >= 0:
                data["items"][idx] = row
            else:
                data.setdefault("items", []).append(row)
            self._write(data)

    def remove(self, event_id: str) -> bool:
        with self._lock:
            data = self._read()
            before = len(data.get("items", []))
            data["items"] = [r for r in data.get("items", []) if r.get("id") != event_id]
            self._write(data)
            return len(data["items"]) < before

    def is_saved(self, event_id: str) -> bool:
        return self._index_of(event_id) >= 0


# convenience singleton
_store_singleton: Optional[SavedStore] = None

def get_store() -> SavedStore:
    global _store_singleton
    if _store_singleton is None:
        _store_singleton = SavedStore()
    return _store_singleton
