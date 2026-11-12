"""TMDb client. The token never leaves the backend.

- Bearer-token auth (Read Access Token), never in a URL.
- Global rate limiter shared by all users (TMDb limits per IP, not per key). Taps the user
  made (opening a title) go ahead of background queue building.
- Single-flight: concurrent identical requests share one upstream call.
- In-memory LRU cache for list-style calls, slimmed before storing; expired entries are served
  at once and refreshed in the background. MySQL `title_cache` for details.
- Stale cache is served if TMDb errors.
"""

import asyncio
import re
import time
from collections import OrderedDict
from datetime import timedelta

import httpx
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import config
from database.connection import SessionLocal
from database.models import TitleCache, utcnow

BASE = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p"
LANGS = {"en": "en-US", "fr": "fr-CA"}
SLIM_VERSION = 5  # bump when _slim keeps new fields: older cached rows are refetched on open
APPEND = "videos,credits,external_ids,keywords,reviews,watch/providers,recommendations"

_client: httpx.AsyncClient | None = None
_mem: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()  # key -> (expires at, data), least recently used first
_inflight: dict[str, asyncio.Future] = {}
_MEM_MAX = 2000
_STALE = 6 * 3600  # an expired entry younger than this is served at once and refreshed behind the scenes

# Fields of a list item that the queue builder and `card` actually read.
_ITEM_KEYS = (
    "id", "media_type", "title", "name", "release_date", "first_air_date", "poster_path", "overview",
    "vote_average", "vote_count", "genre_ids", "order", "job",
)


def _ttl(path: str) -> int:
    """Credits, collections, people, studios and genres barely change; trending and discover do."""
    return 86400 if path.startswith(("/genre/", "/collection/", "/person/", "/company/")) else 3600


def _item(x: dict) -> dict:
    return {k: x[k] for k in _ITEM_KEYS if k in x}


def _top(rows: list[dict], n: int) -> list[dict]:
    return sorted(rows, key=lambda p: p.get("vote_count") or 0, reverse=True)[:n]


def _shrink(path: str, data: dict) -> dict:
    """Keep only what callers read from big list responses, so 2000 cached entries stay small."""
    if re.fullmatch(r"/person/\d+/movie_credits", path):
        return {
            "cast": [_item(c) for c in _top(data.get("cast") or [], 40)],
            "crew": [_item(c) for c in data.get("crew") or [] if c.get("job") == "Director"],
        }
    if re.fullmatch(r"/person/\d+/combined_credits", path):
        return {
            "cast": [_item(c) for c in _top([c for c in data.get("cast") or [] if c.get("order") is None or c["order"] < 10], 60)],
            "crew": [_item(c) for c in data.get("crew") or [] if c.get("job") in ("Director", "Creator")],
        }
    if re.fullmatch(r"/person/\d+", path) and "combined_credits" in data:
        cc = data["combined_credits"] or {}
        return {**data, "combined_credits": {
            "cast": [_item(c) for c in _top([c for c in cc.get("cast") or [] if c.get("order") is None or c["order"] < 10], 60)],
            "crew": [_item(c) for c in cc.get("crew") or [] if c.get("job") in ("Director", "Creator")],
        }}
    if re.fullmatch(r"/collection/\d+", path):
        return {**{k: v for k, v in data.items() if k != "parts"}, "parts": [_item(p) for p in data.get("parts") or []]}
    if path.startswith(("/trending/", "/discover/")) or path.endswith(("/recommendations", "/similar")):
        return {**data, "results": [_item(p) for p in data.get("results") or []]}
    return data


def _store(key: str, path: str, data: dict) -> None:
    _mem[key] = (time.time() + _ttl(path), data)
    _mem.move_to_end(key)
    while len(_mem) > _MEM_MAX:
        _mem.popitem(last=False)


