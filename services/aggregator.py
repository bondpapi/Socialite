from __future__ import annotations

import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple, Callable

from .schemas import EventOut

@dataclass
class _CacheEntry:
    expires_at: float
    value: Dict[str, Any]

class TTLCache:
    def __init__(self, ttl_seconds: int = 60):
        self.ttl = ttl_seconds
        self._lock = threading.RLock()
        self._data: Dict[str, _CacheEntry] = {}

    def get(self, key: str) -> Dict[str, Any] | None:
        now = time.time()
        with self._lock:
            ent = self._data.get(key)
            if not ent:
                return None
            if ent.expires_at < now:
                self._data.pop(key, None)
                return None
            return ent.value

    def set(self, key: str, value: Dict[str, Any]) -> None:
        with self._lock:
            self._data[key] = _CacheEntry(time.time() + self.ttl, value)

    def clear(self):
        with self._lock:
            self._data.clear()


_CACHE_TTL = int(os.getenv("SOCIALITE_CACHE_TTL", "60"))  # seconds
_CACHE = TTLCache(ttl_seconds=_CACHE_TTL)

# ---------- provider registry ----------
# Each provider module must expose:
#   def search(city, country, start_iso, end_iso, query) -> (items: list[dict], errors: list[str])
ProviderFn = Callable[[str, str, str, str, str | None], Tuple[List[Dict[str, Any]], List[str]]]

def _try_import_provider(path: str, attr: str = "search") -> Tuple[str, ProviderFn] | None:
    try:
        mod = __import__(path, fromlist=["*"])
        fn = getattr(mod, attr)
        name = path.rsplit(".", 1)[-1]
        return name, fn
    except Exception:
        return None

def _load_providers() -> List[Tuple[str, ProviderFn]]:
    candidates = [
        "social_agent_ai.providers.bilietai",
        "social_agent_ai.providers.songkick",
        "social_agent_ai.providers.bandsintown",
        "social_agent_ai.providers.eventbrite",
        "social_agent_ai.providers.kakava", 
    ]
    loaded: List[Tuple[str, ProviderFn]] = []
    for p in candidates:
        tup = _try_import_provider(p)
        if tup:
            loaded.append(tup)
    return loaded

_PROVIDERS: List[Tuple[str, ProviderFn]] = _load_providers()

def list_providers() -> List[Dict[str, str]]:
    return [{"key": name} for name, _ in _PROVIDERS]

# ---------- date helpers ----------
def _date_range(start_in_days: int, days_ahead: int) -> Tuple[str, str]:
    # Return ISO8601 (UTC) range
    now = datetime.now(timezone.utc)
    start = now + timedelta(days=start_in_days)
    end = start + timedelta(days=days_ahead)
    # normalize to seconds for readability
    return start.replace(microsecond=0).isoformat(), end.replace(microsecond=0).isoformat()

# ---------- normalization ----------
def _to_event(item: Dict[str, Any]) -> EventOut:
    """
    Accepts a generic provider item dict and returns EventOut.
    Providers should ideally fill these keys:
      source, external_id, title, category, start_time, city, country, venue_name, min_price, currency, url
    """
    # Ensure datetime
    start_val = item.get("start_time")
    if isinstance(start_val, str):
        try:
            datetime.fromisoformat(start_val.replace("Z", "+00:00"))
        except Exception:
            pass

    return EventOut(
        id=None,
        source=item.get("source", "web"),
        external_id=str(item.get("external_id", "")),
        title=item.get("title") or "",
        category=item.get("category", "Event"),
        start_time=item.get("start_time"), 
        city=item.get("city"),
        country=item.get("country"),
        venue_name=item.get("venue_name"),
        min_price=item.get("min_price"),
        currency=item.get("currency"),
        url=item.get("url"),
    )

def _dedupe(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[Tuple[str, str]] = set()
    out: List[Dict[str, Any]] = []
    for it in items:
        key = (str(it.get("source", "")), str(it.get("external_id", "")))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out

# ---------- main search ----------
def search_events(
    *,
    city: str,
    country: str,
    days_ahead: int = 30,
    start_in_days: int = 0,
    include_mock: bool = False,
    query: str | None = None,
    max_results: int | None = None,
) -> Dict[str, Any]:
    """
    Aggregates providers in parallel and returns a dict:
      { city, country, count, items: [EventOut dicts], errors: [str] }
    """

    ck = f"{city}|{country}|{days_ahead}|{start_in_days}|{bool(include_mock)}|{query or ''}"
    cached = _CACHE.get(ck)
    if cached:
        return cached

    start_iso, end_iso = _date_range(start_in_days, days_ahead)
    items: List[Dict[str, Any]] = []
    errors: List[str] = []

    # Include mock data if requested
    if include_mock:
        items.extend([
            {
                "source": "mock",
                "external_id": "m1",
                "title": "Mock Festival",
                "category": "Festival",
                "start_time": (datetime.now(timezone.utc) + timedelta(days=7)).replace(microsecond=0).isoformat(),
                "city": city,
                "country": country,
                "venue_name": "Town Square",
                "min_price": 0.0,
                "currency": "EUR",
                "url": "https://example.com/festival",
            }
        ])


    providers = list(_PROVIDERS)
    if not providers:
        errors.append("No providers registered.")
    else:
        workers = min(8, max(2, len(providers)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(fn, city, country, start_iso, end_iso, query): name
                for name, fn in providers
            }
            for fut in as_completed(futures):
                name = futures[fut]
                try:
                    p_items, p_errs = fut.result()
                    if p_items:
                        items.extend(p_items)
                    if p_errs:
                        errors.extend([f"{name}: {e}" for e in p_errs])
                except Exception as e:
                    errors.append(f"{name}: {e!r}")


    items = _dedupe(items)
    try:
        items.sort(key=lambda x: x.get("start_time") or "")
    except Exception:
        pass

    # limit
    max_results = max_results or int(os.getenv("SOCIALITE_MAX_RESULTS", "200"))
    items = items[:max_results]


    model_items: List[EventOut] = []
    for it in items:
        try:
            model_items.append(_to_event(it))
        except Exception as e:
            errors.append(f"normalize: {e!r}")

    result = {
        "city": city,
        "country": country,
        "count": len(model_items),
        "items": [m.dict() for m in model_items],
        "errors": errors,
    }

    _CACHE.set(ck, result)
    return result
