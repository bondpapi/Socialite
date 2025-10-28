from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Iterable
from urllib.parse import urljoin, urlencode, urlparse, parse_qsl, urlunparse

from bs4 import BeautifulSoup


from ..services import http
from .base import build_event

KEY = "kakava"
NAME = "Kakava"

BASE = "https://kakava.lt"
SEARCH_EN = f"{BASE}/en/search"
SEARCH_LT = f"{BASE}/lt/search"

# Candidate category slugs
CATEGORY_SLUGS = {
    "concerts":  {"en": ["concerts"],                 "lt": ["koncertai"]},
    "theater":   {"en": ["theater", "theatre"],       "lt": ["teatras"]},
    "exhibitions":{"en": ["exhibitions"],             "lt": ["parodos", "paroda"]},
    "sport":     {"en": ["sport"],                    "lt": ["sportas"]},
    "festivals": {"en": ["festivals"],                "lt": ["festivaliai"]},
    "kids":      {"en": ["for-kids", "kids"],         "lt": ["vaikams"]},
    "standup":   {"en": ["stand-up", "standup"],      "lt": ["stand-up", "standup"]},
    "halloween": {"en": ["halloween"],                "lt": ["halloween"]},
    "other":     {"en": ["other"],                    "lt": ["kiti", "kita"]},
}

@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime

_jsonld_re = re.compile(r'^\s*{')

# ---------- time & cleaning helpers ----------
def _to_window(start_in_days: int, days_ahead: int) -> Window:
    start = datetime.now(timezone.utc) + timedelta(days=start_in_days)
    end = start + timedelta(days=days_ahead)
    return Window(start, end)

def _parse_date(dt: str | None) -> Optional[datetime]:
    if not dt:
        return None
    try:
        d = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        return d.astimezone(timezone.utc) if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None

def _within_window(d: Optional[datetime], w: Window) -> bool:
    return bool(d and (w.start <= d <= w.end))

