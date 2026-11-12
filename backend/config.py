import os

from dotenv import load_dotenv

load_dotenv()


def _list(name: str, default: str) -> list[str]:
    return [o.strip() for o in os.getenv(name, default).split(",") if o.strip()]


DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = os.getenv("DB_USER", "debarras")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "debarras")
# Only used by dev/compose to create the database; leave unset on the cluster
# (the database is created by hand on the shared MySQL, see sql/init.sql).
DB_ROOT_PASSWORD = os.getenv("DB_ROOT_PASSWORD")

JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_EXPIRE_DAYS = int(os.getenv("JWT_EXPIRE_DAYS", "30"))

# Passkeys (WebAuthn). RP ID is the bare domain; origins include the scheme.
WEBAUTHN_RP_ID = os.getenv("WEBAUTHN_RP_ID", "localhost")
WEBAUTHN_RP_NAME = os.getenv("WEBAUTHN_RP_NAME", "Débarras")
WEBAUTHN_ORIGINS = _list("WEBAUTHN_ORIGINS", "http://localhost:3002,http://localhost:5173")

# TMDb "API Read Access Token" (v4 bearer), sent in the Authorization header.
TMDB_READ_TOKEN = os.getenv("TMDB_READ_TOKEN", "")
TMDB_WARM = os.getenv("TMDB_WARM", "1") == "1"  # keep trending and genres cached in the background
TMDB_RPS = float(os.getenv("TMDB_RPS", "30"))  # stay under TMDb's ~40 req/s per-IP ceiling
# TMDb's terms limit how long data may be cached; refresh well inside that.
CACHE_TTL_DAYS = int(os.getenv("CACHE_TTL_DAYS", "7"))
FACTS_TTL_DAYS = int(os.getenv("FACTS_TTL_DAYS", "30"))

DEFAULT_LANG = "en"
DEFAULT_REGION = "CA"

WIKI_USER_AGENT = os.getenv(
    "WIKI_USER_AGENT", "Debarras/1.0 (https://debarras.sacenpapier.org; hobby project)"
)

CORS_ORIGINS = _list("CORS_ORIGINS", "http://localhost:3002,http://localhost:5173")
