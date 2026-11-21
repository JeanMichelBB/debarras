"""Builds the swipe queue: finish franchises / follow directors first, then fillers.

Order: same franchise, same director, lead actors, TMDb recommendations, then filler
(well-known titles for a new user, then trending, or /discover when filters are set). Titles the user already decided are
excluded. v1 treats "not_now" like any decided title; resurfacing them is phase 2.
"""

import asyncio
import random
from types import SimpleNamespace
from datetime import date as _date, timedelta
from dataclasses import dataclass, field

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

import tmdb
from database.models import User, UserTitle
from tmdb import card

SEED_COUNT = 3        # most recent liked titles used to seed related picks
CAST_PER_SEED = 2     # lead actors followed per seed
PER_PERSON = 6        # titles taken per director / actor / recommendation list
MIN_VOTES = 50        # skip near-unrated entries (cutscene compilations, stubs, bad data)
FRESH_UNTIL = 30      # a user with fewer decided titles still gets the well-known picks first
MAX_FILLER_PAGES = 4  # filler pages fetched per call when many titles are already decided


@dataclass
class Filters:
    media_type: str = "all"
    genres: set[int] = field(default_factory=set)
    year_min: int | None = None
    year_max: int | None = None
    min_rating: float | None = None

    @property
    def use_discover(self) -> bool:
        return bool(self.genres or self.year_min or self.year_max or self.min_rating is not None)

    def accepts(self, item: dict, media_type: str) -> bool:
        if self.media_type in ("movie", "tv") and media_type != self.media_type:
            return False
        if self.genres and not (self.genres & set(item.get("genre_ids") or [])):
            return False
        if self.year_min or self.year_max:
            date = item.get("release_date") or item.get("first_air_date") or ""
            if not date[:4].isdigit():
                return False
            year = int(date[:4])
            if (self.year_min and year < self.year_min) or (self.year_max and year > self.year_max):
                return False
        if self.min_rating is not None and (item.get("vote_average") or 0) < self.min_rating:
            return False
        return True


def is_released(item: dict, today: _date | None = None) -> bool:
    """False for announced-but-unreleased titles (no date, or a date in the future)."""
    d = item.get("release_date") or item.get("first_air_date") or ""
    try:
        return _date.fromisoformat(d[:10]) <= (today or _date.today())
    except ValueError:
        return False


async def _safe(coro):
    try:
        return await coro
    except HTTPException:
        return None


def _pair(item: dict, media_type: str, reason: str) -> tuple[dict, dict]:
    return card(item, media_type, reason), item


async def _from_seed(db: Session, seed: UserTitle, lang: str, wide: bool = False) -> dict[str, list]:
    """Related candidates for one seed title, grouped by source strength."""
    out: dict[str, list] = {"franchise": [], "director": [], "cast": [], "similar": []}
    try:
        details = await tmdb.get_details(db, seed.media_type, seed.tmdb_id, lang)
    except HTTPException:
        return out

    if seed.media_type == "movie":
        tasks = []
        coll = details.get("belongs_to_collection")
        if coll:
            tasks.append(("franchise", coll["name"], _safe(tmdb.tmdb_get(f"/collection/{coll['id']}", lang=lang))))
        for crew in [c for c in details["crew"] if c["job"] == "Director"][:1]:
            tasks.append(("director", f"By {crew['name']}",
                          _safe(tmdb.tmdb_get(f"/person/{crew['id']}/movie_credits", lang=lang))))
        for actor in details["cast"][:CAST_PER_SEED]:
            tasks.append(("cast", f"With {actor['name']}",
                          _safe(tmdb.tmdb_get(f"/person/{actor['id']}/movie_credits", lang=lang))))
        results = await asyncio.gather(*(t[2] for t in tasks))
        for (kind, label, _), res in zip(tasks, results):
            if not res:
                continue
            if kind == "franchise":
                parts = sorted(res.get("parts", []), key=lambda p: p.get("release_date") or "9999")
                out["franchise"] += [_pair(p, "movie", f"Same franchise: {label}") for p in parts]
            elif kind == "director":
                items = [c for c in res.get("crew", []) if c.get("job") == "Director"]
                items.sort(key=lambda p: p.get("vote_count", 0), reverse=True)
                out["director"] += [_pair(p, "movie", label) for p in items[:PER_PERSON]]
            else:
                items = sorted(res.get("cast", []), key=lambda p: p.get("vote_count", 0), reverse=True)
                out["cast"] += [_pair(p, "movie", label) for p in items[:PER_PERSON]]

    n = 20 if wide else PER_PERSON
    name = details.get("title") or details.get("name")
    why = f"Because you liked {name}"
    # Recommendations arrive with the cached details (no extra call); only "similar" needs its own.
    out["similar"] += [_pair(p, seed.media_type, why) for p in (details.get("recommendations") or [])[:n]]
    if wide:
        sim = await _safe(tmdb.tmdb_get(f"/{seed.media_type}/{seed.tmdb_id}/similar", lang=lang))
        if sim:
            out["similar"] += [_pair(p, seed.media_type, why) for p in sim.get("results", [])[:n]]
    return out


