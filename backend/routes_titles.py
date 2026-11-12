from typing import Literal

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

import login_posters
import tmdb
import wiki
from auth import get_current_user
from database.connection import get_db
from database.models import User, UserTitle
from ratelimit import rate_limit
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


@router.get("/titles/queue", dependencies=[Depends(rate_limit("queue", 120, 60))])
async def queue(
    limit: int = Query(12, ge=1, le=30),
    media_type: Literal["all", "movie", "tv"] = "all",
    genres: str = "",
    year_min: int | None = Query(None, ge=1888, le=2100),
    year_max: int | None = Query(None, ge=1888, le=2100),
    min_rating: float | None = Query(None, ge=0, le=10),
    page: int = Query(1, ge=1, le=500),
    source: Literal["mix", "related", "wild"] = "mix",
    shuffle: bool = False,
    person: int | None = Query(None, ge=1),
    company: int | None = Query(None, ge=1),
    like: str = Query("", max_length=40, description="'movie:123': only titles similar to this one"),
    exclude: str = Query("", max_length=2000, description="comma list of 'movie:123' already on the client"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    filters = Filters(
        media_type=media_type, genres=_int_set(genres, "genres"),
        year_min=year_min, year_max=year_max, min_rating=min_rating,
    )
    return await build_queue(db, user, limit, filters, page=page, exclude=_exclude(exclude), source=source, shuffle=shuffle, person=person, company=company,
                             like=next(iter(_exclude(like)), None))


@router.get("/titles/{media_type}/{tmdb_id}")
async def title_details(
    media_type: MediaType, tmdb_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    data = await tmdb.get_details(db, media_type, tmdb_id, user.lang, hi=True)
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
        "companies": data.get("companies", []),
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
    data = await tmdb.get_details(db, media_type, tmdb_id, user.lang, hi=True)
    return {"facts": await wiki.get_facts(db, media_type, tmdb_id, data.get("imdb_id"), user.lang)}


@router.get("/people/{person_id}")
async def person(person_id: int, response: Response, user: User = Depends(get_current_user)):
    response.headers["Cache-Control"] = "private, max-age=3600"
    return await tmdb.get_person(person_id, user.lang)


@router.get("/companies/{company_id}")
async def company(company_id: int, response: Response, user: User = Depends(get_current_user)):
    response.headers["Cache-Control"] = "private, max-age=3600"
    params = {"with_companies": company_id, "sort_by": "popularity.desc", "vote_count.gte": 50}
    info, movie, tv = await asyncio.gather(
        tmdb.get_company(company_id, user.lang),
        tmdb.tmdb_get("/discover/movie", params, lang=user.lang, hi=True),
        tmdb.tmdb_get("/discover/tv", params, lang=user.lang, hi=True),
    )
    items = []
    for i in range(max(len(movie.get("results", [])), len(tv.get("results", [])))):
        for res, mt in ((movie, "movie"), (tv, "tv")):
            if i < len(res.get("results", [])) and res["results"][i].get("poster_path"):
                items.append(card(res["results"][i], mt))
    return {**info, "titles": items[:20]}


@router.get("/public/login-posters", dependencies=[Depends(rate_limit("login-posters", 60, 60))])
def login_poster_picks(response: Response, db: Session = Depends(get_db)):
    """No sign-in needed: three different posters for the login cards, new picks on every visit."""
    response.headers["Cache-Control"] = "no-store"
    return {"posters": login_posters.pick(db, 3)}


@router.get("/meta/genres")
async def genres(response: Response, user: User = Depends(get_current_user)):
    response.headers["Cache-Control"] = "private, max-age=86400"
    movie = await tmdb.tmdb_get("/genre/movie/list", lang=user.lang, hi=True)
    tv = await tmdb.tmdb_get("/genre/tv/list", lang=user.lang, hi=True)
    return {"movie": movie.get("genres", []), "tv": tv.get("genres", [])}
