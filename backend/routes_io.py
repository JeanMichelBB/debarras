"""Import (IMDb CSV, Letterboxd CSV, Trakt public profile) as a background job, and CSV export.

IMDb has no write API: users export their lists/ratings from IMDb, import them here, and
import this app's exported CSV into an IMDb custom list by hand.
"""

import asyncio
import csv
import io
import re
import secrets
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

import config
import httpx
import tmdb
from auth import get_current_user
from database.connection import SessionLocal, get_db
from database.models import STATUSES, ImportJob, User, UserTitle, utcnow
from ratelimit import rate_limit

router = APIRouter(tags=["import-export"])

MAX_BYTES = 5_000_000
MAX_ROWS = 3000
CHUNK = 50
IMPORT_CONCURRENCY = 10
EXPORT_CONCURRENCY = 15
CONST_RE = re.compile(r"^tt\d{5,12}$")


def imdb_rating_to_ours(n: int) -> int:
    """IMDb 1-10 -> 1 disliked, 2 fine, 3 loved."""
    return 3 if n >= 8 else 2 if n >= 5 else 1


def parse_imdb_csv(text: str) -> list[dict]:
    """Rows from an IMDb ratings/watchlist/list export. Needs a 'Const' column."""
    reader = csv.DictReader(io.StringIO(text))
    fields = {(f or "").strip().lower(): f for f in (reader.fieldnames or [])}
    if "const" not in fields:
        raise HTTPException(400, "this does not look like an IMDb export (no 'Const' column)")
    rating_col = fields.get("your rating")
    rows, seen = [], set()
    for rec in reader:
        const = (rec.get(fields["const"]) or "").strip()
        if not CONST_RE.match(const) or const in seen:
            continue
        seen.add(const)
        rating = None
        if rating_col and (rec.get(rating_col) or "").strip().isdigit():
            rating = imdb_rating_to_ours(int(rec[rating_col]))
        rows.append({"const": const, "rating": rating})
    return rows


def letterboxd_rating_to_ours(x: float) -> int:
    """Letterboxd 0.5-5 stars -> 1 disliked, 2 fine, 3 loved."""
    return 3 if x >= 4 else 2 if x >= 2.5 else 1


def parse_letterboxd_csv(text: str) -> list[dict]:
    """Rows from a Letterboxd export (watched.csv, ratings.csv or watchlist.csv). They have no IMDb ID,
    so each row is found on TMDb by title and year."""
    reader = csv.DictReader(io.StringIO(text))
    fields = {(f or "").strip().lower(): f for f in (reader.fieldnames or [])}
    rating_col = fields.get("rating")
    rows, seen = [], set()
    for rec in reader:
        name = (rec.get(fields["name"]) or "").strip()
        year = (rec.get(fields["year"]) or "").strip()
        key = (name.lower(), year)
        if not name or key in seen:
            continue
        seen.add(key)
        rating = None
        if rating_col:
            try:
                rating = letterboxd_rating_to_ours(float(rec.get(rating_col) or ""))
            except ValueError:
                rating = None
        rows.append({"name": name[:200], "year": int(year) if year.isdigit() else None, "rating": rating})
    return rows


def parse_csv(text: str) -> list[dict]:
    """IMDb or Letterboxd, told apart by their columns."""
    head = next(csv.reader(io.StringIO(text)), [])
    cols = {c.strip().lower() for c in head}
    if "const" in cols:
        return parse_imdb_csv(text)
    if "name" in cols and "year" in cols:
        return parse_letterboxd_csv(text)
    raise HTTPException(400, "this does not look like an IMDb or Letterboxd export")


