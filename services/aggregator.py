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


# ---------- Provider discovery ----------

@dataclass(frozen=True)
class ProviderInfo:
    key: str
    name: str
    module: str
    search: Callable[..., Any]  # may be sync or async

# --- discovery & loader (replace your current versions) ---

_DISCOVERY: Dict[str, Any] = {
    "searched_pkg": "providers",
    "discovered_modules": [],
    "loaded": [],
    "skipped": [],
    "errors": {},      # mod -> "ImportError ..." / traceback
}

def _iter_provider_modules() -> Iterable[str]:
    """
    Discover top-level 'providers' package; fall back to filesystem scan.
    Works with layout where repo root contains providers/, services/, routers/.
    """
    pkg_name = "providers"

    # Try normal package discovery
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

    # Filesystem fallback
    root = Path(__file__).resolve().parent.parent / "providers"
    if root.exists():
        project_root = root.parent  # repo root
        if str(project_root) not in sys.path:
            sys.path.append(str(project_root))
        for py in root.glob("*.py"):
            if py.name.startswith("_"):
                continue
            mod = f"providers.{py.stem}"
            _DISCOVERY["discovered_modules"].append(mod)
            yield mod

@dataclass
class Provider:
    key: str
    is_async: bool
    fn: Any
    module: str

_PROVIDERS: List[Provider] = []

def _load_providers() -> None:
    _PROVIDERS.clear()
    for mod_name in _iter_provider_modules():
        key = mod_name.split(".")[-1]
        try:
            mod = importlib.import_module(mod_name)
            fn = getattr(mod, "search", None)
            if not callable(fn):
                _DISCOVERY["skipped"].append({"module": mod_name, "reason": "no_search_function"})
                continue
            is_async = asyncio.iscoroutinefunction(fn)
            _PROVIDERS.append(Provider(key=key, is_async=is_async, fn=fn, module=mod_name))
            _DISCOVERY["loaded"].append({"key": key, "module": mod_name})
        except Exception as e:
            _DISCOVERY["errors"][mod_name] = f"{type(e).__name__}: {e}"

# Call once at import
_load_providers()

def list_provider_diagnostics() -> Dict[str, Any]:
    """Return rich discovery info for debugging on Render."""
    return {
        "providers": [{"key": p.key, "module": p.module} for p in _PROVIDERS],
        "discovery": _DISCOVERY,
    }


# ---------- Public helpers for UI ----------

def list_providers(include_mock: Optional[bool] = None) -> List[Dict[str, str]]:
    providers = _discover_providers()
    if include_mock is False:
        providers = [p for p in providers if "mock" not in p.key.lower()]
    return [{"key": p.key, "name": p.name, "module": p.module} for p in providers]


# ---------- Core fan-out (async) ----------

async def _call_provider(
    p: ProviderInfo,
    *,
    city: str,
    country: str,
    days_ahead: int,
    start_in_days: int,
    query: Optional[str],
) -> Tuple[str, List[Dict[str, Any]], Optional[str]]:
    """
    Returns (provider_key, items, error) where:
      - items is a possibly empty list
      - error is None on success or a short error string on failure
    """
    kwargs = dict(
        city=city,
        country=country,
        days_ahead=days_ahead,
        start_in_days=start_in_days,
        query=query,
    )

    try:
        # Provider search can be sync or async. Handle both.
        if inspect.iscoroutinefunction(p.search):
            chunk = await p.search(**kwargs)  # type: ignore[misc]
        else:
            chunk = await asyncio.to_thread(p.search, **kwargs)  # type: ignore[misc]
    except Exception as exc:
        return p.key, [], f"{type(exc).__name__}: {exc}"

    items: List[Dict[str, Any]] = []
    if isinstance(chunk, list):
        for e in chunk:
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
) -> Dict[str, Any]:
    providers = _discover_providers()
    if include_mock is False:
        providers = [p for p in providers if "mock" not in p.key.lower()]

    tasks = [
        _call_provider(
            p,
            city=city,
            country=country,
            days_ahead=days_ahead,
            start_in_days=start_in_days,
            query=query,
        )
        for p in providers
    ]

    results: List[Tuple[str, List[Dict[str, Any]], Optional[str]]] = []
    if tasks:
        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        for g in gathered:
            if isinstance(g, Exception):
                # Should not happen because _call_provider captures exceptions,
                # but keep a guard anyway.
                results.append(("unknown", [], f"{type(g).__name__}: {g}"))
            else:
                results.append(g)

    items: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}
    for key, chunk, err in results:
        if err:
            errors[key] = err
        items.extend(chunk)

    return {
        "count": len(items),
        "items": items,
        "providers_used": [p.key for p in providers],
        "debug": {
            "discovered": [p.key for p in _discover_providers()],
            "errors": errors,
        },
    }


# ---------- Public API ----------

async def search_events(
    *,
    city: str,
    country: str,
    days_ahead: int = 60,
    start_in_days: int = 0,
    include_mock: bool = False,
    query: Optional[str] = None,
) -> Dict[str, Any]:
    """Async façade used by FastAPI endpoints."""
    return await _search_events_async(
        city=city,
        country=country,
        days_ahead=days_ahead,
        start_in_days=start_in_days,
        include_mock=include_mock,
        query=query,
    )


def search_events_sync(
    *,
    city: str,
    country: str,
    days_ahead: int = 60,
    start_in_days: int = 0,
    include_mock: bool = False,
    query: Optional[str] = None,
) -> Dict[str, Any]:
    """Sync helper (e.g., CLI/tests). Not used by FastAPI runtime."""
    return asyncio.run(
        _search_events_async(
            city=city,
            country=country,
            days_ahead=days_ahead,
            start_in_days=start_in_days,
            include_mock=include_mock,
            query=query,
        )
    )
