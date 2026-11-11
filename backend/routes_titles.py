from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

import tmdb
import wiki
from auth import get_current_user
from database.connection import get_db
from database.models import User, UserTitle
from queue_builder import Filters, build_queue
from tmdb import card

router = APIRouter(tags=["titles"])
MediaType = Literal["movie", "tv"]


def _int_set(csv: str, what: str) -> set[int]:
    try:
        return {int(x) for x in csv.split(",") if x.strip()}
    except ValueError:
        raise HTTPException(422, f"{what} must be a comma-separated list of integers")


def _exclude(csv: str) -> set[tuple[str, int]]:
    out = set()
    for part in csv.split(","):
        mt, _, i = part.strip().partition(":")
        if mt in ("movie", "tv") and i.isdigit():
            out.add((mt, int(i)))
    return out


@router.get("/titles/queue")
async def queue(
    limit: int = Query(12, ge=1, le=30),
    media_type: Literal["all", "movie", "tv"] = "all",
    genres: str = "",
    year_min: int | None = Query(None, ge=1888, le=2100),
    year_max: int | None = Query(None, ge=1888, le=2100),
    min_rating: float | None = Query(None, ge=0, le=10),
    page: int = Query(1, ge=1, le=500),
    exclude: str = Query("", max_length=2000, description="comma list of 'movie:123' already on the client"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    filters = Filters(
        media_type=media_type, genres=_int_set(genres, "genres"),
        year_min=year_min, year_max=year_max, min_rating=min_rating,
    )
    return await build_queue(db, user, limit, filters, page=page, exclude=_exclude(exclude))


@router.get("/titles/{media_type}/{tmdb_id}")
async def title_details(
    media_type: MediaType, tmdb_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    data = await tmdb.get_details(db, media_type, tmdb_id, user.lang)
    mine = db.scalar(select(UserTitle).where(
        UserTitle.user_id == user.id, UserTitle.media_type == media_type, UserTitle.tmdb_id == tmdb_id))
    return {
        **card(data, media_type),
        "tagline": data.get("tagline"),
        "runtime": data.get("runtime") or (data.get("episode_run_time") or [None])[0],
        "genres": data.get("genres") or [],
        "number_of_seasons": data.get("number_of_seasons"),
        "cast": data.get("cast", []),
        "crew": data.get("crew", []),
        "videos": data.get("videos", []),
        "reviews": data.get("reviews", []),
        "providers": (data.get("providers") or {}).get(user.region),
        "region": user.region,
        "my_status": mine.status if mine else None,
        "my_rating": mine.rating if mine else None,
    }


@router.get("/titles/{media_type}/{tmdb_id}/facts")
async def title_facts(
    media_type: MediaType, tmdb_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """'Behind the scenes' from Wikipedia. Loaded only when the detail sheet opens."""
    data = await tmdb.get_details(db, media_type, tmdb_id, user.lang)
    return {"facts": await wiki.get_facts(db, media_type, tmdb_id, data.get("imdb_id"), user.lang)}


@router.get("/meta/genres")
async def genres(user: User = Depends(get_current_user)):
    movie = await tmdb.tmdb_get("/genre/movie/list", lang=user.lang)
    tv = await tmdb.tmdb_get("/genre/tv/list", lang=user.lang)
    return {"movie": movie.get("genres", []), "tv": tv.get("genres", [])}
