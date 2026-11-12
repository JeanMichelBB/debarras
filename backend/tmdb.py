"""TMDb client. The token never leaves the backend.

- Bearer-token auth (Read Access Token), never in a URL.
- Global rate limiter shared by all users (TMDb limits per IP, not per key).
- Single-flight: concurrent identical requests share one upstream call.
- In-memory TTL cache for list-style calls; MySQL `title_cache` for details.
- Stale cache is served if TMDb errors.
"""

import asyncio
import time
from datetime import timedelta

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

import config
from database.models import TitleCache, utcnow

BASE = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p"
LANGS = {"en": "en-US", "fr": "fr-CA"}
SLIM_VERSION = 3  # bump when _slim keeps new fields: older cached rows are refetched on open
APPEND = "videos,credits,external_ids,keywords,reviews,watch/providers"

_client: httpx.AsyncClient | None = None
_mem: dict[str, tuple[float, dict]] = {}
_inflight: dict[str, asyncio.Future] = {}
_MEM_TTL = 3600
_MEM_MAX = 3000


class _Limiter:
    """Spaces requests at least 1/rate seconds apart (no lock needed: single event loop)."""

    def __init__(self, rate: float):
        self.interval = 1.0 / rate
        self._next = 0.0

    async def wait(self) -> None:
        now = time.monotonic()
        start = max(now, self._next)
        self._next = start + self.interval
        if start > now:
            await asyncio.sleep(start - now)


_limiter = _Limiter(config.TMDB_RPS)


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10.0)
    return _client


def tmdb_lang(lang: str) -> str:
    return LANGS.get(lang, LANGS["en"])


async def _fetch(path: str, params: dict, lang: str) -> dict:
    if not config.TMDB_READ_TOKEN:
        raise HTTPException(500, "server misconfigured: TMDB_READ_TOKEN not set")
    q = {"language": tmdb_lang(lang), **params}
    headers = {"Authorization": f"Bearer {config.TMDB_READ_TOKEN}", "accept": "application/json"}
    for attempt in range(3):
        await _limiter.wait()
        try:
            r = await _get_client().get(BASE + path, params=q, headers=headers)
        except httpx.HTTPError:
            if attempt == 2:
                raise HTTPException(502, "TMDb unreachable")
            await asyncio.sleep(0.5 * (attempt + 1))
            continue
        if r.status_code == 429:
            try:
                delay = float(r.headers.get("Retry-After", "1"))
            except ValueError:
                delay = 1.0
            await asyncio.sleep(min(delay, 5.0))
            continue
        if r.status_code >= 500 and attempt < 2:  # TMDb hiccup: try again before giving up
            await asyncio.sleep(0.5 * (attempt + 1))
            continue
        if r.status_code == 404:
            raise HTTPException(404, "not found on TMDb")
        if r.status_code in (401, 403):
            raise HTTPException(500, "server misconfigured: TMDb rejected the token")
        if r.status_code != 200:
            raise HTTPException(502, f"TMDb error {r.status_code}")
        return r.json()
    raise HTTPException(503, "TMDb is busy, try again shortly")


async def tmdb_get(
    path: str, params: dict | None = None, *, lang: str = "en", cache: bool = True
) -> dict:
    params = params or {}
    key = f"{lang}|{path}|" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    now = time.time()
    if cache and key in _mem and _mem[key][0] > now:
        return _mem[key][1]

    fut = _inflight.get(key)
    if fut is None:
        fut = asyncio.ensure_future(_fetch(path, params, lang))
        _inflight[key] = fut
        fut.add_done_callback(lambda _f, k=key: _inflight.pop(k, None))
    data = await asyncio.shield(fut)

    if cache:
        if len(_mem) >= _MEM_MAX:
            _mem.clear()
        _mem[key] = (now + _MEM_TTL, data)
    return data


def poster_url(path: str | None, size: str = "w500") -> str | None:
    return f"{IMG}/{size}{path}" if path else None


def poster_path_from_url(url: str | None) -> str | None:
    """Store only the path part (e.g. /abc.jpg) so the size can change later."""
    if not url:
        return None
    if url.startswith(IMG):
        url = url[len(IMG):]
        url = "/" + url.split("/", 2)[2] if url.count("/") >= 2 else url
    return url[:255] if url.startswith("/") else None


def card(item: dict, media_type: str | None = None, reason: str | None = None) -> dict:
    """Minimal card shape for the swipe UI, from any TMDb list item or details."""
    mt = media_type or item.get("media_type")
    date = item.get("release_date") or item.get("first_air_date") or ""
    return {
        "tmdb_id": item["id"],
        "media_type": mt,
        "title": item.get("title") or item.get("name") or "",
        "year": date[:4] or None,
        "poster": poster_url(item.get("poster_path")),
        "overview": item.get("overview") or "",
        "vote_average": item.get("vote_average"),
        "imdb_id": item.get("imdb_id"),
        "reason": reason,
    }


