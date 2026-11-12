import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import config

# DATABASE_URL overrides the DB_* settings (used by tests with sqlite).
DATABASE_URL = os.getenv("DATABASE_URL") or (
    f"mysql+pymysql://{config.DB_USER}:{config.DB_PASSWORD}"
    f"@{config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}?charset=utf8mb4"
)

_kwargs = {"pool_pre_ping": True, "pool_size": 20, "max_overflow": 20, "pool_recycle": 1800}
if DATABASE_URL.startswith("sqlite"):
    _kwargs = {"connect_args": {"check_same_thread": False}}

engine = create_engine(DATABASE_URL, **_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
