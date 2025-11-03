# services/aggregator.py
from __future__ import annotations

import asyncio
import importlib
import inspect
import pkgutil
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

# ---------- Provider dataclass ----------

@dataclass
class Provider:
    key: str
    module: str
    fn: Callable[..., Any]
    is_async: bool
    name: str = ""

# discovery bookkeeping
_DISCOVERY: Dict[str, Any] = {
    "discovered_modules": [],
    "loaded": [],
    "skipped": [],
    "errors": {},
}
_PROVIDERS: List[Provider] = []

# ---------- Module discovery ----------

def _iter_provider_modules() -> Iterable[str]:
    pkg_name = "providers"
    try:
        pkg = importlib.import_module(pkg_name)
        for m in pkgutil.iter_modules(pkg.__path__, pkg_name + "."):  # type: ignore[attr-defined]
            leaf = m.name.rsplit(".", 1)[-1]
            if leaf.startswith("_"):
                continue
            _DISCOVERY["discovered_modules"].append(m.name)
            yield m.name
        return
    except Exception as e:
        _DISCOVERY["errors"]["__package__"] = f"{type(e).__name__}: {e}"

    # filesystem fallback
    root = Path(__file__).resolve().parent.parent / "providers"
    if root.exists():
        project_root = root.parent
        if str(project_root) not in sys.path:
            sys.path.append(str(project_root))
        for py in root.glob("*.py"):
            if py.name.startswith("_"):
                continue
            mod = f"providers.{py.stem}"
            _DISCOVERY["discovered_modules"].append(mod)
            yield mod

# ---------- Loader ----------

def _load_providers(mod_names: Optional[List[str]] = None) -> None:
    _PROVIDERS.clear()
    _DISCOVERY["loaded"].clear()
    _DISCOVERY["skipped"].clear()
    _DISCOVERY["errors"].clear()

    if mod_names is None:
        mod_names = list(_iter_provider_modules())

    for mod_name in mod_names:
        key = mod_name.split(".")[-1]
        try:
            mod = importlib.import_module(mod_name)

            # 1) module-level function 'search'
            fn = getattr(mod, "search", None)
            if callable(fn):
                prov = Provider(
                    key=key,
                    module=mod_name,
                    fn=fn,
                    is_async=asyncio.iscoroutinefunction(fn),
                    name=getattr(mod, "NAME", key),
                )
                _PROVIDERS.append(prov)
                _DISCOVERY["loaded"].append(
                    {"key": key, "module": mod_name, "via": "function"}
                )
                continue

            # 2) Provider class with .search()
            ProvCls = getattr(mod, "Provider", None)
            if ProvCls is not None and inspect.isclass(ProvCls):
                try:
                    inst = ProvCls()
                    sfn = getattr(inst, "search", None)
                    if callable(sfn):
                        def _call(**kw):
                            return sfn(**kw)
                        # expose real target for inspect.signature
                        try:
                            _call.__wrapped__ = sfn  # type: ignore[attr-defined]
                        except Exception:
                            pass
                        prov = Provider(
                            key=key,
                            module=mod_name,
                            fn=_call,
                            is_async=asyncio.iscoroutinefunction(sfn),
                            name=getattr(inst, "name", key),
                        )
                        _PROVIDERS.append(prov)
                        _DISCOVERY["loaded"].append(
                            {"key": key, "module": mod_name, "via": "Provider"}
                        )
                        continue
                except Exception as e:
                    _DISCOVERY["errors"][mod_name] = f"Provider() init failed: {e}"

            # 3) factory get_provider()
            getp = getattr(mod, "get_provider", None)
            if callable(getp):
                try:
                    inst = getp()
                    sfn = getattr(inst, "search", None)
                    if callable(sfn):
                        def _call(**kw):
                            return sfn(**kw)
                        try:
                            _call.__wrapped__ = sfn  # type: ignore[attr-defined]
                        except Exception:
                            pass
                        prov = Provider(
                            key=key,
                            module=mod_name,
                            fn=_call,
                            is_async=asyncio.iscoroutinefunction(sfn),
                            name=getattr(inst, "name", key),
                        )
                        _PROVIDERS.append(prov)
                        _DISCOVERY["loaded"].append(
                            {"key": key, "module": mod_name, "via": "get_provider"}
                        )
                        continue
                except Exception as e:
                    _DISCOVERY["errors"][mod_name] = f"get_provider() failed: {e}"

            _DISCOVERY["skipped"].append(
                {"module": mod_name, "reason": "no_search_function"}
            )
        except Exception as e:
            _DISCOVERY["errors"][mod_name] = f"{type(e).__name__}: {e}"

# initial load
_load_providers()

# ---------- Diagnostics / helpers ----------

def list_provider_diagnostics() -> Dict[str, Any]:
    return {
        "providers": [
            {"key": p.key, "module": p.module, "is_async": p.is_async, "name": p.name}
            for p in _PROVIDERS
        ],
        "discovery": _DISCOVERY,
    }

def _discover_providers() -> List[Provider]:
    return list(_PROVIDERS)

