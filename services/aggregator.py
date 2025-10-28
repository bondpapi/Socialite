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

def _iter_provider_modules() -> Iterable[str]:
    """
    Discover top-level package 'providers' (sibling of 'services').
    Falls back to a filesystem scan under ./providers if import fails.
    """
    pkg_name = "providers"

    # Try normal package discovery
    try:
        pkg = importlib.import_module(pkg_name)
        for m in pkgutil.iter_modules(pkg.__path__, pkg_name + "."):  # type: ignore[attr-defined]
            leaf = m.name.rsplit(".", 1)[-1]
            if not leaf.startswith("_"):
                yield m.name
        return
    except ModuleNotFoundError as e:
        # continue to filesystem fallback
        pass
    except Exception:
        # continue to filesystem fallback
        pass

    # Filesystem fallback (works if PYTHONPATH is odd)
    root = Path(__file__).resolve().parent.parent / "providers"
    if root.exists():
        project_root = root.parent  # repo root that has providers/, services/
        if str(project_root) not in sys.path:
            sys.path.append(str(project_root))
        for py in root.glob("*.py"):
            if not py.name.startswith("_"):
                yield f"{pkg_name}.{py.stem}"


def _load_provider(module_name: str) -> Optional[ProviderInfo]:
    try:
        mod = importlib.import_module(module_name)
    except Exception:
        return None

    search = getattr(mod, "search", None)
    if not callable(search):
        return None
    name = getattr(mod, "NAME", module_name.rsplit(".", 1)[-1].title())
    key = getattr(mod, "KEY", module_name.rsplit(".", 1)[-1])
    return ProviderInfo(key=key, name=name, module=module_name, search=search)


def _discover_providers() -> List[ProviderInfo]:
    out: List[ProviderInfo] = []
    for dotted in _iter_provider_modules():
        p = _load_provider(dotted)
        if p:
            out.append(p)
    out.sort(key=lambda p: p.key)
    return out


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