# A film needs this many TMDb votes to count as "everyone has heard of it".
_WELL_KNOWN_VOTES = {"movie": 3000, "tv": 1000}
DECADES = range(1970, 2030, 10)


def _mainstream_requests(lang: str, t: str, page: int) -> list[tuple[str, object]]:
    """Well-known titles for a new user, as (media type, request) pairs.

    Movies: one query per decade, by box office and by vote count. Without the decade, the all-time
    lists are mostly recent films and the 1970s to 1990s hits never show up.
    Series: by vote count and by popularity."""
    base = {"page": page, "include_adult": "false"}
    out = []
    if t == "movie":
        for d in DECADES:
            span = {"primary_release_date.gte": f"{d}-01-01", "primary_release_date.lte": f"{d + 9}-12-31"}
            for sort, floor in (("revenue.desc", 2000), ("vote_count.desc", 1000)):
                params = {**base, **span, "sort_by": sort, "vote_count.gte": floor}
                out.append((t, _safe(tmdb.tmdb_get("/discover/movie", params, lang=lang))))
    else:
        for sort in ("vote_count.desc", "popularity.desc"):
            params = {**base, "sort_by": sort, "vote_count.gte": _WELL_KNOWN_VOTES["tv"]}
            out.append((t, _safe(tmdb.tmdb_get("/discover/tv", params, lang=lang))))
    return out


async def _filler_page(lang: str, filters: Filters, page: int, mainstream: bool = False) -> list[tuple[dict, dict]]:
    types = [filters.media_type] if filters.media_type in ("movie", "tv") else ["movie", "tv"]
    reqs = []
    names: list[str] = []
    for t in types:
        if mainstream and not filters.use_discover:
            for name, req in _mainstream_requests(lang, t, page):
                names.append(name)
                reqs.append(req)
            continue
        names.append(t)
        if filters.use_discover:
            date_key = "primary_release_date" if t == "movie" else "first_air_date"
            params = {"page": page, "include_adult": "false", "sort_by": "popularity.desc", "vote_count.gte": 100}
            if filters.genres:
                params["with_genres"] = "|".join(str(g) for g in sorted(filters.genres))
            if filters.year_min:
                params[f"{date_key}.gte"] = f"{filters.year_min}-01-01"
            if filters.year_max:
                params[f"{date_key}.lte"] = f"{filters.year_max}-12-31"
            if filters.min_rating is not None:
                params["vote_average.gte"] = filters.min_rating
            reqs.append(_safe(tmdb.tmdb_get(f"/discover/{t}", params, lang=lang)))
        else:
            reqs.append(_safe(tmdb.tmdb_get(f"/trending/{t}/week", {"page": page}, lang=lang)))
    results = await asyncio.gather(*reqs)
    reason = "Popular for your filters" if filters.use_discover else ("Popular" if mainstream else "Trending")
    lists = [
        [_pair(p, t, reason) for p in (r or {}).get("results", [])] for t, r in zip(names, results)
    ]
    if mainstream and not filters.use_discover:
        # Movies have one list per decade, series have two. Mix each kind at random, then alternate
        # one movie, one series, so decades are mixed and the two kinds stay balanced.
        by_kind: dict[str, list] = {t: [] for t in types}
        for n, lst in zip(names, lists):
            by_kind[n] += lst
        for kind_list in by_kind.values():
            random.shuffle(kind_list)
        lists = list(by_kind.values())
    out = []
    for i in range(max((len(x) for x in lists), default=0)):  # interleave movies and TV
        for lst in lists:
            if i < len(lst):
                out.append(lst[i])
    return out


