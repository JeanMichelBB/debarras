from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# watched  = right swipe
# want     = up swipe (watchlist)
# not_now  = left swipe ("don't know it / not now"; may resurface in phase 2)
STATUSES = ("watched", "want", "not_now")
MEDIA_TYPES = ("movie", "tv")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    """No email or phone: identity is a random handle plus one or more passkeys."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    handle: Mapped[str] = mapped_column(String(32), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    lang: Mapped[str] = mapped_column(String(2), default="en")
    region: Mapped[str] = mapped_column(String(2), default="CA")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Passkey(Base):
    __tablename__ = "passkeys"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    credential_id: Mapped[str] = mapped_column(String(255), unique=True)  # base64url
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RecoveryCode(Base):
    __tablename__ = "recovery_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TitleCache(Base):
    """Slimmed TMDb details per title and language, refreshed after CACHE_TTL_DAYS."""

    __tablename__ = "title_cache"

    media_type: Mapped[str] = mapped_column(String(8), primary_key=True)
    tmdb_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lang: Mapped[str] = mapped_column(String(5), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LoginPoster(Base):
    """A movie whose poster can appear on the login screen's cards (a few are picked at random)."""

    __tablename__ = "login_posters"

    tmdb_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    media_type: Mapped[str] = mapped_column(String(8), default="movie")
    title: Mapped[str] = mapped_column(String(255))
    poster_path: Mapped[str] = mapped_column(String(255))


class FactCache(Base):
    """Wikipedia "behind the scenes" excerpts (or a negative result), per title and language."""

    __tablename__ = "fact_cache"

    media_type: Mapped[str] = mapped_column(String(8), primary_key=True)
    tmdb_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lang: Mapped[str] = mapped_column(String(5), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UserTitle(Base):
    __tablename__ = "user_titles"
    __table_args__ = (
        UniqueConstraint("user_id", "media_type", "tmdb_id", name="uq_user_title"),
        Index("ix_user_status", "user_id", "status", "decided_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    media_type: Mapped[str] = mapped_column(String(8))
    tmdb_id: Mapped[int] = mapped_column(Integer)
    imdb_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    year: Mapped[str | None] = mapped_column(String(4), nullable=True)
    poster_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(10))
    # 1 = disliked, 2 = fine, 3 = loved. Only meaningful for status "watched".
    rating: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(12), default="running")  # running/done/failed
    total: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[int] = mapped_column(Integer, default=0)
    imported: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    not_found: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
