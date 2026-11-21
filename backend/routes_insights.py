"""Taste card and quiet badges. Plain counting over the user's own decisions, no LLM."""

import asyncio
from collections import Counter

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

import routes_collections
from auth import get_current_user
from database.connection import get_db
from database.models import TitleCache, User, UserTitle
from queue_builder import _genre_names

router = APIRouter(tags=["insights"])

TASTE_AT = 25   # the taste card appears
FULL_AT = 100   # the fuller card (director, actor) appears
MILESTONES = (25, 100, 500)
DECADES = (1970, 1980, 1990, 2000, 2010, 2020)
REWATCH_LOVER = 5


def _rows(db: Session, user_id: int):
    return db.execute(
        select(UserTitle.media_type, UserTitle.tmdb_id, UserTitle.status, UserTitle.year,
               UserTitle.genre_ids, UserTitle.rewatch).where(UserTitle.user_id == user_id)
    ).all()


def _people(db: Session, liked: list[tuple[str, int]]) -> list[dict]:
    """Most frequent directors and lead actors among liked titles. Uses details already in the cache."""
    if not liked:
        return []
    names: Counter = Counter()
    for i in range(0, len(liked), 400):
        chunk = liked[i:i + 400]
        wanted = set(chunk)
        for row in db.scalars(select(TitleCache).where(TitleCache.tmdb_id.in_([c[1] for c in chunk]))):
            if (row.media_type, row.tmdb_id) not in wanted:
                continue
            data = row.data or {}
            for c in data.get("crew", []):
                if c.get("job") in ("Director", "Creator"):
                    names[(c["name"], "director")] += 1
            for c in data.get("cast", [])[:3]:
                names[(c["name"], "actor")] += 1
    best: dict[str, dict] = {}
    for (name, role), n in names.most_common():
        if n >= 2 and role not in best:
            best[role] = {"name": name, "role": role, "n": n}
    return list(best.values())


@router.get("/me/taste")
async def taste(response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    rows = await asyncio.to_thread(_rows, db, user.id)
    count = len(rows)
    liked = [r for r in rows if r.status in ("watched", "want")]
    genre_count: Counter = Counter()
    decades: Counter = Counter()
    for r in liked:
        genre_count.update(r.genre_ids or [])
        if r.year and r.year.isdigit():
            decades[int(r.year) // 10 * 10] += 1
    names = await _genre_names(user.lang) if genre_count else {}
    genres = [{"id": g, "name": names.get(g, ""), "n": n} for g, n in genre_count.most_common(8) if names.get(g)][:3]
    out = {
        "count": count, "ready": count >= TASTE_AT, "full": count >= FULL_AT,
        "genres": genres,
        "decade": decades.most_common(1)[0][0] if decades else None,
        "movies": sum(1 for r in liked if r.media_type == "movie"),
        "tv": sum(1 for r in liked if r.media_type == "tv"),
        "keep_percent": round(100 * len(liked) / count) if count else 0,
        "people": [],
    }
    if count >= FULL_AT:
        out["people"] = await asyncio.to_thread(_people, db, [(r.media_type, r.tmdb_id) for r in liked])
    return out


@router.get("/me/badges")
async def badges(response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Marks earned so far, from existing swipes only. Each one has its progress, so a quiet
    row can show how near the next one is."""
    response.headers["Cache-Control"] = "no-store"
    rows = await asyncio.to_thread(_rows, db, user.id)
    count = len(rows)
    out = [{"key": f"swipes-{n}", "have": min(count, n), "need": n, "earned": count >= n} for n in MILESTONES]
    seen_decades = {
        int(r.year) // 10 * 10 for r in rows
        if r.status == "watched" and r.media_type == "movie" and r.year and r.year.isdigit()
    }
    have = len(seen_decades & set(DECADES))
    out.append({"key": "every-decade", "have": have, "need": len(DECADES), "earned": have == len(DECADES)})
    rewatch = sum(1 for r in rows if r.rewatch)
    out.append({"key": "rewatch-lover", "have": min(rewatch, REWATCH_LOVER), "need": REWATCH_LOVER,
                "earned": rewatch >= REWATCH_LOVER})
    # Only a user who has seen something can have finished a franchise: skip the TMDb calls otherwise.
    done = []
    if any(r.status == "watched" for r in rows):
        done = [{"key": c["key"], "name": c["name"]} for c in await routes_collections.summaries(db, user) if c["complete"]]
    return {"badges": out, "collections": done}
