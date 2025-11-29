"""
Robust HTTP session with retries/backoff for all outbound requests.
"""
from typing import Any, Mapping, Optional

import requests
from requests.adapters import HTTPAdapter, Retry

DEFAULT_HEADERS = {"User-Agent": "Socialite/0.1 (+https://example.com)"}


def _make_session(
    total: int = 3,
    backoff_factor: float = 0.5,
    status_forcelist: tuple[int, ...] = (429, 500, 502, 503, 504),
) -> requests.Session:
    sess = requests.Session()
    retry = Retry(
        total=total,
        read=total,
        connect=total,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    return sess


_SESSION = _make_session()


def get(
    url: str,
    *,
    params: Optional[Mapping[str, Any]] = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: int = 12,
) -> requests.Response:
    return _SESSION.get(
        url, params=params, headers=headers or {}, timeout=timeout
    )


def post(
    url: str,
    *,
    json: Optional[Any] = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: int = 12,
) -> requests.Response:
    return _SESSION.post(
        url, json=json, headers=headers or {}, timeout=timeout
    )