class _Limiter:
    """Spaces requests at least 1/rate seconds apart (no lock needed: single event loop).

    Two lanes: a user's own tap (`hi`) is served first; background queue building (`lo`) takes
    the free slots and steps aside while a tap is waiting.
    """

    def __init__(self, rate: float):
        self.interval = 1.0 / rate
        self._next = 0.0
        self._hi = 0
        self._lo_lock = asyncio.Lock()

    async def wait(self, hi: bool = False) -> None:
        if hi:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + self.interval
            if start > now:
                self._hi += 1
                try:
                    await asyncio.sleep(start - now)
                finally:
                    self._hi -= 1
            return
        async with self._lo_lock:  # one background waiter polls; the rest queue behind it
            while True:
                now = time.monotonic()
                if not self._hi and now >= self._next:
                    self._next = now + self.interval
                    return
                await asyncio.sleep(self.interval)


_limiter = _Limiter(config.TMDB_RPS)


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10.0)
    return _client


def tmdb_lang(lang: str) -> str:
    return LANGS.get(lang, LANGS["en"])


async def _fetch(path: str, params: dict, lang: str, hi: bool = False) -> dict:
    if not config.TMDB_READ_TOKEN:
        raise HTTPException(500, "server misconfigured: TMDB_READ_TOKEN not set")
    q = {"language": tmdb_lang(lang), **params}
    headers = {"Authorization": f"Bearer {config.TMDB_READ_TOKEN}", "accept": "application/json"}
    for attempt in range(3):
        await _limiter.wait(hi)
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


async def _load(key: str, path: str, params: dict, lang: str, hi: bool, cache: bool) -> dict:
    data = await _fetch(path, params, lang, hi)
    if cache:
        data = _shrink(path, data)
        _store(key, path, data)
    return data


def _flight_done(key: str, fut: asyncio.Future) -> None:
    _inflight.pop(key, None)
    if not fut.cancelled():
        fut.exception()  # mark retrieved: a failed background refresh is not an error nobody awaited


async def tmdb_get(
    path: str, params: dict | None = None, *, lang: str = "en", cache: bool = True, hi: bool = False
) -> dict:
    """`hi`: the user is waiting on this call (opening a title), so it goes ahead of queue building."""
    params = params or {}
    key = f"{lang}|{path}|" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    hit = _mem.get(key) if cache else None
    stale = False
    if hit:
        expires, data = hit
        now = time.time()
        if expires > now:
            _mem.move_to_end(key)
            return data
        stale = now - expires < _STALE

    fut = _inflight.get(key)
    if fut is None:
        fut = asyncio.ensure_future(_load(key, path, params, lang, hi, cache))
        _inflight[key] = fut
        fut.add_done_callback(lambda f, k=key: _flight_done(k, f))
    if stale:  # serve the old copy now; the refresh fills the cache for the next caller
        _mem.move_to_end(key)
        return hit[1]
    return await asyncio.shield(fut)


async def warm_loop() -> None:
    """Keep the pages every user hits (trending, genres) fresh so nobody waits for them."""
    while True:
        try:
            for lang in LANGS:
                for kind in ("movie", "tv"):
                    await tmdb_get(f"/genre/{kind}/list", lang=lang)
                    for page in range(1, 5):
                        await tmdb_get(f"/trending/{kind}/week", {"page": page}, lang=lang)
        except Exception:  # never let a TMDb hiccup kill the loop
            pass
        await asyncio.sleep(3300)


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
        "companies": [
            {"id": c["id"], "name": c["name"], "logo": poster_url(c.get("logo_path"), "w185")}
            for c in (raw.get("production_companies") or [])[:6]
        ],
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
        "recommendations": [_item(p) for p in ((raw.get("recommendations") or {}).get("results") or [])[:20]],
    }


def _read_cached(media_type: str, tmdb_id: int, lang: str):
    """Runs in a worker thread with its own session, so the event loop never waits on MySQL."""
    with SessionLocal() as s:
        row = s.get(TitleCache, (media_type, tmdb_id, lang))
        return (row.data, row.refreshed_at) if row else None


