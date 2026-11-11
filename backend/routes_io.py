"""IMDb CSV import (background job) and per-bucket CSV export.

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
from sqlalchemy import select
from sqlalchemy.orm import Session

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


def _csv_safe(value: str) -> str:
    """Stop spreadsheet formula injection when the CSV is opened in Excel/Sheets."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


async def _run_import(job_id: str, user_id: int, rows: list[dict], status: str, lang: str) -> None:
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
                try:
                    data = await tmdb.tmdb_get(f"/find/{row['const']}", {"external_source": "imdb_id"}, lang=lang)
                except HTTPException:
                    return row, None
            if data.get("movie_results"):
                return row, ("movie", data["movie_results"][0])
            if data.get("tv_results"):
                return row, ("tv", data["tv_results"][0])
            return row, None

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
                db.add(UserTitle(
                    user_id=user_id, media_type=media_type, tmdb_id=item["id"], imdb_id=row["const"],
                    title=c["title"][:255], year=c["year"], poster_path=item.get("poster_path"),
                    status=status, rating=row["rating"] if status == "watched" else None,
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
    rows = parse_imdb_csv(raw.decode("utf-8-sig", errors="replace"))
    if not rows:
        raise HTTPException(400, "no IMDb titles found in this file")
    if len(rows) > MAX_ROWS:
        raise HTTPException(400, f"too many rows (max {MAX_ROWS}); split the file")
    job = ImportJob(id=secrets.token_hex(16), user_id=user.id, total=len(rows))
    db.add(job)
    db.commit()
    background.add_task(_run_import, job.id, user.id, rows, status, user.lang)
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
    status: Literal["watched", "want", "not_now"],
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """CSV for IMDb list import (needs the 'Const' column). Missing IMDb IDs are resolved lazily."""
    rows = db.scalars(
        select(UserTitle).where(UserTitle.user_id == user.id, UserTitle.status == status)
        .order_by(UserTitle.decided_at, UserTitle.id)
    ).all()

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
