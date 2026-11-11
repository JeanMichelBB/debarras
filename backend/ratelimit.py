"""Tiny in-memory sliding-window rate limiter for abuse-prone endpoints.

Per-process only (one replica today). Behind Cloudflare/Traefik the client IP comes from
CF-Connecting-IP / X-Forwarded-For; do not expose the backend directly without a proxy.
"""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_hits: dict[tuple[str, str], deque] = defaultdict(deque)


def client_ip(request: Request) -> str:
    return (
        request.headers.get("cf-connecting-ip")
        or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )


def rate_limit(name: str, max_calls: int, per_seconds: int):
    def dependency(request: Request) -> None:
        key = (name, client_ip(request))
        now = time.monotonic()
        q = _hits[key]
        while q and q[0] <= now - per_seconds:
            q.popleft()
        if len(q) >= max_calls:
            raise HTTPException(429, "too many requests, slow down")
        q.append(now)

    return dependency