def _providers(raw: dict) -> dict:
    out = {}
    for country, p in ((raw.get("watch/providers") or {}).get("results") or {}).items():
        entry = {"link": p.get("link")}
        for kind in ("flatrate", "rent", "buy", "free", "ads"):
            if p.get(kind):
                entry[kind] = [
                    {"name": x.get("provider_name"), "logo": poster_url(x.get("logo_path"), "w92")}
                    for x in p[kind]
                ]
        out[country] = entry
    return out


def _crew(raw: dict, credits: dict, jobs: set[str]) -> list[dict]:
    """Directors, writers and creators. TV shows list their creators in `created_by`, not in credits."""
    out = [
        {"id": c["id"], "name": c["name"], "job": c.get("job"), "photo": poster_url(c.get("profile_path"), "w185")}
        for c in credits.get("crew", []) if c.get("job") in jobs
    ]
    have = {(c["id"], c["job"]) for c in out}
    for c in raw.get("created_by") or []:
        if (c["id"], "Creator") not in have:
            out.append({"id": c["id"], "name": c["name"], "job": "Creator",
                        "photo": poster_url(c.get("profile_path"), "w185")})
    return out


def _slim(raw: dict, media_type: str) -> dict:
    """Keep only what the app uses, so title_cache rows stay small."""
    ext = raw.get("external_ids") or {}
    credits = raw.get("credits") or {}
    videos = [
        v for v in (raw.get("videos") or {}).get("results", [])
        if v.get("site") == "YouTube" and v.get("type") in ("Trailer", "Teaser")
    ]
    videos.sort(key=lambda v: (v.get("type") != "Trailer", not v.get("official", False)))
    kw = raw.get("keywords") or {}
    keywords = kw.get("keywords") or kw.get("results") or []
    crew_jobs = {"Director", "Creator", "Writer", "Screenplay"}
    keep = (
        "id", "title", "name", "overview", "tagline", "poster_path", "backdrop_path",
        "release_date", "first_air_date", "runtime", "episode_run_time", "genres",
        "vote_average", "vote_count", "belongs_to_collection", "number_of_seasons",
        "created_by", "status",
    )
    return {
        **{k: raw.get(k) for k in keep},
        "media_type": media_type,
        "v": SLIM_VERSION,
        "imdb_id": raw.get("imdb_id") or ext.get("imdb_id"),
        "cast": [
            {"id": c["id"], "name": c["name"], "character": c.get("character"),
             "photo": poster_url(c.get("profile_path"), "w185")}
            for c in credits.get("cast", [])[:15]
        ],
        "crew": _crew(raw, credits, crew_jobs),
        "videos": [{"key": v["key"], "name": v.get("name"), "type": v.get("type")} for v in videos[:3]],
        "keywords": [{"id": k["id"], "name": k["name"]} for k in keywords[:15]],
        "reviews": [
            {
                "author": r.get("author"),
                "content": (r.get("content") or "")[:1200],
                "rating": (r.get("author_details") or {}).get("rating"),
            }
            for r in (raw.get("reviews") or {}).get("results", [])[:5]
        ],
        "providers": _providers(raw),
    }


async def get_details(db: Session, media_type: str, tmdb_id: int, lang: str = "en") -> dict:
    row = db.get(TitleCache, (media_type, tmdb_id, lang))
    if row and row.data.get("v") == SLIM_VERSION and row.refreshed_at > utcnow() - timedelta(days=config.CACHE_TTL_DAYS):
        return row.data

    try:
        raw = await tmdb_get(f"/{media_type}/{tmdb_id}", {"append_to_response": APPEND}, lang=lang, cache=False)
    except HTTPException as e:
        if row and e.status_code != 404:
            return row.data  # stale beats failing
        raise
    data = _slim(raw, media_type)

    # French overviews are often empty: fall back to English for missing text.
    if lang != "en" and not data.get("overview"):
        try:
            en = await tmdb_get(f"/{media_type}/{tmdb_id}", {}, lang="en")
            data["overview"] = en.get("overview") or ""
            data["tagline"] = data.get("tagline") or en.get("tagline")
        except HTTPException:
            pass

    if row:
        row.data, row.refreshed_at = data, utcnow()
    else:
        db.add(TitleCache(media_type=media_type, tmdb_id=tmdb_id, lang=lang, data=data, refreshed_at=utcnow()))
    db.commit()
    return data