def _write_cached(media_type: str, tmdb_id: int, lang: str, data: dict) -> None:
    """Upsert. Two requests for the same title can finish together (details and facts both ask),
    so a lost insert race is handled by updating the row the other one just wrote."""
    with SessionLocal() as s:
        for _ in range(2):
            row = s.get(TitleCache, (media_type, tmdb_id, lang))
            if row:
                row.data, row.refreshed_at = data, utcnow()
            else:
                s.add(TitleCache(media_type=media_type, tmdb_id=tmdb_id, lang=lang, data=data, refreshed_at=utcnow()))
            try:
                s.commit()
                return
            except IntegrityError:
                s.rollback()


async def get_details(db: Session, media_type: str, tmdb_id: int, lang: str = "en", hi: bool = False) -> dict:
    cached = await asyncio.to_thread(_read_cached, media_type, tmdb_id, lang)
    if cached and cached[0].get("v") == SLIM_VERSION and cached[1] > utcnow() - timedelta(days=config.CACHE_TTL_DAYS):
        return cached[0]

    try:
        raw = await tmdb_get(f"/{media_type}/{tmdb_id}", {"append_to_response": APPEND}, lang=lang, cache=False, hi=hi)
    except HTTPException as e:
        if cached and e.status_code != 404:
            return cached[0]  # stale beats failing
        raise
    data = _slim(raw, media_type)

    # French overviews are often empty: fall back to English for missing text.
    if lang != "en" and not data.get("overview"):
        try:
            en = await tmdb_get(f"/{media_type}/{tmdb_id}", {}, lang="en", hi=hi)
            data["overview"] = en.get("overview") or ""
            data["tagline"] = data.get("tagline") or en.get("tagline")
        except HTTPException:
            pass

    await asyncio.to_thread(_write_cached, media_type, tmdb_id, lang, data)
    return data


async def get_person(person_id: int, lang: str = "en") -> dict:
    """Bio, photo and best-known titles for one actor / director."""
    raw = await tmdb_get(f"/person/{person_id}", {"append_to_response": "combined_credits"}, lang=lang, hi=True)
    bio = raw.get("biography") or ""
    if lang != "en" and not bio:  # many French bios are empty: fall back to English
        try:
            bio = (await tmdb_get(f"/person/{person_id}", {}, lang="en", hi=True)).get("biography") or ""
        except HTTPException:
            pass
    credits = raw.get("combined_credits") or {}
    rows = [c for c in credits.get("cast", []) if c.get("order") is None or c["order"] < 10]
    rows += [c for c in credits.get("crew", []) if c.get("job") in ("Director", "Creator")]
    seen, known = set(), []
    for c in sorted(rows, key=lambda p: p.get("vote_count") or 0, reverse=True):
        key = (c.get("media_type"), c.get("id"))
        if c.get("media_type") not in ("movie", "tv") or key in seen or not c.get("poster_path"):
            continue
        seen.add(key)
        known.append(card(c, c["media_type"]))
        if len(known) >= 15:
            break
    return {
        "id": raw["id"],
        "name": raw.get("name"),
        "photo": poster_url(raw.get("profile_path"), "w342"),
        "department": raw.get("known_for_department"),
        "birthday": raw.get("birthday"),
        "deathday": raw.get("deathday"),
        "place": raw.get("place_of_birth"),
        "bio": bio[:1500],
        "known_for": known,
    }


async def get_company(company_id: int, lang: str = "en") -> dict:
    raw = await tmdb_get(f"/company/{company_id}", {}, lang=lang, hi=True)
    return {
        "id": raw["id"],
        "name": raw.get("name"),
        "logo": poster_url(raw.get("logo_path"), "w185"),
        "country": raw.get("origin_country"),
        "description": raw.get("description") or "",
    }