def _csv_safe(value: str) -> str:
    """Stop spreadsheet formula injection when the CSV is opened in Excel/Sheets."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


async def _resolve(row: dict, lang: str):
    """The TMDb item behind one import row, as (media type, item), or None."""
    try:
        if row.get("const"):
            data = await tmdb.tmdb_get(f"/find/{row['const']}", {"external_source": "imdb_id"}, lang=lang)
            if data.get("movie_results"):
                return "movie", data["movie_results"][0]
            if data.get("tv_results"):
                return "tv", data["tv_results"][0]
            return None
        if row.get("tmdb"):  # Trakt gives the TMDb id directly
            return row["media_type"], await tmdb.tmdb_get(f"/{row['media_type']}/{row['tmdb']}", lang=lang)
        year = row.get("year")
        res = (await tmdb.tmdb_get("/search/movie", {"query": row["name"], "include_adult": "false",
                                                     **({"year": year} if year else {})}, lang=lang)).get("results", [])
        if not res and year:  # Letterboxd and TMDb sometimes differ by a year
            res = [r for r in (await tmdb.tmdb_get("/search/movie", {"query": row["name"], "include_adult": "false"},
                                                   lang=lang)).get("results", [])
                   if (r.get("release_date") or "0000")[:4].isdigit() and abs(int(r["release_date"][:4]) - year) <= 1]
        return ("movie", res[0]) if res else None
    except HTTPException:
        return None


async def _run_import(job_id: str, user_id: int, rows: list[dict], status: str, lang: str) -> None:
    """Rows may carry their own "status" (Trakt: watched and watchlist in one job); `status` is the default."""
    db = SessionLocal()
    try:
        job = db.get(ImportJob, job_id)
        existing = {
            (r.media_type, r.tmdb_id)
            for r in db.execute(select(UserTitle.media_type, UserTitle.tmdb_id).where(UserTitle.user_id == user_id))
        }
        sem = asyncio.Semaphore(IMPORT_CONCURRENCY)

        async def resolve(row: dict):
            async with sem:
                return row, await _resolve(row, lang)

        for i in range(0, len(rows), CHUNK):
            for row, hit in await asyncio.gather(*(resolve(r) for r in rows[i:i + CHUNK])):
                job.done += 1
                if hit is None:
                    job.not_found += 1
                    continue
                media_type, item = hit
                key = (media_type, item["id"])
                if key in existing:
                    job.skipped += 1
                    continue
                c = tmdb.card(item, media_type)
                st = row.get("status", status)
                db.add(UserTitle(
                    user_id=user_id, media_type=media_type, tmdb_id=item["id"], imdb_id=row.get("const"),
                    title=c["title"][:255], year=c["year"], poster_path=item.get("poster_path"),
                    genre_ids=c["genre_ids"] or None, release_date=c["release_date"],
                    status=st, rating=row.get("rating") if st == "watched" else None,
                    decided_at=utcnow(),
                ))
                existing.add(key)
                job.imported += 1
            db.commit()
        job.status = "done"
        db.commit()
    except Exception as e:  # noqa: BLE001 - job must always end in a terminal state
        db.rollback()
        job = db.get(ImportJob, job_id)
        if job:
            job.status, job.error = "failed", str(e)[:255]
            db.commit()
    finally:
        db.close()


@router.post("/import", status_code=202, dependencies=[Depends(rate_limit("import", 5, 3600))])
async def start_import(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    status: Literal["watched", "want", "not_now"] = Form("watched"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    raw = await file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, "file too large")
    rows = parse_csv(raw.decode("utf-8-sig", errors="replace"))
    if not rows:
        raise HTTPException(400, "no titles found in this file")
    if len(rows) > MAX_ROWS:
        raise HTTPException(400, f"too many rows (max {MAX_ROWS}); split the file")
    job = ImportJob(id=secrets.token_hex(16), user_id=user.id, total=len(rows))
    db.add(job)
    db.commit()
    background.add_task(_run_import, job.id, user.id, rows, status, user.lang)
    return {"job_id": job.id, "total": len(rows)}


TRAKT_API = "https://api.trakt.tv"
TRAKT_USER_RE = re.compile(r"^[A-Za-z0-9_-]{1,50}$")


async def trakt_get(path: str):
    """One call to Trakt's public API. A private or unknown profile is a 400 for the user, not a crash."""
    headers = {"trakt-api-version": "2", "trakt-api-key": config.TRAKT_CLIENT_ID, "User-Agent": config.WIKI_USER_AGENT}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(TRAKT_API + path, headers=headers, params={"limit": 5000})
    except httpx.HTTPError:
        raise HTTPException(502, "Trakt unreachable")
    if r.status_code in (401, 403, 404):
        raise HTTPException(400, "Trakt profile not found, or it is private")
    if r.status_code != 200:
        raise HTTPException(502, f"Trakt error {r.status_code}")
    return r.json()


