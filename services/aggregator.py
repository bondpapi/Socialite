from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from typing import Any, Callable, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


SearchFn = Callable[..., Iterable[dict]]

def _discover_providers() -> Dict[str, SearchFn]:
    """
    Dynamically import modules under the `providers` package and collect any
    top-level callable named `search`. The key is the module's short name.
    """
    found: Dict[str, SearchFn] = {}

    try:
        pkg = importlib.import_module("providers")
    except Exception as e:
        logger.exception("Failed to import providers package: %s", e)
        return found

    if not hasattr(pkg, "__path__"):
        return found

    for m in pkgutil.iter_modules(pkg.__path__, prefix="providers."):
        mod_name = m.name
        short = mod_name.split(".")[-1]  # e.g. providers.eventbrite -> eventbrite
        try:
            mod = importlib.import_module(mod_name)
        except Exception as e:
            logger.warning("Provider %s failed to import: %s", mod_name, e)
            continue

        search = getattr(mod, "search", None)
        if callable(search):
            found[short] = search  # type: ignore[assignment]
        else:
            # Optional: allow a PROVIDER object exposing a .search(...) method
            prov = getattr(mod, "PROVIDER", None)
            if prov is not None and callable(getattr(prov, "search", None)):
                found[short] = prov.search  # type: ignore[assignment]
            else:
                logger.debug("Provider %s has no search()", mod_name)

    return found


# Build once at import; safe even if empty.
_PROVIDERS: Dict[str, SearchFn] = _discover_providers()


def get_providers(include_mock: bool = False,
                  allow_only: Optional[Iterable[str]] = None) -> Dict[str, SearchFn]:
    """
    Return a filtered dict of available providers.
    - include_mock=False filters out modules named 'mock' (common pattern)
    - allow_only restricts to a given subset by name
    """
    providers = dict(_PROVIDERS)

    if not include_mock:
        providers.pop("mock", None)

    if allow_only is not None:
        allow = {name.lower() for name in allow_only}
        providers = {k: v for k, v in providers.items() if k.lower() in allow}

    return providers


def search_events(*,
                  city: str,
                  country: str,
                  days_ahead: int,
                  start_in_days: int = 0,
                  query: Optional[str] = None,
                  include_mock: bool = False,
                  providers: Optional[Iterable[str]] = None,
                  extra_kwargs: Optional[dict] = None) -> Dict[str, Any]:
    """
    Aggregate events across available providers.

    Returns a dict like:
      {"count": N, "items": [ {...event...}, ... ]}

    Each provider's `search` is called with the standard kwargs plus any extra_kwargs.
    """
    params = dict(
        city=city,
        country=country,
        days_ahead=days_ahead,
        start_in_days=start_in_days,
        query=query,
    )
    if extra_kwargs:
        params.update(extra_kwargs)

    registry = get_providers(include_mock=include_mock, allow_only=providers)

    items: List[dict] = []
    for name, fn in registry.items():
        try:
            result = fn(**params) if _accepts_kwargs(fn) else fn(city, country, days_ahead)  # type: ignore[misc]
            if result:
                items.extend(list(result))
        except Exception as e:
            logger.warning("Provider %s.search failed: %s", name, e)

    return {"count": len(items), "items": items}


def _accepts_kwargs(fn: Callable[..., Any]) -> bool:
    """Return True if function accepts **kwargs (or the full param set)."""
    sig = inspect.signature(fn)
    if any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
        return True
    expected = {"city", "country", "days_ahead", "start_in_days", "query"}
    have = set(sig.parameters.keys())
    return expected.issubset(have)
