# social_agent_ai/providers/web_discovery.py
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional
from urllib.parse import urlparse

import httpx


DEFAULT_BALTIC_DOMAINS = [
    "bilietai.lt",        # LT
    "tiketa.lt",          # LT
    "kakava.lt",          # LT (venues + ticketing)
    "piletilevi.ee",      # EE
    "bilesuserviss.lv",   # LV
]

JSONLD_RE = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(?P<json>.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)

# --- Small helpers -----------------------------------------------------------

def _domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""

def _as_iter(x) -> Iterable:
    if x is None:
        return []
    if isinstance(x, (list, tuple, set)):
        return x
    return [x]

def _walk(obj):
    """Walk nested dict/list tree, yielding all dicts."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)

def _is_event_dict(d: dict) -> bool:
    t = d.get("@type") or d.get("type")
    if not t:
        return False
    if isinstance(t, str):
        return t.lower() == "event"
    if isinstance(t, list):
        return any(isinstance(x, str) and x.lower() == "event" for x in t)
    return False

def _first_str(*vals) -> Optional[str]:
    for v in vals:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None

# --- Extraction --------------------------------------------------------------

def _extract_events_from_jsonld(html: str, origin_url: str) -> List[dict]:
    out: List[dict] = []
    for m in JSONLD_RE.finditer(html or ""):
        blob = m.group("json").strip()
        if not blob:
            continue
        try:
            data = json.loads(blob)
        except Exception:
            # Try to recover simple trailing commas etc.
            try:
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", blob))
            except Exception:
                continue

        for node in _walk(data):
            if not isinstance(node, dict):
                continue
            if not _is_event_dict(node):
                continue

            name = _first_str(node.get("name"))
            start = _first_str(node.get("startDate"), node.get("start_date"))
            loc = node.get("location") or {}
            if isinstance(loc, list):
                loc = loc[0] if loc else {}
            venue_name = _first_str(
                (loc or {}).get("name"),
                ((loc or {}).get("address") or {}).get("name"),
            )
            address = (loc or {}).get("address") or {}
            city = _first_str(address.get("addressLocality"), address.get("address_locality"))

            offers = node.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            min_price = None
            currency = None
            try:
                if isinstance(offers.get("price"), (int, float, str)):
                    min_price = offers.get("price")
                currency = _first_str(offers.get("priceCurrency"))
            except Exception:
                pass

            url = _first_str(node.get("url"), origin_url)

            if not name:
                continue

            out.append(
                {
                    "source": "web",
                    "external_id": url or origin_url,
                    "title": name,
                    "category": _first_str(node.get("eventType"), "Event"),
                    "start_time": start,        # leave as-is; aggregator handles sorting
                    "city": city,
                    "country": None,            # aggregator supplies filtering by city
                    "venue_name": venue_name,
                    "min_price": min_price,
                    "currency": currency,
                    "url": url or origin_url,
                }
            )
    return out

def _quick_fallback_items(url: str, page_title: str) -> List[dict]:
    """
    If no JSON-LD events found, return a single page-level lead.
    This still gives the agent something to show, and the aggregator
    will fuzzy-dedupe/score across results.
    """
    title = page_title.strip() if page_title else _domain_of(url)
    if not title:
        return []
    return [
        {
            "source": "web",
            "external_id": url,
            "title": title,
            "category": "Event",
            "start_time": None,
            "city": None,
            "country": None,
            "venue_name": None,
            "min_price": None,
            "currency": None,
            "url": url,
        }
    ]

def _page_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", flags=re.I | re.S)
    return (m.group(1).strip() if m else "") if html else ""

# --- Tavily client -----------------------------------------------------------

@dataclass
class _TavilySearchResult:
    url: str
    title: str

class _TavilyClient:
    def __init__(self, api_key: str, timeout: float = 15.0):
        self.api_key = api_key
        self.timeout = timeout
        self.endpoint = "https://api.tavily.com/search"  # works with dev keys

    async def search(
        self,
        query: str,
        include_domains: Optional[List[str]] = None,
        max_results: int = 5,
        depth: str = "basic",
    ) -> List[_TavilySearchResult]:
        payload = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": depth,             # "basic" or "advanced"
            "max_results": max_results,
        }
        if include_domains:
            payload["include_domains"] = include_domains

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(self.endpoint, json=payload)
            if r.status_code == 401:
                print("[WEB] Tavily error: Unauthorized: missing or invalid API key.")
                return []
            if r.status_code != 200:
                print(f"[WEB] Tavily error: HTTP {r.status_code}: {r.text[:200]}")
                return []

            data = r.json()
            items = []
            for res in data.get("results", []):
                u = res.get("url")
                t = res.get("title") or ""
                if u:
                    items.append(_TavilySearchResult(url=u, title=t))
            return items

# --- Provider ---------------------------------------------------------------

import time
_CACHE: dict[tuple, tuple[float, list[dict]]] = {}
_TTL = 300.0  # 5 minutes

def _cache_get(key):
    hit = _CACHE.get(key)
    if not hit: return None
    ts, payload = hit
    if time.time() - ts > _TTL:
        _CACHE.pop(key, None)
        return None
    return payload

def _cache_set(key, payload):
    _CACHE[key] = (time.time(), payload)


class WebDiscoveryProvider:
    """
    Discover events via web search (Tavily) and extract from pages.
    Intended to complement API providers in regions where APIs are sparse.
    """

    def __init__(
        self,
        *,
        tavily_key: str,
        allow_domains: Optional[List[str]] = None,
        max_pages: int = 12,
        timeout: float = 15.0,
    ):
        self.tavily = _TavilyClient(tavily_key, timeout=timeout)
        self.allow_domains = allow_domains or DEFAULT_BALTIC_DOMAINS
        self.max_pages = max_pages
        self.timeout = timeout

    # Provider interface expected by the aggregator
    async def search(
        self,
        *,
        city: str,
        country: str,
        start=None,
        end=None,
        query: str | None = None,
    ) -> List[dict]:
        base_terms = query or "events tickets"
        # If domains are specified, bias the queries toward them.
        queries: List[str] = []
        if self.allow_domains:
            for d in self.allow_domains:
                # site-specific query; keeps results clean
                queries.append(f"{base_terms} {city} {country} site:{d}")
        else:
            queries.append(f"{base_terms} {city} {country}")

        # Run Tavily queries (light parallelism)
        seen_urls: set[str] = set()
        found: List[_TavilySearchResult] = []

        for q in queries:
            hits = await self.tavily.search(
                query=q,
                include_domains=self.allow_domains or None,
                max_results=10,
                depth="basic",
            )
            for h in hits:
                if self.allow_domains and _domain_of(h.url) not in self.allow_domains:
                    continue
                if h.url not in seen_urls:
                    seen_urls.add(h.url)
                    found.append(h)
            if len(found) >= self.max_pages:
                break

        print(
            f"[WEB] queries={len(queries)} urls={len(found)} "
            f"first={[h.url for h in found[:2]]} allow={self.allow_domains or 'None'}"
        )

        if not found:
            return []

        # Fetch pages concurrently and extract events
        sem = asyncio.Semaphore(6)
        results: List[dict] = []

        async def _grab_and_extract(h: _TavilySearchResult):
            async with sem:
                try:
                    async with httpx.AsyncClient(timeout=self.timeout) as client:
                        r = await client.get(h.url, follow_redirects=True)
                        if r.status_code != 200 or not r.text:
                            return
                        html = r.text
                except Exception:
                    return

                items = _extract_events_from_jsonld(html, h.url)
                if not items:
                    title = _page_title(html)
                    items = _quick_fallback_items(h.url, title)

                # Normalize + attach the city we’re searching for (helps aggregator filter)
                for it in items:
                    it.setdefault("city", city)
                    it.setdefault("country", country)
                    # Ensure URL present
                    it["url"] = it.get("url") or h.url
                results.extend(items)

        tasks = [asyncio.create_task(_grab_and_extract(h)) for h in found[: self.max_pages]]
        await asyncio.gather(*tasks, return_exceptions=True)

        return results
