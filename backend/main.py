import asyncio
from contextlib import asynccontextmanager

import pymysql
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_fastapi_instrumentator import Instrumentator

import auth
import config
import login_posters
import routes_io
import routes_swipes
import routes_titles
import tmdb
from database.connection import DATABASE_URL, SessionLocal, engine
from database.models import Base
from tracing import setup_tracing


def init_database() -> None:
    """Dev/compose only: create the database and user with root credentials.

    On the cluster the database is created by hand on the shared MySQL (sql/init.sql)
    and DB_ROOT_PASSWORD is not set, so this is skipped.
    """
    if not config.DB_ROOT_PASSWORD or DATABASE_URL.startswith("sqlite"):
        return
    conn = pymysql.connect(host=config.DB_HOST, port=int(config.DB_PORT), user="root", password=config.DB_ROOT_PASSWORD)
    with conn.cursor() as cur:
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{config.DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        cur.execute(f"CREATE USER IF NOT EXISTS '{config.DB_USER}'@'%%' IDENTIFIED BY %s", (config.DB_PASSWORD,))
        # No args here, so pymysql does no %-formatting: a single % is the wildcard host.
        cur.execute(f"GRANT ALL PRIVILEGES ON `{config.DB_NAME}`.* TO '{config.DB_USER}'@'%'")
        cur.execute("FLUSH PRIVILEGES")
    conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        login_posters.seed(db)
    warm = asyncio.create_task(tmdb.warm_loop()) if config.TMDB_WARM else None
    yield
    if warm:
        warm.cancel()


setup_tracing("debarras-backend", engine)

app = FastAPI(title="Débarras", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Missing-Imdb", "Content-Disposition"],
)

app.include_router(auth.router)
app.include_router(routes_titles.router)
app.include_router(routes_swipes.router)
app.include_router(routes_io.router)

Instrumentator().instrument(app).expose(app, include_in_schema=False)
FastAPIInstrumentor.instrument_app(app)


@app.get("/health")
def health():
    return {"status": "ok"}
