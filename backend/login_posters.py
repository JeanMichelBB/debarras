"""Posters for the login screen: ten well-known films kept in the database, three picked per visit."""

import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import LoginPoster

DEFAULTS = [
    (155, "The Dark Knight", "/qJ2tW6WMUDux911r6m7haRef0WH.jpg"),
    (550, "Fight Club", "/jSziioSwPVrOy9Yow3XhWIBDjq1.jpg"),
    (872585, "Oppenheimer", "/8Gxv8gSFCU0XGDykEGv7zR1n2ua.jpg"),
    (16869, "Inglourious Basterds", "/aupnPtagH9JVBuMrGEanf4iqXEQ.jpg"),
    (807, "Se7en", "/191nKfP0ehp3uIvWqgPbFmI4lv9.jpg"),
    (210577, "Gone Girl", "/ts996lKsxvjkO2yiYG0ht4qAicO.jpg"),
    (374720, "Dunkirk", "/b4Oe15CGLL61Ped0RAS9JpqdmCt.jpg"),
    (361743, "Top Gun: Maverick", "/n0YuM4f5lvGAP6MAW2kBIzugXnc.jpg"),
    (324857, "Spider-Man: Into the Spider-Verse", "/iiZZdoQBEYBv6id8su7ImL0oCbD.jpg"),
    (62, "2001: A Space Odyssey", "/ve72VxNqjGM69Uky4WTo2bK6rfq.jpg"),
]


def seed(db: Session) -> None:
    """Fill the table the first time only, so edits made in the database are never overwritten."""
    if db.scalar(select(LoginPoster.tmdb_id).limit(1)) is not None:
        return
    db.add_all(LoginPoster(tmdb_id=i, media_type="movie", title=t, poster_path=p) for i, t, p in DEFAULTS)
    db.commit()


def pick(db: Session, n: int = 3) -> list[str]:
    paths = list(db.scalars(select(LoginPoster.poster_path)))
    return random.sample(paths, min(n, len(paths)))
