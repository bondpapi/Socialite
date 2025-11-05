from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional
import logging
import re
import json
from pathlib import Path
from bs4 import BeautifulSoup

from utils.http_client import HttpClient
from utils.cache import FileCache
from config import settings
from providers.base import build_event

logger = logging.getLogger(__name__)

DEFAULT_SITES = [
    "bilietai.lt",
    "piletilevi.ee",
    "bilesuserviss.lv",
    "tiketa.lt",
    "kakava.lt",
]

CACHE_NS = "web_discovery"

try:
    cache_root = Path(getattr(settings, "cache_dir", "."))
except Exception:
    cache_root = Path(".")

cache = FileCache(cache_root, enabled=True)

def _cache() -> FileCache:
    return FileCache(Path(getattr(settings, "cache_dir", ".")), enabled=getattr(settings, "cache_enabled", True))

def _looks_like_event_title(text: str) -> bool:
    if not text:
        return False
    bad = {"cookies", "privacy", "login", "terms"}
    return not any(w in text.lower() for w in bad)

_A_RE = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>([^<]{4,200})</a>', re.I)

def _extract_links(html: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for m in _A_RE.finditer(html or ""):
        href, title = m.groups()
        title = re.sub(r"\s+", " ", title).strip()
        out.append({"href": href, "title": title})
    return out

def _first(obj, *keys):
    cur = obj
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k)
        else:
            return None
    return cur

def _jsonld_from_html(html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, Any]] = []
    for s in soup.find_all("script", {"type": "application/ld+json"}):
        txt = (s.string or s.text or "").strip()
        if not txt.startswith("{") and not txt.startswith("["):
            continue
        try:
            data = json.loads(txt)
        except Exception:
            continue
        payloads = data if isinstance(data, list) else [data]
        for obj in payloads:
            if isinstance(obj, dict):
                if obj.get("@type") == "Event":
                    out.append(obj)
                elif isinstance(obj.get("@graph"), list):
                    for g in obj["@graph"]:
                        if isinstance(g, dict) and g.get("@type") == "Event":
                            out.append(g)
    return out

def _enrich_from_jsonld(html: str, *, city: str, country: str, fallback_title: str, url: str) -> Dict[str, Any]:
    for ev in _jsonld_from_html(html):
        title = ev.get("name") or fallback_title
        url0 = ev.get("url") or url
        desc = ev.get("description") or None
        img = ev.get("image")
        if isinstance(img, list) and img:
            img = img[0]
        elif not isinstance(img, str):
            img = None

        # location
        venue_name, city0, country0 = None, None, None
        loc = ev.get("location")
        if isinstance(loc, dict):
            venue_name = loc.get("name") or None
            addr = loc.get("address") or {}
            if isinstance(addr, dict):
                city0 = addr.get("addressLocality") or addr.get("addressRegion") or None
                country0 = addr.get("addressCountry") or None

        # dates
        start_iso = ev.get("startDate") or None
        # prices
        currency, min_price = None, None
        offers = ev.get("offers")
        if isinstance(offers, dict):
            currency = offers.get("priceCurrency") or currency
            try:
                p = offers.get("lowPrice") or offers.get("price")
                if p is not None:
                    min_price = float(p)
            except Exception:
                pass
        elif isinstance(offers, list) and offers:
            o0 = offers[0]
            if isinstance(o0, dict):
                currency = o0.get("priceCurrency") or currency
                try:
                    p = o0.get("lowPrice") or o0.get("price")
                    if p is not None:
                        min_price = float(p)
                except Exception:
                    pass

        return build_event(
            title=title,
            start_time=start_iso,
            city=city0 or city,
            country=(country0 or country),
            url=url0,
            venue_name=venue_name,
            category=ev.get("eventType"),
            description=desc,
            image_url=img,
            currency=currency,
            min_price=min_price,
            external_id=url0,
            source="web",
        )

    # fallback if no JSON-LD
    return build_event(
        title=fallback_title,
        start_time=None,
        city=city,
        country=country,
        url=url,
        venue_name=None,
        category="Event",
        description=None,
        image_url=None,
        currency=None,
        min_price=None,
        external_id=url,
        source="web",
    )

def crawl_sites(
    *,
    client: HttpClient,
    city: str,
    country: str,
    allow_domains: Optional[Iterable[str]] = None,
    keyword: Optional[str] = None,
    limit_per_site: int = 25,
) -> List[Dict[str, Any]]:
    domains = list(allow_domains or DEFAULT_SITES)
    all_items: List[Dict[str, Any]] = []

    for domain in domains:
        url = f"https://{domain}"

        def _fetch_html() -> str:
            try:
                resp = client.get(url)
                resp.raise_for_status()
                return resp.text or ""
            except Exception as e:
                logger.info("Web discovery error for %s: %s", url, e)
                return ""

        html = _cache().get_or_set(
            CACHE_NS,
            json.dumps({"seed": url}),
            max_age=float(getattr(settings, "web_cache_ttl_seconds", 3600)),
            producer=_fetch_html,
        )
        if not html:
            continue

        links = _extract_links(html)
        seen = set()
        per_site_items: List[Dict[str, Any]] = []

        for link in links:
            href = link["href"]
            title = link["title"]
            if not _looks_like_event_title(title):
                continue
            if href in seen:
                continue
            seen.add(href)

            # fetch the detail page to try JSON-LD enrichment (cache it)
            def _fetch_detail() -> str:
                try:
                    r = client.get(href)
                    r.raise_for_status()
                    return r.text or ""
                except Exception:
                    return ""

            detail_html = _cache().get_or_set(
                CACHE_NS,
                json.dumps({"detail": href}),
                max_age=float(getattr(settings, "web_cache_ttl_seconds", 3600)),
                producer=_fetch_detail,
            )

            enriched = _enrich_from_jsonld(detail_html, city=city, country=country, fallback_title=title, url=href)
            if keyword:
                if keyword.lower() not in (enriched["title"] or "").lower():
                    continue

            per_site_items.append(enriched)
            if len(per_site_items) >= limit_per_site:
                break

        all_items.extend(per_site_items)

    return all_items