async def trakt_rows(username: str) -> list[dict]:
    """Seen titles (with ratings) and the watchlist of a public Trakt profile."""
    u = f"/users/{username}"
    watched_m, watched_s, wl_m, wl_s, rate_m, rate_s = await asyncio.gather(
        trakt_get(f"{u}/watched/movies"), trakt_get(f"{u}/watched/shows"),
        trakt_get(f"{u}/watchlist/movies"), trakt_get(f"{u}/watchlist/shows"),
        trakt_get(f"{u}/ratings/movies"), trakt_get(f"{u}/ratings/shows"),
    )
    ratings = {}
    for entries, kind, mt in ((rate_m, "movie", "movie"), (rate_s, "show", "tv")):
        for e in entries:
            tid = (e.get(kind) or {}).get("ids", {}).get("tmdb")
            if tid and e.get("rating"):
                ratings[(mt, tid)] = imdb_rating_to_ours(int(e["rating"]))
    rows, seen = [], set()
    for entries, kind, mt, status in ((watched_m, "movie", "movie", "watched"), (watched_s, "show", "tv", "watched"),
                                       (wl_m, "movie", "movie", "want"), (wl_s, "show", "tv", "want")):
        for e in entries:
            tid = (e.get(kind) or {}).get("ids", {}).get("tmdb")
            if not tid or (mt, tid) in seen:
                continue
            seen.add((mt, tid))  # watched comes first, so a seen title is never also "want"
            rows.append({"tmdb": tid, "media_type": mt, "status": status, "rating": ratings.get((mt, tid))})
    return rows


class TraktIn(BaseModel):
    username: str


@router.get("/import/sources")
def import_sources():
    return {"trakt": bool(config.TRAKT_CLIENT_ID)}


@router.post("/import/trakt", status_code=202, dependencies=[Depends(rate_limit("import", 5, 3600))])
async def start_trakt_import(
    body: TraktIn, background: BackgroundTasks, user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    if not config.TRAKT_CLIENT_ID:
        raise HTTPException(503, "Trakt import is not set up on this server")
    name = body.username.strip().lstrip("@")
    if not TRAKT_USER_RE.match(name):
        raise HTTPException(422, "that is not a Trakt username")
    rows = await trakt_rows(name)
    if not rows:
        raise HTTPException(400, "no titles found on this Trakt profile")
    if len(rows) > MAX_ROWS:
        raise HTTPException(400, f"too many titles (max {MAX_ROWS})")
    job = ImportJob(id=secrets.token_hex(16), user_id=user.id, total=len(rows))
    db.add(job)
    db.commit()
    background.add_task(_run_import, job.id, user.id, rows, "watched", user.lang)
    return {"job_id": job.id, "total": len(rows)}


@router.get("/import/{job_id}")
def import_status(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = db.get(ImportJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(404, "import not found")
    return {
        "job_id": job.id, "status": job.status, "total": job.total, "done": job.done,
        "imported": job.imported, "skipped": job.skipped, "not_found": job.not_found, "error": job.error,
    }


@router.get("/export/{status}")
async def export_bucket(
    status: Literal["watched", "want", "not_now", "all", "rewatch"],
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """CSV for IMDb list import (needs the 'Const' column). Missing IMDb IDs are resolved lazily."""
    cond = [UserTitle.user_id == user.id]
    if status == "rewatch":
        cond.append(UserTitle.rewatch.is_(True))
    elif status != "all":
        cond.append(UserTitle.status == status)
    rows = db.scalars(select(UserTitle).where(*cond).order_by(UserTitle.decided_at, UserTitle.id)).all()

    sem = asyncio.Semaphore(EXPORT_CONCURRENCY)

    async def resolve(r: UserTitle):
        async with sem:
            try:
                d = await tmdb.tmdb_get(f"/{r.media_type}/{r.tmdb_id}/external_ids", lang="en")
                return r, d.get("imdb_id")
            except HTTPException:
                return r, None

    for r, imdb in await asyncio.gather(*(resolve(r) for r in rows if not r.imdb_id)):
        if imdb:
            r.imdb_id = imdb
    db.commit()

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Const", "Title", "Year"])
    missing = 0
    for r in rows:
        if r.imdb_id:
            writer.writerow([r.imdb_id, _csv_safe(r.title), r.year or ""])
        else:
            missing += 1
    return Response(
        out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="debarras-{status}.csv"',
            "X-Missing-Imdb": str(missing),
            "Access-Control-Expose-Headers": "X-Missing-Imdb, Content-Disposition",
        },
    )