def _clean(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    return re.sub(r"\s+", " ", s).strip()

# ---------- network ----------
def _fetch(url: str) -> Optional[str]:
    r = http.get(url, timeout=15)
    if r.status_code == 200:
        return r.text
    return None

# ---------- link extraction ----------
def _extract_event_links_from_html(html: str) -> List[str]:
    """
    Extract likely event detail links from a listing/search page.
    Kakava event pages typically contain '/event/' (EN) or '/renginys/' (LT).
    """
    soup = BeautifulSoup(html, "html.parser")
    links: List[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href:
            continue
        if not href.startswith("http"):
            href = urljoin(BASE, href)
        if "/event/" in href or "/renginys/" in href:
            links.append(href)
    # de-dupe
    seen = set()
    out = []
    for u in links:
        if u not in seen:
            out.append(u)
            seen.add(u)
    return out

# ---------- json-ld parsing ----------
def _extract_jsonld_events(html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []
    for tag in soup.find_all("script", {"type": "application/ld+json"}):
        txt = (tag.string or tag.text or "").strip()
        if not _jsonld_re.search(txt):
            continue
        try:
            data = json.loads(txt)
        except Exception:
            continue

        payloads = data if isinstance(data, list) else [data]
        for obj in payloads:
            if not isinstance(obj, dict):
                continue
            # direct
            if obj.get("@type") == "Event":
                items.append(obj)
                continue
            # @graph container
            graph = obj.get("@graph")
            if isinstance(graph, list):
                for g in graph:
                    if isinstance(g, dict) and g.get("@type") == "Event":
                        items.append(g)
    return items

def _map_jsonld_event(e: Dict[str, Any], country_default: str = "LT") -> Dict[str, Any]:
    title = e.get("name")
    url = e.get("url") or None

    start_iso = None
    dt = _parse_date(e.get("startDate"))
    if dt:
        start_iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    venue_name, city, country = None, None, None
    loc = e.get("location")
    if isinstance(loc, dict):
        venue_name = loc.get("name")
        addr = loc.get("address") or {}
        if isinstance(addr, dict):
            city = addr.get("addressLocality") or addr.get("addressRegion") or None
            country = addr.get("addressCountry") or country_default

    currency = None
    min_price = None
    offers = e.get("offers")
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
        city=city,
        country=country or country_default,
        url=url,
        venue_name=venue_name,
        category=e.get("eventType"),
        currency=currency,
        min_price=min_price,
    )

# ---------- pagination helpers ----------
def _bump_page(url: str, page: int) -> str:
    """
    Try to set ?page=N (or &page=N) while keeping other query params.
    """
    pr = urlparse(url)
    qs = dict(parse_qsl(pr.query, keep_blank_values=True))
    qs["page"] = str(page)
    new_q = urlencode(qs)
    return urlunparse((pr.scheme, pr.netloc, pr.path, pr.params, new_q, pr.fragment))

def _paginate_urls(seed_url: str, max_pages: int = 5) -> Iterable[str]:
    """
    Yield seed_url plus common pagination variants.
    """
    yield seed_url
    # ?page=2..N
    for p in range(2, max_pages + 1):
        yield _bump_page(seed_url, p)
    # /page/2..N variant
    for p in range(2, max_pages + 1):
        if seed_url.endswith("/"):
            yield f"{seed_url}page/{p}"
        else:
            yield f"{seed_url}/page/{p}"

# ---------- category crawling ----------
def _category_urls(language: str = "en") -> List[tuple[str, str]]:
    """
    Returns [(friendly_category, full_url), ...] for the given language.
    """
    lang = "en" if language.lower().startswith("en") else "lt"
    urls: List[tuple[str, str]] = []
    for cat_key, slugs in CATEGORY_SLUGS.items():
        for slug in slugs.get(lang, []):
            urls.append((cat_key, f"{BASE}/{lang}/{slug}".rstrip("/")))
    return urls

def _crawl_categories(language: str = "en", max_pages: int = 5) -> List[tuple[str, str]]:
    """
    Returns list of (category_key, event_link) discovered by walking category pages.
    """
    out: List[tuple[str, str]] = []
    seen_links = set()

    for cat_key, base_url in _category_urls(language):
        # walk a few pages
        for page_url in _paginate_urls(base_url, max_pages=max_pages):
            html = _fetch(page_url)
            if not html:
                continue
            links = _extract_event_links_from_html(html)
            if not links:
                continue
            for l in links:
                if l not in seen_links:
                    seen_links.add(l)
                    out.append((cat_key, l))
    return out

# ---------- search fallback ----------
def _search_site(query: str, language: str = "en") -> List[str]:
    base = SEARCH_EN if language.lower().startswith("en") else SEARCH_LT
    url = f"{base}?{urlencode({'query': query})}"
    html = _fetch(url)
    if not html:
        return []
    return _extract_event_links_from_html(html)

# ---------- main entry ----------
def search(
    *,
    city: str,
    country: str,
    days_ahead: int = 60,
    start_in_days: int = 0,
    query: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Crawl Kakava categories (EN & LT), parse each event page JSON-LD, and filter
    by date window and optional city. Falls back to site search if categories are empty.
    """
    window = _to_window(start_in_days, days_ahead)
    country = (country or "LT").strip().upper()[:2]
    city_q = (city or "").strip()
    q_extra = (query or "").strip()

    # 1) category crawl (EN then LT)
    discovered: List[tuple[str, str]] = []
    discovered.extend(_crawl_categories(language="en", max_pages=5))
    discovered.extend(_crawl_categories(language="lt", max_pages=5))

    # Fallback to search if nothing discovered
    if not discovered:
        queries = []
        if city_q and q_extra:
            queries = [f"{city_q} {q_extra}", city_q, q_extra]
        elif city_q:
            queries = [city_q]
        elif q_extra:
            queries = [q_extra]
        else:
            queries = ["concert", "theatre", "festival"]

        seen = set()
        for q in queries:
            for l in _search_site(q, language="en"):
                if l not in seen:
                    discovered.append(("search", l))
                    seen.add(l)
            for l in _search_site(q, language="lt"):
                if l not in seen:
                    discovered.append(("search", l))
                    seen.add(l)

    # 2) open each event page and parse JSON-LD
    items: List[Dict[str, Any]] = []
    seen_urls = set()

    for cat_key, url in discovered[:200]:  # safety cap
        if url in seen_urls:
            continue
        seen_urls.add(url)

        html = _fetch(url)
        if not html:
            continue

        jsonld_events = _extract_jsonld_events(html)
        if not jsonld_events:
            continue

        for je in jsonld_events:
            dt = _parse_date(je.get("startDate"))
            if not _within_window(dt, window):
                continue

            mapped = _map_jsonld_event(je, country_default=country)

            # City filter (only if provided)
            if city_q:
                city_in_event = (mapped.get("city") or "").lower()
                venue_in_event = (mapped.get("venue_name") or "").lower()
                if city_q.lower() not in city_in_event and city_q.lower() not in venue_in_event:
                    continue

            # Ensure absolute URL (some jsonld use relative)
            if mapped.get("url") and mapped["url"].startswith("/"):
                mapped["url"] = urljoin(BASE, mapped["url"])

            # Persist a friendly category from the crawl key when JSON-LD lacks one
            if not mapped.get("category"):
                mapped["category"] = cat_key

            items.append(mapped)

    return items
