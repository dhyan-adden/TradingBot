from __future__ import annotations

import random
import time
from dataclasses import dataclass

import httpx

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 TradeLoop/1.0"
)


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    headers: dict
    not_modified: bool


class Http:
    """One shared hardened client: UA, retry/backoff/jitter, timeout, conditional GET,
    optional cookie warmup for hosts (NSE/BSE) that hand out a cookie on the homepage first."""

    def __init__(self, timeout: float = 10.0, retries: int = 3, warmup_hosts: tuple[str, ...] = ()):
        self.retries = retries
        self.warmup_hosts = warmup_hosts
        self._warmed: set[str] = set()
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": DEFAULT_UA, "Accept-Language": "en-IN,en;q=0.9"},
        )

    def _sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def _warmup(self, url: str) -> None:
        host = httpx.URL(url).host or ""
        if host and host in self.warmup_hosts and host not in self._warmed:
            try:
                self._client.get(f"https://{host}/", timeout=self._client.timeout)
            except httpx.HTTPError:
                pass  # warmup is best-effort; the real request still carries any cookie set
            self._warmed.add(host)

    def get(self, url, *, etag=None, modified=None, extra_headers=None) -> HttpResponse:
        self._warmup(url)
        headers: dict = dict(extra_headers or {})
        if etag:
            headers["If-None-Match"] = etag
        if modified:
            headers["If-Modified-Since"] = modified
        last_exc: Exception | None = None
        for attempt in range(self.retries):
            try:
                resp = self._client.get(url, headers=headers)
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.retries - 1:
                    self._sleep((2 ** attempt) + random.uniform(0, 0.5))
                    continue
                return HttpResponse(
                    status=resp.status_code,
                    body=resp.content,
                    headers=dict(resp.headers),
                    not_modified=resp.status_code == 304,
                )
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < self.retries - 1:
                    self._sleep((2 ** attempt) + random.uniform(0, 0.5))
                    continue
        assert last_exc is not None
        raise last_exc

    def close(self) -> None:
        self._client.close()
