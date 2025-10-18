"""
Robust HTTP session with retries/backoff for all outbound requests.
"""
from typing import Optional, Mapping, Any
import requests
from requests.adapters import HTTPAdapter, Retry


def _make_session(
    total: int = 3,
    backoff_factor: float = 0.5,
    status_forcelist: tuple[int, ...] = (429, 500, 502, 503, 504),
) -> requests.Session:
    sess = requests.Session()
    retry = Retry(
        total=total,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=["GET", "HEAD", "OPTIONS"],
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    sess.mount("http://", adapter)
    sess.mount("https://", adapter)
    return sess


_SESSION = _make_session()


def get(
    url: str,
    *,
    params: Optional[Mapping[str, Any]] = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: int = 12,
) -> requests.Response:
    return _SESSION.get(url, params=params, headers=headers or {}, timeout=timeout)