def list_providers(include_mock: Optional[bool] = None) -> List[Dict[str, str]]:
    providers = _discover_providers()
    if include_mock is False:
        providers = [p for p in providers if "mock" not in p.key.lower()]
    return [{"key": p.key, "name": p.name or p.key, "module": p.module} for p in providers]

# ---------- Fan-out utilities ----------

def _date_window(start_in_days: int, days_ahead: int) -> Tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    start = (now + timedelta(days=start_in_days)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = (now + timedelta(days=start_in_days + days_ahead)).replace(hour=23, minute=59, second=59, microsecond=0)
    return start, end

def _filter_kwargs(func, **kw):
    """
    Pass only params the provider function declares explicitly.
    - unwrap __wrapped__ if present
    - ignore VAR_POSITIONAL / VAR_KEYWORD
    - ALWAYS drop limit/offset unless explicitly present in signature
    """
    try:
        target = getattr(func, "__wrapped__", func)  # unwrap our wrapper
        sig = inspect.signature(target)
        explicit_params = {
            name
            for name, p in sig.parameters.items()
            if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        }
        # Only forward explicitly-declared params
        filtered = {k: v for k, v in kw.items() if k in explicit_params}
        return filtered
    except Exception:
        # Conservative fallback: the safest common set
        common = ("city", "country", "start", "end", "query")
        return {k: v for k, v in kw.items() if k in common}

def _dedupe(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, out = set(), []
    for e in items:
        key = e.get("url") or (
            (e.get("title") or "").strip().lower(),
            e.get("start_time"),
            (e.get("venue_name") or "").strip().lower(),
            (e.get("city") or "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out

def _sort_key(e: Dict[str, Any]):
    start = e.get("start_time") or "9999-12-31T00:00:00Z"
    title = (e.get("title") or "").lower()
    return (start, title)

# ---------- Core fan-out ----------

async def _call_provider(
    p: Provider,
    *,
    city: str,
    country: str,
    start: datetime,
    end: datetime,
    query: Optional[str],
    limit: int,
    offset: int,
) -> Tuple[str, List[Dict[str, Any]], Optional[str]]:
    raw_kwargs = dict(
        city=city, country=country, start=start, end=end,
        query=query, limit=limit, offset=offset
    )
    kwargs = _filter_kwargs(p.fn, **raw_kwargs)
    try:
        if p.is_async:
            chunk = await p.fn(**kwargs)  # type: ignore[misc]
        else:
            chunk = await asyncio.to_thread(p.fn, **kwargs)  # type: ignore[misc]
    except Exception as exc:
        return p.key, [], f"{type(exc).__name__}: {exc}"

    items: List[Dict[str, Any]] = []
    if isinstance(chunk, dict) and "items" in chunk:
        chunk = chunk.get("items") or []
    if isinstance(chunk, list):
        for e in chunk:
            if isinstance(e, dict):
                e.setdefault("source", p.key)
                items.append(e)
    return p.key, items, None

async def _search_events_async(
    *,
    city: str,
    country: str,
    days_ahead: int = 60,
    start_in_days: int = 0,
    include_mock: bool = False,
    query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    providers = _discover_providers()
    if include_mock is False:
        providers = [p for p in providers if "mock" not in p.key.lower()]

    start_dt, end_dt = _date_window(start_in_days, days_ahead)
    per_provider = min(50, max(10, limit))

    tasks = [
        _call_provider(
            p,
            city=city,
            country=country,
            start=start_dt,
            end=end_dt,
            query=query,
            limit=per_provider,
            offset=0,
        )
        for p in providers
    ]

    results: List[Tuple[str, List[Dict[str, Any]], Optional[str]]] = []
    if tasks:
        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        for g in gathered:
            if isinstance(g, Exception):
                results.append(("unknown", [], f"{type(g).__name__}: {g}"))
            else:
                results.append(g)

    items: List[Dict[str, Any]] = []
    provider_errors: Dict[str, str] = {}
    for key, chunk, err in results:
        if err:
            provider_errors[key] = err
        items.extend(chunk)

    items = _dedupe(items)
    items.sort(key=_sort_key)
    total = len(items)
    page = items[offset : offset + limit]

    return {
        "count": len(page),
        "total": total,
        "items": page,
        "providers_used": [p.key for p in providers],
        "debug": {
            "provider_errors": provider_errors,
            "window": {"start": start_dt.isoformat(), "end": end_dt.isoformat()},
            "discovered": [p.key for p in _discover_providers()],
            "limit": limit,
            "offset": offset,
        },
    }

# Public API

async def search_events(
    *,
    city: str,
    country: str,
    days_ahead: int = 60,
    start_in_days: int = 0,
    include_mock: bool = False,
    query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    return await _search_events_async(
        city=city,
        country=country,
        days_ahead=days_ahead,
        start_in_days=start_in_days,
        include_mock=include_mock,
        query=query,
        limit=limit,
        offset=offset,
    )

def search_events_sync(
    *,
    city: str,
    country: str,
    days_ahead: int = 60,
    start_in_days: int = 0,
    include_mock: bool = False,
    query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    return asyncio.run(
        _search_events_async(
            city=city,
            country=country,
            days_ahead=days_ahead,
            start_in_days=start_in_days,
            include_mock=include_mock,
            query=query,
            limit=limit,
            offset=offset,
        )
    )
