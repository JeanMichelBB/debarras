"""Collections page: franchise browse with progress ("7 of 33 seen")."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

import tmdb
from auth import get_current_user
from collections_data import BY_KEY, COLLECTIONS
from database.connection import get_db
from database.models import User, UserTitle
from queue_builder import is_released
from tmdb import card

router = APIRouter(tags=["collections"])
FETCH_CONCURRENCY = 8


def _mine(db: Session, user: User) -> dict[tuple[str, int], str]:
    return {
        (r.media_type, r.tmdb_id): r.status
        for r in db.execute(select(UserTitle.media_type, UserTitle.tmdb_id, UserTitle.status).where(UserTitle.user_id == user.id))
    }


async def _safe(coro):
    try:
        return await coro
    except HTTPException:
        return None


async def _parts(entry: dict, lang: str, full: bool) -> tuple[str, list[dict]]:
    """(name, movie items) of one entry. With full=False, an id list returns bare ids (no TMDb call)."""
    name = (entry.get("name_fr") if lang == "fr" else None) or entry.get("name") or ""
    items: list[dict] = []
    if entry.get("collections"):
        found = await asyncio.gather(*(_safe(tmdb.tmdb_get(f"/collection/{c}", lang=lang)) for c in entry["collections"]))
        for res in found:
            if not res:
                continue
            name = name or res.get("name") or ""
            items += [p for p in res.get("parts", []) if p.get("poster_path") or not full]
    if entry.get("movies"):
        sem = asyncio.Semaphore(FETCH_CONCURRENCY)

        async def one(i: int):
            async with sem:
                return await _safe(tmdb.tmdb_get(f"/movie/{i}", lang=lang))

        if full:
            items += [m for m in await asyncio.gather(*(one(i) for i in entry["movies"])) if m]
        else:
            items += [{"id": i} for i in entry["movies"]]
    seen_ids: set[int] = set()
    out = []
    for p in items:  # a film can sit in two collections of one franchise
        if p["id"] not in seen_ids:
            seen_ids.add(p["id"])
            out.append(p)
    return name, out


def _released(p: dict) -> bool:
    return "release_date" not in p or is_released(p)  # a bare id (id list) counts as released


async def summaries(db: Session, user: User) -> list[dict]:
    mine = await asyncio.to_thread(_mine, db, user)

    async def one(entry: dict) -> dict | None:
        name, parts = await _parts(entry, user.lang, full=False)
        parts = [p for p in parts if _released(p)]
        if not parts:
            return None
        ids = {p["id"] for p in parts}
        seen = sum(1 for i in ids if mine.get(("movie", i)) == "watched")
        wanted = sum(1 for i in ids if mine.get(("movie", i)) == "want")
        poster = next((p.get("poster_path") for p in parts if p.get("poster_path")), None)
        if poster is None:  # an id list has no posters yet: the first film gives one
            first = await _safe(tmdb.tmdb_get(f"/movie/{parts[0]['id']}", lang=user.lang))
            poster = (first or {}).get("poster_path")
        return {
            "key": entry["key"], "name": name, "poster": tmdb.poster_url(poster, "w342"),
            "total": len(ids), "seen": seen, "want": wanted, "complete": seen == len(ids),
        }

    rows = [r for r in await asyncio.gather(*(one(e) for e in COLLECTIONS)) if r]
    # Started franchises first, nearest to done first; then the rest in table order.
    order = {r["key"]: i for i, r in enumerate(rows)}
    rows.sort(key=lambda r: (r["seen"] == 0, -(r["seen"] / r["total"]), order[r["key"]]))
    return rows


@router.get("/collections")
async def list_collections(response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return {"collections": await summaries(db, user)}


@router.get("/collections/{key}")
async def one_collection(key: str, response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    entry = BY_KEY.get(key)
    if entry is None:
        raise HTTPException(404, "unknown collection")
    mine = await asyncio.to_thread(_mine, db, user)
    name, parts = await _parts(entry, user.lang, full=True)
    parts.sort(key=lambda p: p.get("release_date") or "9999")
    items = []
    for p in parts:
        c = card(p, "movie")
        c["status"] = mine.get(("movie", p["id"]))
        c["released"] = is_released(p)
        items.append(c)
    counted = [i for i in items if i["released"]]
    return {
        "key": key, "name": name, "items": items, "total": len(counted),
        "seen": sum(1 for i in counted if i["status"] == "watched"),
    }
