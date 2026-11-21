"""Private calendar feed (ICS): the release day of every Want title that is not out yet.

The link holds a long random token. Anyone with the link can read the feed, so it lists titles
only, and the user can replace or remove the link at any time.
"""

import asyncio
import secrets
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

import tmdb
from auth import get_current_user
from database.connection import get_db
from database.models import User, UserTitle
from ratelimit import rate_limit

router = APIRouter(tags=["calendar"])
BACKFILL_MAX = 25  # titles saved before release dates were kept get their date from TMDb, a few per request
DOMAIN = "debarras.sacenpapier.org"
LINE = {"en": "Out today. Added from your Want list in Débarras.", "fr": "Sort aujourd'hui. Ajouté depuis votre liste À voir dans Débarras."}


def _path(token: str) -> str:
    return f"/calendar/{token}.ics"


@router.get("/me/calendar")
def calendar_link(user: User = Depends(get_current_user)):
    return {"path": _path(user.cal_token) if user.cal_token else None}


@router.post("/me/calendar", dependencies=[Depends(rate_limit("calendar-link", 10, 3600))])
def new_calendar_link(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create the link, or replace it (the old link stops working)."""
    user.cal_token = secrets.token_urlsafe(32)
    db.add(user)
    db.commit()
    return {"path": _path(user.cal_token)}


@router.delete("/me/calendar", status_code=204)
def remove_calendar_link(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.cal_token = None
    db.add(user)
    db.commit()


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def _fold(line: str) -> list[str]:
    """RFC 5545: lines are at most 75 octets; a longer one continues on the next line after a space."""
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode())
        if size + n > (75 if not out else 74):
            out.append(cur)
            cur, size = "", 0
        cur += ch
        size += n
    out.append(cur)
    return [out[0]] + [" " + x for x in out[1:]]


def build_ics(events: list[tuple[str, str, str, str]], name: str, stamp: datetime) -> str:
    """events: (uid, title, yyyy-mm-dd, description)."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//{DOMAIN}//Debarras//EN", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{_escape(name)}"]
    for uid, title, day, desc in events:
        d = date.fromisoformat(day)
        lines += [
            "BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp.strftime('%Y%m%dT%H%M%SZ')}",
            f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}", f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}",
            f"SUMMARY:{_escape(title)}", f"DESCRIPTION:{_escape(desc)}", "TRANSP:TRANSPARENT", "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(part for line in lines for part in _fold(line)) + "\r\n"


async def _backfill(db: Session, rows: list[UserTitle], lang: str) -> None:
    """Fill the release date of Want titles saved before the date was kept. Cached details make this cheap."""
    year = date.today().year
    todo = [r for r in rows if not r.release_date and (not r.year or int(r.year) >= year)][:BACKFILL_MAX]
    sem = asyncio.Semaphore(8)

    async def one(r: UserTitle):
        async with sem:
            try:
                data = await tmdb.get_details(db, r.media_type, r.tmdb_id, lang)
            except HTTPException:
                return
            r.release_date = tmdb.card(data, r.media_type)["release_date"]

    await asyncio.gather(*(one(r) for r in todo))
    if todo:
        db.commit()


@router.get("/calendar/{token}.ics", dependencies=[Depends(rate_limit("calendar-feed", 60, 3600))])
async def feed(token: str, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.cal_token == token)) if len(token) >= 32 else None
    if user is None:
        raise HTTPException(404, "unknown calendar link")
    rows = db.scalars(select(UserTitle).where(UserTitle.user_id == user.id, UserTitle.status == "want")).all()
    await _backfill(db, rows, user.lang)
    today = date.today().isoformat()
    desc = LINE.get(user.lang, LINE["en"])
    events = [
        (f"{r.media_type}-{r.tmdb_id}@{DOMAIN}", r.title or f"{r.media_type} {r.tmdb_id}", r.release_date, desc)
        for r in sorted(rows, key=lambda r: r.release_date or "")
        if r.release_date and r.release_date >= today
    ]
    body = build_ics(events, "Débarras", datetime.now(timezone.utc))
    return Response(body, media_type="text/calendar; charset=utf-8",
                    headers={"Cache-Control": "private, max-age=900", "Content-Disposition": 'inline; filename="debarras.ics"'})
