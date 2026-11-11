import os
import re
import tempfile
from types import SimpleNamespace

# Must be set before the app is imported: config loads backend/.env but never overrides
# variables that are already set, so tests can never use the real token or database.
_tmp = tempfile.mkdtemp(prefix="debarras-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["JWT_SECRET"] = "test-secret-not-real"
os.environ["TMDB_READ_TOKEN"] = "test-token-not-real"
os.environ["WEBAUTHN_RP_ID"] = "localhost"
os.environ["WEBAUTHN_ORIGINS"] = "http://localhost:3002"

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from webauthn.helpers import bytes_to_base64url  # noqa: E402

import auth  # noqa: E402
import ratelimit  # noqa: E402
import tmdb  # noqa: E402
import wiki  # noqa: E402
from database.connection import engine  # noqa: E402
from database.models import Base  # noqa: E402
from main import app  # noqa: E402

CRED_ID = bytes_to_base64url(b"cred-one")


def item(i: int, title: str | None = None, **kw) -> dict:
    return {
        "id": i, "title": title or f"Movie {i}", "overview": "An overview.", "poster_path": f"/p{i}.jpg",
        "release_date": kw.pop("release_date", "2001-01-01"), "vote_average": kw.pop("vote_average", 7.0),
        "vote_count": 500, "genre_ids": kw.pop("genre_ids", [18]), **kw,
    }


def tv_item(i: int, **kw) -> dict:
    d = item(i, **kw)
    d["name"] = f"Show {i}"
    d.pop("title")
    d["first_air_date"] = d.pop("release_date")
    return d


def details_raw(i: int) -> dict:
    raw = {
        **item(i), "runtime": 100, "genres": [{"id": 18, "name": "Drama"}], "imdb_id": f"tt{i:07d}",
        "credits": {
            "cast": [{"id": 200, "name": "Actor A", "character": "X"}, {"id": 201, "name": "Actor B"}],
            "crew": [{"id": 100, "name": "Dir A", "job": "Director"}, {"id": 5, "name": "Cam", "job": "Camera"}],
        },
        "videos": {"results": [
            {"site": "YouTube", "type": "Teaser", "key": "tease", "name": "Teaser"},
            {"site": "YouTube", "type": "Trailer", "key": "trail", "name": "Trailer", "official": True},
            {"site": "Vimeo", "type": "Trailer", "key": "nope"},
        ]},
        "keywords": {"keywords": [{"id": 1, "name": "k"}]},
        "reviews": {"results": [{"author": "a", "content": "great", "author_details": {"rating": 9}}]},
        "watch/providers": {"results": {
            "CA": {"link": "http://ca", "flatrate": [{"provider_name": "Netflix", "logo_path": "/n.jpg"}]},
            "FR": {"link": "http://fr", "rent": [{"provider_name": "Canal", "logo_path": "/c.jpg"}]},
        }},
    }
    if i == 1:
        raw["belongs_to_collection"] = {"id": 10, "name": "Hero Collection"}
    return raw


class FakeTmdb:
    """Fake TMDb. Records calls so tests can assert on caching behaviour."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, path, params=None, *, lang="en", cache=True):
        params = params or {}
        self.calls.append((path, params))
        if path == "/collection/10":
            return {"name": "Hero Collection", "parts": [item(3, release_date="2005-01-01"), item(1), item(2, release_date="2003-01-01")]}
        if m := re.fullmatch(r"/person/(\d+)/movie_credits", path):
            if m.group(1) == "100":
                return {"crew": [{**item(4), "job": "Director"}, {**item(2), "job": "Director"}, {**item(99), "job": "Producer"}], "cast": []}
            if m.group(1) == "200":
                return {"cast": [item(7)], "crew": []}
            return {"cast": [item(9)], "crew": []}
        if m := re.fullmatch(r"/(movie|tv)/(\d+)/recommendations", path):
            return {"results": [item(8)]}
        if m := re.fullmatch(r"/(movie|tv)/(\d+)/external_ids", path):
            return {"imdb_id": f"tt{int(m.group(2)):07d}"}
        if path == "/trending/movie/week":
            return {"results": [item(800), item(801)]}
        if path == "/trending/tv/week":
            return {"results": [tv_item(900), tv_item(901)]}
        if m := re.fullmatch(r"/discover/(movie|tv)", path):
            return {"results": [item(700, genre_ids=[35]), item(701, genre_ids=[35])]}
        if path in ("/genre/movie/list", "/genre/tv/list"):
            return {"genres": [{"id": 18, "name": "Drama"}]}
        if m := re.fullmatch(r"/find/(tt\d+)", path):
            n = int(m.group(1)[2:])
            if n == 404:
                return {"movie_results": [], "tv_results": []}
            if n >= 5000:
                return {"movie_results": [], "tv_results": [tv_item(n)]}
            return {"movie_results": [item(n)], "tv_results": []}
        if m := re.fullmatch(r"/(movie|tv)/(\d+)", path):
            if int(m.group(2)) == 404:
                raise HTTPException(404, "not found on TMDb")
            return details_raw(int(m.group(2)))
        raise HTTPException(404, f"fake has no route for {path}")


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    tmdb._mem.clear()
    ratelimit._hits.clear()
    fake = FakeTmdb()
    monkeypatch.setattr(tmdb, "tmdb_get", fake)
    # Never touch Wikipedia in tests unless a test patches this itself.
    async def no_wiki(*a, **k):
        return None
    monkeypatch.setattr(wiki, "fetch_facts", no_wiki)
    return fake


@pytest.fixture
def fake_tmdb(fresh_state):
    return fresh_state


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _patch_verify(monkeypatch, cred: bytes):
    monkeypatch.setattr(auth, "verify_registration_response", lambda **kw: SimpleNamespace(
        credential_id=cred, credential_public_key=b"public-key", sign_count=0))


@pytest.fixture
def register(client, monkeypatch):
    """Returns a function that registers a new user and returns (headers, recovery_codes)."""
    counter = {"n": 0}

    def _register():
        counter["n"] += 1
        _patch_verify(monkeypatch, b"cred-one" if counter["n"] == 1 else f"cred-{counter['n']}".encode())
        begin = client.post("/auth/register/begin", json={}).json()
        r = client.post("/auth/register/finish", json={"credential": {"id": "x"}, "state": begin["state"]})
        assert r.status_code == 201, r.text
        body = r.json()
        return {"Authorization": f"Bearer {body['access_token']}"}, body["recovery_codes"]

    return _register


@pytest.fixture
def user(register):
    headers, _ = register()
    return headers
