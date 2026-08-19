"""Cliente HTTP com retry e Retry-After."""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx

from osint4all.exceptions import FailedAuthentication, FailedRateLimit, FailedSource, FailedTimeout


class RateLimitedClient:
    def __init__(
        self,
        *,
        source: str,
        max_concurrency: int = 3,
        timeout: float = 30.0,
        default_headers: dict[str, str] | None = None,
        proxy: str | None = None,
    ) -> None:
        self.source = source
        self._thread_sem = threading.Semaphore(max_concurrency)
        self.timeout = timeout
        self.default_headers = default_headers or {}
        self.proxy = (proxy or "").strip() or None

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        max_retries: int = 3,
        allow_404: bool = False,
    ) -> httpx.Response:
        hdrs = {**self.default_headers, **(headers or {})}
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            self._thread_sem.acquire()
            try:
                client_kwargs: dict[str, Any] = {"timeout": self.timeout, "follow_redirects": True}
                if self.proxy:
                    client_kwargs["proxy"] = self.proxy
                with httpx.Client(**client_kwargs) as client:
                    resp = client.request(method, url, headers=hdrs, json=json, params=params)
                if resp.status_code in (401, 403):
                    raise FailedAuthentication(f"{self.source} auth failed: {resp.status_code}")
                if resp.status_code == 404 and allow_404:
                    return resp
                if resp.status_code == 429:
                    retry_after = _parse_retry_after(resp)
                    if attempt < max_retries:
                        time.sleep(retry_after or (2**attempt))
                        continue
                    raise FailedRateLimit(f"{self.source} rate limited", retry_after=retry_after)
                if resp.status_code >= 500:
                    if attempt < max_retries:
                        time.sleep(2**attempt)
                        continue
                    raise FailedSource(f"{self.source} HTTP {resp.status_code}")
                return resp
            except httpx.TimeoutException as exc:
                last_exc = FailedTimeout(str(exc))
                if attempt < max_retries:
                    time.sleep(2**attempt)
                    continue
                raise last_exc from exc
            except (FailedAuthentication, FailedRateLimit, FailedSource):
                raise
            except httpx.HTTPError as exc:
                last_exc = FailedSource(str(exc))
                if attempt < max_retries:
                    time.sleep(2**attempt)
                    continue
                raise last_exc from exc
            finally:
                self._thread_sem.release()
        raise last_exc or FailedSource(f"{self.source} request failed")


def _parse_retry_after(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return 5.0
