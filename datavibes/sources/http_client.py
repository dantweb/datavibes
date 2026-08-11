"""Shared HTTP retry helper for the built-in HTTP source adapters (DRY).

The session is always injected (``ctx.http``); this module never creates a
module-level client. Timeout, retry count, backoff, and the User-Agent header
come from the injected :class:`~datavibes.config.app_config.HttpConfig`. A
transient 5xx is retried with linear backoff, then a typed
:class:`SourceFetchError` naming the URL and status is raised.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from datavibes.config.app_config import HttpConfig
from datavibes.errors import SourceFetchError

# Kept for callers/tests that reference the built-in defaults directly.
DEFAULT_RETRIES = HttpConfig.max_retries
DEFAULT_BACKOFF_SECONDS = HttpConfig.backoff_seconds


def request_with_retry(
    http: Any,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    settings: HttpConfig | None = None,
    sleep: Callable[[float], None] | None = None,
) -> Any:
    """GET ``url`` through the injected session, retrying transient failures."""
    if http is None:
        raise SourceFetchError(f"no HTTP session injected for GET {url}")
    settings = settings or HttpConfig()
    if sleep is None:
        sleep = time.sleep

    merged_headers = dict(headers or {})
    if settings.user_agent and "User-Agent" not in merged_headers:
        merged_headers["User-Agent"] = settings.user_agent

    attempts = max(1, settings.max_retries)
    last_status: int | None = None
    for attempt in range(attempts):
        response = http.get(
            url,
            params=params,
            headers=merged_headers,
            timeout=settings.timeout_seconds,
        )
        status = getattr(response, "status_code", 200)
        if 200 <= status < 300:
            return response
        last_status = status
        # 429 is transient too: the polite public APIs (energy-charts, GitHub)
        # meter unauthenticated callers and expect a backed-off retry.
        is_transient = 500 <= status < 600 or status == 429
        if is_transient and attempt < attempts - 1:
            sleep(settings.backoff_seconds * (attempt + 1))
            continue
        break

    raise SourceFetchError(f"GET {url} returned status {last_status}")
