from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional, Iterable
import json
import logging
import os
import time

import requests
from requests import Response, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


logger = logging.getLogger(__name__)


def _build_retry(total: int = 4, backoff_factor: float = 0.6) -> Retry:
    """
    Exponential backoff with jitter via urllib3 Retry.
    Retries common transient HTTP errors + 429.
    """
    return Retry(
        total=total,
        read=total,
        connect=total,
        status=total,
        backoff_factor=backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504, 522),
        allowed_methods=frozenset({"HEAD", "GET", "OPTIONS"}),
        raise_on_status=False,
        respect_retry_after_header=True,
    )


class HttpClient:
    """
    Small wrapper around requests.Session with sane defaults:
    - Retries + backoff
    - Per-request timeout
    - JSON helper with safe errors
    """

    def __init__(
        self,
        timeout: float = 8.0,
        max_retries: int = 4,
        user_agent: Optional[str] = None,
    ) -> None:
        self._timeout = timeout
        self._session = Session()

        adapter = HTTPAdapter(max_retries=_build_retry(total=max_retries))
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

        ua = user_agent or os.getenv(
            "HTTP_USER_AGENT",
            "SocialiteBot/1.0 (+https://example.com; support@example.com)",
        )
        self._default_headers: dict[str, str] = {
            "User-Agent": ua,
            "Accept": "application/json, text/plain;q=0.9, */*;q=0.8",
        }

    @property
    def session(self) -> Session:
        return self._session

    def get(
        self,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Response:
        merged: MutableMapping[str, str] = dict(self._default_headers)
        if headers:
            merged.update(headers)
        t = timeout or self._timeout
        resp = self._session.get(url, params=params, headers=merged, timeout=t)
        return resp

    def get_json(
        self,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        timeout: Optional[float] = None,
        default: Any = None,
    ) -> Any:
        resp = self.get(url, params=params, headers=headers, timeout=timeout)

        # Soft-handle 404 as empty result for search endpoints
        if resp.status_code == 404:
            logger.info("GET %s -> 404 Not Found (returning default)", resp.url)
            return default

        # For other non-2xx, log and raise for status (so callers can handle)
        try:
            resp.raise_for_status()
        except requests.HTTPError as e:
            # Decorate error with URL to ease debugging
            logger.warning("HTTP error %s for %s", e, resp.url)
            raise

        if not resp.content:
            return default

        try:
            return resp.json()
        except json.JSONDecodeError:
            logger.warning("Non-JSON response from %s; returning text.", resp.url)
            return resp.text