def _load_state(db: Session, user_id: int, seed_count: int) -> tuple[set[tuple[str, int]], list]:
    """Two quick queries, run in a worker thread so the event loop keeps serving other users."""
    decided = {
        (r.media_type, r.tmdb_id)
        for r in db.execute(select(UserTitle.media_type, UserTitle.tmdb_id).where(UserTitle.user_id == user_id))
    }
    seeds = db.scalars(
        select(UserTitle)
        .where(UserTitle.user_id == user_id, UserTitle.status.in_(("watched", "want")))
        .where((UserTitle.rating.is_(None)) | (UserTitle.rating > 1))
        .order_by(UserTitle.decided_at.desc())
        .limit(seed_count)
    ).all() if seed_count else []
    return decided, seeds


async def _genre_names(lang: str) -> dict[int, str]:
    """Genre id -> name for movies and TV (cached for a day, so this costs no extra call in practice)."""
    lists = await asyncio.gather(*(_safe(tmdb.tmdb_get(f"/genre/{k}/list", lang=lang)) for k in ("movie", "tv")))
    return {g["id"]: g["name"] for res in lists for g in (res or {}).get("genres", [])}


async def build_queue(
    db: Session, user: User, limit: int, filters: Filters, page: int = 1, exclude: set[tuple[str, int]] | None = None,
    source: str = "mix", like: tuple[str, int] | None = None, shuffle: bool = False, person: int | None = None, company: int | None = None,
) -> dict:
    """source: "mix" = related first then filler, "related" = only titles related to liked ones,
    "wild" = filler only (ignores what the user liked)."""
    lang = user.lang
    if person or company:  # "more from this person / studio": only their titles, ignoring saved filters
        filters, source = Filters(), "related"
    if like:  # "more like this title": related to that one title only, ignoring saved filters
        filters, source = Filters(), "related"
    decided, found = await asyncio.to_thread(_load_state, db, user.id, 0 if like or source == "wild" else SEED_COUNT)
    skip = decided | (exclude or set())
    fresh = len(decided) < FRESH_UNTIL  # new user: start with titles everyone knows
    genre_names = await _genre_names(lang)

    seeds = [SimpleNamespace(media_type=like[0], tmdb_id=like[1])] if like else found
    if like:
        skip = skip | {like}

    extra: list[tuple[dict, dict]] = []
    if person:
        credits = await _safe(tmdb.tmdb_get(f"/person/{person}/combined_credits", lang=lang)) or {}
        who = await _safe(tmdb.tmdb_get(f"/person/{person}", lang=lang)) or {}
        reason = f"Work by {who.get('name', '')}".strip()
        rows = [c for c in credits.get("cast", []) if c.get("order") is None or c["order"] < 10]
        rows += [c for c in credits.get("crew", []) if c.get("job") in ("Director", "Creator")]
        rows.sort(key=lambda p: p.get("vote_count", 0), reverse=True)
        extra = [_pair(p, p.get("media_type"), reason) for p in rows if p.get("media_type") in ("movie", "tv")]
    if company:
        who = await _safe(tmdb.tmdb_get(f"/company/{company}", lang=lang)) or {}
        reason = f"From {who.get('name', '')}".strip()
        lists = await asyncio.gather(*(
            _safe(tmdb.tmdb_get(f"/discover/{t}", {"with_companies": company, "sort_by": "popularity.desc",
                                                    "vote_count.gte": MIN_VOTES, "page": page}, lang=lang))
            for t in ("movie", "tv")))
        per = [[_pair(p, t, reason) for p in (r or {}).get("results", [])] for t, r in zip(("movie", "tv"), lists)]
        for i in range(max((len(x) for x in per), default=0)):  # interleave movies and TV
            extra += [x[i] for x in per if i < len(x)]

    grouped: dict[str, list] = {"franchise": [], "director": [], "cast": [], "similar": []}
    for res in await asyncio.gather(*(_from_seed(db, s, lang, wide=bool(like)) for s in ([] if (person or company) else seeds))):
        for k, v in res.items():
            grouped[k] += v
    candidates = grouped["franchise"] + grouped["director"] + grouped["cast"] + grouped["similar"]
    if person or company:
        candidates = extra
    if like:  # recommendations are the closest match for a single title, so they go before people
        candidates = grouped["franchise"] + grouped["similar"] + grouped["director"] + grouped["cast"]

    queue: list[dict] = []
    cap = limit * 3 if shuffle else limit  # shuffle: gather extra, then pick `limit` at random
    seen: set[tuple[str, int]] = set()

    def take(pairs: list[tuple[dict, dict]]) -> None:
        for c, raw in pairs:
            key = (c["media_type"], c["tmdb_id"])
            if len(queue) >= cap:
                return
            if key in skip or key in seen or c["media_type"] not in ("movie", "tv"):
                continue
            if not raw.get("poster_path") or not is_released(raw) or (raw.get("vote_count") or 0) < MIN_VOTES or not filters.accepts(raw, c["media_type"]):
                continue
            seen.add(key)
            c["genres"] = [genre_names[g] for g in (raw.get("genre_ids") or []) if g in genre_names][:2]
            queue.append(c)

    take(candidates)
    next_page = page
    for p in range(page, page + (MAX_FILLER_PAGES if source != "related" else 0)):
        if len(queue) >= cap:
            break
        take(await _filler_page(lang, filters, p, mainstream=fresh))
        # A new user's page holds far more well-known titles than one batch uses. Stay on it until it
        # is used up, so the best titles of each decade are not skipped.
        next_page = p if (fresh and not filters.use_discover and len(queue) >= cap) else p + 1
    if shuffle and len(queue) > limit:
        queue = random.sample(queue, limit)
    if like:
        for c in queue:
            c["reason"] = (c.get("reason") or "").replace("Because you liked", "Similar to")
    return {"cards": queue, "next_page": next_page}


