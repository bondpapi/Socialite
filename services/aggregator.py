from __future__ import annotations

import asyncio
import importlib
import pkgutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

from config import settings  # expects settings.ticketmaster_api_key, settings.eventbrite_token, optional settings.ics_feeds

# Hard exclude providers by key (without deleting files)
EXCLUDE_KEYS = {"seatgeek"}

@dataclass(frozen=True)
class ProviderInfo:
    key: str                 # e.g., "ticketmaster"
    name: str                # human readable
    module: str              # dotted path
    kind: str                # "function" or "class"
    callable: Any            # function or provider instance


# ---------- discovery ---------------------------------------------------------

def _iter_provider_modules() -> Iterable[str]:
    """
    Discover modules inside the top-level 'providers' package.
    """
    pkg_name = "providers"
    try:
        pkg = importlib.import_module(pkg_name)
    except Exception:
        return []

    for m in pkgutil.iter_modules(getattr(pkg, "__path__", [])):
        if not m.name.startswith("_"):
            yield f"{pkg_name}.{m.name}"


def _load_provider(module_name: str) -> Optional[ProviderInfo]:
    """
    Accept either:
      - module-level function: search(city, country, days_ahead, start_in_days, query)
      - class provider with async: search(city, country, start, end, query)
    """
    try:
        mod = importlib.import_module(module_name)
    except Exception:
        return None

    # A) module-level sync search(...)
    fn = getattr(mod, "search", None)
    if callable(fn):
        key = getattr(mod, "KEY", module_name.rsplit(".", 1)[-1]).lower()
        name = getattr(mod, "NAME", key.title())
        if key in EXCLUDE_KEYS:
            return None
        return ProviderInfo(key=key, name=name, module=module_name, kind="function", callable=fn)

    # B) class-based provider with async search(...)
    for attr_name in dir(mod):
        cls = getattr(mod, attr_name)
        if not isinstance(cls, type):
            continue
        if not hasattr(cls, "search"):
            continue

        # Try to construct. Known constructors mapped to your config.
        instance = None
        try:
            instance = cls()
        except Exception:
            try:
                if "Ticketmaster" in cls.__name__:
                    instance = cls(getattr(settings, "ticketmaster_api_key", None))
                elif "Eventbrite" in cls.__name__:
                    instance = cls(getattr(settings, "eventbrite_token", None))
                elif "ICS" in cls.__name__:
                    feeds = getattr(settings, "ics_feeds", []) or []
                    instance = cls(feeds)
                elif "Mock" in cls.__name__:
                    instance = cls()
            except Exception:
                instance = None

        if instance is None:
            continue

        key = getattr(mod, "KEY", getattr(instance, "name", attr_name)).lower()
        name = getattr(mod, "NAME", key.title())
        if key in EXCLUDE_KEYS or getattr(instance, "name", "").lower() in EXCLUDE_KEYS:
            return None

        return ProviderInfo(key=key, name=name, module=module_name, kind="class", callable=instance)

    return None


def _discover_providers() -> List[ProviderInfo]:
    out: List[ProviderInfo] = []
    for dotted in _iter_provider_modules():
        p = _load_provider(dotted)
        if p:
            out.append(p)
    out.sort(key=lambda p: p.key)
    return out


def list_providers(include_mock: Optional[bool] = None) -> List[Dict[str, str]]:
    providers = _discover_providers()
    if include_mock is False:
        providers = [p for p in providers if "mock" not in p.key.lower()]
    return [{"key": p.key, "name": p.name, "module": p.module} for p in providers]


# ---------- helpers -----------------------------------------------------------

def _to_window(start_in_days: int, days_ahead: int):
    start = datetime.now(timezone.utc) + timedelta(days=start_in_days)
    end = start + timedelta(days=days_ahead)
    return start, end


# ---------- public API --------------------------------------------------------

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
    Fan-out to all providers. Supports both module-level and class-based providers.
    Returns a debug block for transparency.
    """
    city = city.strip().title()
    country = country.strip().upper()[:2]
    start, end = _to_window(start_in_days, days_ahead)

    providers = _discover_providers()
    used = [p for p in providers if include_mock or "mock" not in p.key.lower()]

    results: List[Dict[str, Any]] = []
    errors: List[str] = []

    async def _run():
        tasks = []
        for p in used:
            try:
                if p.kind == "function":
                    # old-style module function
                    chunk = p.callable(
                        city=city, country=country,
                        days_ahead=days_ahead, start_in_days=start_in_days,
                        query=query
                    ) or []
                    for e in chunk:
                        e.setdefault("source", p.key)
                    results.extend(chunk)
                else:
                    # class-based async provider
                    coro = p.callable.search(
                        city=city, country=country,
                        start=start, end=end, query=query
                    )
                    tasks.append((p, asyncio.create_task(coro)))
            except Exception as e:
                errors.append(f"{p.key}: {e}")

        for p, t in tasks:
            try:
                chunk = await t
                if chunk:
                    for e in chunk:
                        e.setdefault("source", p.key)
                    results.extend(list(chunk))
            except Exception as e:
                errors.append(f"{p.key}: {e}")

    asyncio.run(_run())

    if not used:
        errors.append("No providers available (mocks filtered out or excluded).")
    elif not results:
        errors.append("Providers returned no events for this query window.")

    return {
        "count": len(results),
        "items": results,
        "debug": {
            "discovered": [p.key for p in providers],
            "providers_used": [p.key for p in used],
            "errors": errors,
        },
    }


async def search_events(**kw) -> Dict[str, Any]:
    # Async façade for router
    return search_events_sync(**kw)
