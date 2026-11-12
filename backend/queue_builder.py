"""Builds the swipe queue: finish franchises / follow directors first, then fillers.

Order: same franchise, same director, lead actors, TMDb recommendations, then filler
(trending, or /discover when filters are set). Titles the user already decided are
excluded. v1 treats "not_now" like any decided title; resurfacing them is phase 2.
"""

import asyncio
import random
from types import SimpleNamespace
from datetime import date as _date
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


async def _filler_page(lang: str, filters: Filters, page: int) -> list[tuple[dict, dict]]:
    types = [filters.media_type] if filters.media_type in ("movie", "tv") else ["movie", "tv"]
    reqs = []
    for t in types:
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
    reason = "Popular for your filters" if filters.use_discover else "Trending"
    lists = [
        [_pair(p, t, reason) for p in (r or {}).get("results", [])] for t, r in zip(types, results)
    ]
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
            queue.append(c)

    take(candidates)
    next_page = page
    for p in range(page, page + (MAX_FILLER_PAGES if source != "related" else 0)):
        if len(queue) >= cap:
            break
        take(await _filler_page(lang, filters, p))
        next_page = p + 1
    if shuffle and len(queue) > limit:
        queue = random.sample(queue, limit)
    if like:
        for c in queue:
            c["reason"] = (c.get("reason") or "").replace("Because you liked", "Similar to")
    return {"cards": queue, "next_page": next_page}