# ── Coming soon ──────────────────────────────────────────────────────────────
SOON_DAYS = 365       # look this far ahead
SOON_PAGES = 3        # TMDb sorts by popularity, so the first pages hold the titles people wait for
_JUNK_TITLE = ("untitled", "tbd", "tba", "to be announced", "sans titre")
_JUNK_TV_GENRES = "10767|10763|10764"  # talk, news, reality: not something to plan a watch around


def _is_junk_soon(raw: dict) -> bool:
    title = (raw.get("title") or raw.get("name") or "").strip().lower()
    return (
        not raw.get("poster_path") or not (raw.get("overview") or "").strip()
        or not title or any(title.startswith(j) for j in _JUNK_TITLE)
    )


async def build_soon(user: User, limit: int, page: int = 1, skip: set[tuple[str, int]] | None = None) -> dict:
    """Titles that come out within the next year, most awaited first. Never mixed into the normal pile.

    Movies need a confirmed theatrical date in the user's region (release type 2 or 3). Series need a
    first air date in the window and are not talk, news or reality shows."""
    today = _date.today()
    start, end = today.isoformat(), (today + timedelta(days=SOON_DAYS)).isoformat()
    skip = skip or set()
    movie = {"sort_by": "popularity.desc", "include_adult": "false", "region": user.region,
             "with_release_type": "2|3", "release_date.gte": start, "release_date.lte": end}
    tv = {"sort_by": "popularity.desc", "include_adult": "false", "first_air_date.gte": start,
          "first_air_date.lte": end, "without_genres": _JUNK_TV_GENRES}
    genre_names = await _genre_names(user.lang)
    cards: list[dict] = []
    seen: set[tuple[str, int]] = set()
    p = page
    for p in range(page, page + SOON_PAGES):
        res = await asyncio.gather(
            _safe(tmdb.tmdb_get("/discover/movie", {**movie, "page": p}, lang=user.lang)),
            _safe(tmdb.tmdb_get("/discover/tv", {**tv, "page": p}, lang=user.lang)),
        )
        lists = [[(raw, kind) for raw in (r or {}).get("results", [])] for r, kind in zip(res, ("movie", "tv"))]
        for i in range(max((len(x) for x in lists), default=0)):  # one movie, one series
            for lst in lists:
                if i >= len(lst):
                    continue
                raw, kind = lst[i]
                key = (kind, raw["id"])
                date = raw.get("release_date") or raw.get("first_air_date") or ""
                if key in skip or key in seen or _is_junk_soon(raw) or not (start <= date[:10] <= end):
                    continue
                seen.add(key)
                c = card(raw, kind, "Coming soon")
                c["upcoming"] = True
                c["genres"] = [genre_names[g] for g in (raw.get("genre_ids") or []) if g in genre_names][:2]
                cards.append(c)
        if len(cards) >= limit:
            break
    cards.sort(key=lambda c: c["release_date"] or "")  # soonest first
    return {"cards": cards[:limit], "next_page": p + 1}
