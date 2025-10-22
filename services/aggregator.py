"""
Provider aggregation for Socialite.

To avoid exporting module-level mutable state that can trigger circular import
problems during app startup. Instead, we discover providers dynamically and
expose functions.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional

# ---- Provider discovery ------------------------------------------------------

@dataclass(frozen=True)
class ProviderInfo:
    key: str
    name: str
    module: str
    search: Callable[..., List[Dict[str, Any]]]


def _iter_provider_modules() -> Iterable[str]:
    """Yield dotted-module names for all modules in the 'providers' package."""
    pkg_name = "providers"
    pkg = importlib.import_module(pkg_name)
    for m in pkgutil.iter_modules(pkg.__path__):  # type: ignore[attr-defined]
        if m.name.startswith("_"):
            continue
        yield f"{pkg_name}.{m.name}"


def _load_provider(module_name: str) -> Optional[ProviderInfo]:
    """
    Attempt to import a provider module and read its metadata.
    A provider module should define at least a callable named `search`.
    It may optionally define NAME = "Human Friendly Name".
    """
    mod = importlib.import_module(module_name)
    search = getattr(mod, "search", None)
    if not callable(search):
        return None
    name = getattr(mod, "NAME", module_name.rsplit(".", 1)[-1].title())
    key = getattr(mod, "KEY", module_name.rsplit(".", 1)[-1])
    return ProviderInfo(key=key, name=name, module=module_name, search=search)  # type: ignore[return-value]


def _discover_providers() -> List[ProviderInfo]:
    out: List[ProviderInfo] = []
    for dotted in _iter_provider_modules():
        p = _load_provider(dotted)
        if p:
            out.append(p)
    out.sort(key=lambda p: p.key)
    return out


# ---- Public API --------------------------------------------------------------

def list_providers(include_mock: Optional[bool] = None) -> List[Dict[str, str]]:
    """
    Returns lightweight provider metadata for UI.
    If include_mock is False, filters out providers whose key contains 'mock'.
    """
    providers = _discover_providers()
    if include_mock is False:
        providers = [p for p in providers if "mock" not in p.key.lower()]
    return [{"key": p.key, "name": p.name, "module": p.module} for p in providers]


# --- Your original sync search (renamed) -------------------------------------

def search_events_sync(
    *,
    city: str,
    country: str,
    days_ahead: int = 60,
    start_in_days: int = 0,
    include_mock: bool = False,
    query: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Fan-out to all discovered providers, aggregate and return a unified payload.

    Each provider's `search` should accept (city, country, days_ahead, start_in_days, query)
    and return List[dict] items with at least keys:
        title, start_time (ISO), city, country, source, url, category, venue_name, currency, min_price
    """
    items: List[Dict[str, Any]] = []
    providers = _discover_providers()
    for p in providers:
        if not include_mock and "mock" in p.key.lower():
            continue
        try:
            chunk = p.search(
                city=city,
                country=country,
                days_ahead=days_ahead,
                start_in_days=start_in_days,
                query=query,
            )
            if isinstance(chunk, list):
                for e in chunk:
                    e.setdefault("source", p.key)
                items.extend(chunk)
        except Exception as exc:  # Keep a provider failure from taking down the page
            items.append(
                {
                    "title": f"[{p.key}] provider error",
                    "category": "provider_error",
                    "city": city,
                    "country": country,
                    "start_time": None,
                    "url": None,
                    "venue_name": None,
                    "currency": None,
                    "min_price": None,
                    "error": str(exc),
                    "source": p.key,
                }
            )

    return {
        "count": len(items),
        "items": items,
        "providers_used": [p.key for p in providers if include_mock or "mock" not in p.key.lower()],
    }


async def search_events(
    *,
    city: str,
    country: str,
    days_ahead: int = 60,
    start_in_days: int = 0,
    include_mock: bool = False,
    query: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Async façade delegating to the sync implementation so router code can `await` it.
    """
    return search_events_sync(
        city=city,
        country=country,
        days_ahead=days_ahead,
        start_in_days=start_in_days,
        include_mock=include_mock,
        query=query,
    )
