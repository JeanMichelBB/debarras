from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from auth import get_current_user
from database.connection import get_db
from database.models import STATUSES, User, UserTitle, utcnow
from tmdb import poster_path_from_url, poster_url

router = APIRouter(tags=["swipes"])
Status = Literal["watched", "want", "not_now"]


class SwipeIn(BaseModel):
    media_type: Literal["movie", "tv"]
    tmdb_id: int = Field(gt=0)
    status: Status
    # 1 = disliked, 2 = fine, 3 = loved; only kept for "watched"
    rating: int | None = Field(None, ge=1, le=3)
    # Display fields come from the card the user saw, so lists render without TMDb calls.
    title: str = Field("", max_length=255)
    year: str | None = Field(None, pattern=r"^\d{4}$")
    poster: str | None = Field(None, max_length=500)


def _item(r: UserTitle) -> dict:
    return {
        "tmdb_id": r.tmdb_id, "media_type": r.media_type, "imdb_id": r.imdb_id, "title": r.title,
        "year": r.year, "poster": poster_url(r.poster_path, "w342"), "status": r.status,
        "rating": r.rating, "decided_at": r.decided_at.isoformat(),
    }


def _find(db: Session, user: User, media_type: str, tmdb_id: int) -> UserTitle | None:
    return db.scalar(select(UserTitle).where(
        UserTitle.user_id == user.id, UserTitle.media_type == media_type, UserTitle.tmdb_id == tmdb_id))


@router.post("/swipe")
def swipe(body: SwipeIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Record or change a decision. Calling it again for the same title edits the decision."""
    row = _find(db, user, body.media_type, body.tmdb_id)
    path = poster_path_from_url(body.poster)
    if row is None:
        row = UserTitle(user_id=user.id, media_type=body.media_type, tmdb_id=body.tmdb_id)
        db.add(row)
    row.status = body.status
    row.rating = body.rating if body.status == "watched" else None
    if body.title:
        row.title = body.title
    if body.year:
        row.year = body.year
    if path:
        row.poster_path = path
    row.decided_at = utcnow()
    db.commit()
    return _item(row)


@router.delete("/swipe/{media_type}/{tmdb_id}", status_code=204)
def undo(media_type: Literal["movie", "tv"], tmdb_id: int,
         user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = _find(db, user, media_type, tmdb_id)
    if row is None:
        raise HTTPException(404, "no decision for this title")
    db.delete(row)
    db.commit()


@router.get("/swipes")
def list_swipes(
    status: Status | None = None,
    media_type: Literal["movie", "tv"] | None = None,
    q: str | None = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cond = [UserTitle.user_id == user.id]
    if status:
        cond.append(UserTitle.status == status)
    if media_type:
        cond.append(UserTitle.media_type == media_type)
    if q:
        cond.append(UserTitle.title.contains(q, autoescape=True))
    total = db.scalar(select(func.count()).select_from(UserTitle).where(*cond))
    rows = db.scalars(
        select(UserTitle).where(*cond).order_by(UserTitle.decided_at.desc(), UserTitle.id.desc())
        .limit(limit).offset(offset)
    ).all()
    return {"items": [_item(r) for r in rows], "total": total}


@router.get("/swipes/stats")
def stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    counts = dict(db.execute(
        select(UserTitle.status, func.count()).where(UserTitle.user_id == user.id).group_by(UserTitle.status)
    ).all())
    return {s: counts.get(s, 0) for s in STATUSES}
