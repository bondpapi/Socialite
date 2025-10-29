from __future__ import annotations

import asyncio
import importlib
import inspect
import pkgutil
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
import sys
from pathlib import Path

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
    "discovered_modules": [], "loaded": [], "skipped": [], "errors": {}}
_PROVIDERS: List[Provider] = []

# ---------- Module discovery ----------


def _iter_provider_modules() -> Iterable[str]:
    pkg_name = "providers"
    try:
        pkg = importlib.import_module(pkg_name)
        # type: ignore[attr-defined]
        for m in pkgutil.iter_modules(pkg.__path__, pkg_name + "."):
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
                prov = Provider(key=key, module=mod_name, fn=fn, is_async=asyncio.iscoroutinefunction(
                    fn), name=getattr(mod, "NAME", key))
                _PROVIDERS.append(prov)
                _DISCOVERY["loaded"].append(
                    {"key": key, "module": mod_name, "via": "function"})
                continue

            # 2) Provider class with .search()
            ProvCls = getattr(mod, "Provider", None)
            if ProvCls is not None and inspect.isclass(ProvCls):
                try:
                    inst = ProvCls()
                    sfn = getattr(inst, "search", None)
                    if callable(sfn):
                        prov = Provider(key=key, module=mod_name, fn=lambda **kw: getattr(inst, "search")(
                            **kw), is_async=asyncio.iscoroutinefunction(sfn), name=getattr(inst, "name", key))
                        _PROVIDERS.append(prov)
                        _DISCOVERY["loaded"].append(
                            {"key": key, "module": mod_name, "via": "Provider"})
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
                        prov = Provider(key=key, module=mod_name, fn=lambda **kw: getattr(inst, "search")(
                            **kw), is_async=asyncio.iscoroutinefunction(sfn), name=getattr(inst, "name", key))
                        _PROVIDERS.append(prov)
                        _DISCOVERY["loaded"].append(
                            {"key": key, "module": mod_name, "via": "get_provider"})
                        continue
                except Exception as e:
                    _DISCOVERY["errors"][mod_name] = f"get_provider() failed: {e}"

            _DISCOVERY["skipped"].append(
                {"module": mod_name, "reason": "no_search_function"})
        except Exception as e:
            _DISCOVERY["errors"][mod_name] = f"{type(e).__name__}: {e}"


# initial load
_load_providers()

# ---------- Diagnostics / helpers ----------


def list_provider_diagnostics() -> Dict[str, Any]:
    return {
        "providers": [{"key": p.key, "module": p.module, "is_async": p.is_async, "name": p.name} for p in _PROVIDERS],
        "discovery": _DISCOVERY,
    }


def _discover_providers() -> List[Provider]:
    # return current providers list
    return list(_PROVIDERS)


def list_providers(include_mock: Optional[bool] = None) -> List[Dict[str, str]]:
    providers = _discover_providers()
    if include_mock is False:
        providers = [p for p in providers if "mock" not in p.key.lower()]
    return [{"key": p.key, "name": p.name or p.key, "module": p.module} for p in providers]

# ---------- Core fan-out ----------


async def _call_provider(
    p: Provider,
    *,
    city: str,
    country: str,
    days_ahead: int,
    start_in_days: int,
    query: Optional[str],
) -> Tuple[str, List[Dict[str, Any]], Optional[str]]:
    kwargs = dict(city=city, country=country, days_ahead=days_ahead,
                  start_in_days=start_in_days, query=query)
    try:
        if p.is_async:
            chunk = await p.fn(**kwargs)  # type: ignore[misc]
        else:
            # type: ignore[misc]
            chunk = await asyncio.to_thread(p.fn, **kwargs)
    except Exception as exc:
        return p.key, [], f"{type(exc).__name__}: {exc}"

    items: List[Dict[str, Any]] = []
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
) -> Dict[str, Any]:
    providers = _discover_providers()
    if include_mock is False:
        providers = [p for p in providers if "mock" not in p.key.lower()]

    tasks = [_call_provider(p, city=city, country=country, days_ahead=days_ahead,
                            start_in_days=start_in_days, query=query) for p in providers]

    results: List[Tuple[str, List[Dict[str, Any]], Optional[str]]] = []
    if tasks:
        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        for g in gathered:
            if isinstance(g, Exception):
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
        "debug": {"discovered": [p.key for p in _discover_providers()], "errors": errors},
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
) -> Dict[str, Any]:
    return await _search_events_async(city=city, country=country, days_ahead=days_ahead, start_in_days=start_in_days, include_mock=include_mock, query=query)


def search_events_sync(
    *,
    city: str,
    country: str,
    days_ahead: int = 60,
    start_in_days: int = 0,
    include_mock: bool = False,
    query: Optional[str] = None,
) -> Dict[str, Any]:
    return asyncio.run(_search_events_async(city=city, country=country, days_ahead=days_ahead, start_in_days=start_in_days, include_mock=include_mock, query=query))
