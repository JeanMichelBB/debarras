from datetime import date, timedelta

import tmdb
from conftest import item, tv_item
from test_swipes_io import swipe


def day(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


def install(monkeypatch, fake, movies, shows):
    calls = []

    async def patched(path, params=None, **kw):
        if path == "/discover/movie":
            calls.append((path, params))
            return {"results": movies}
        if path == "/discover/tv":
            calls.append((path, params))
            return {"results": shows}
        return await fake(path, params, **kw)

    monkeypatch.setattr(tmdb, "tmdb_get", patched)
    return calls


def test_coming_soon_hides_junk_and_is_flagged_and_sorted(client, user, fake_tmdb, monkeypatch):
    movies = [
        item(10, release_date=day(90)),
        item(11, release_date=day(20)),
        item(12, title="Untitled Marvel Project", release_date=day(30)),   # placeholder title
        item(13, release_date=day(40), poster_path=None),                   # no poster
        item(14, release_date=day(50), overview=""),                        # no overview
        item(15, release_date=day(500)),                                    # too far ahead
        item(16, release_date=day(-5)),                                     # already out
    ]
    shows = [tv_item(20, release_date=day(60)), tv_item(21, release_date="")]
    calls = install(monkeypatch, fake_tmdb, movies, shows)

    r = client.get("/titles/queue", headers=user, params={"source": "soon", "limit": 20}).json()
    got = [(c["media_type"], c["tmdb_id"]) for c in r["cards"]]
    assert got == [("movie", 11), ("tv", 20), ("movie", 10)]  # soonest first
    assert all(c["upcoming"] and c["release_date"] for c in r["cards"])
    assert r["cards"][0]["genres"] == ["Drama"]

    movie_params = next(p for path, p in calls if path == "/discover/movie")
    assert movie_params["with_release_type"] == "2|3" and movie_params["region"] == "CA"
    assert movie_params["release_date.gte"] == day(0) and movie_params["release_date.lte"] == day(365)
    tv_params = next(p for path, p in calls if path == "/discover/tv")
    assert tv_params["without_genres"] == "10767|10763|10764"


def test_coming_soon_skips_titles_already_decided_and_reads_few_pages(client, user, fake_tmdb, monkeypatch):
    calls = install(monkeypatch, fake_tmdb, [item(10, release_date=day(10)), item(11, release_date=day(11))], [])
    swipe(client, user, 10, "want")
    r = client.get("/titles/queue", headers=user, params={"source": "soon", "limit": 5}).json()
    assert [c["tmdb_id"] for c in r["cards"]] == [11]
    pages = {p["page"] for path, p in calls if path == "/discover/movie"}
    assert pages == {1, 2, 3}  # nothing to fill the batch, so it stops after three pages


def test_normal_pile_never_contains_coming_soon_titles(client, user, fake_tmdb, monkeypatch):
    install(monkeypatch, fake_tmdb, [item(10, release_date=day(10))], [])
    r = client.get("/titles/queue", headers=user, params={"limit": 12}).json()
    assert all(not c.get("upcoming") for c in r["cards"])
