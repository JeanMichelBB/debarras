"""The real TMDb client (the other tests replace `tmdb_get` with a fake)."""

import asyncio
import time

import tmdb
from tmdb import tmdb_get as real_get  # captured before the autouse fixture swaps in the fake

from test_titles import queue, swipe


def run(coro):
    return asyncio.run(coro)


def test_person_credits_are_slimmed_before_caching():
    big = {
        "cast": [{"id": i, "title": f"M{i}", "vote_count": i, "poster_path": "/p.jpg", "junk": "x" * 100} for i in range(100)],
        "crew": [{"id": 1, "job": "Director", "title": "D", "junk": 1}, {"id": 2, "job": "Gaffer", "title": "G"}],
        "id": 5,
    }
    out = tmdb._shrink("/person/5/movie_credits", big)
    assert len(out["cast"]) == 40 and out["cast"][0]["id"] == 99  # best known first
    assert all("junk" not in c for c in out["cast"] + out["crew"])
    assert [c["job"] for c in out["crew"]] == ["Director"]


def test_cache_is_lru_and_evicts_the_oldest(monkeypatch):
    monkeypatch.setattr(tmdb, "_MEM_MAX", 2)
    for k in ("a", "b"):
        tmdb._store(k, "/x", {"k": k})
    assert tmdb._mem.get("a")  # touch nothing: just read
    tmdb._mem.move_to_end("a")  # "a" is now the most recently used
    tmdb._store("c", "/x", {"k": "c"})
    assert list(tmdb._mem) == ["a", "c"]


def test_expired_entry_is_served_at_once_and_refreshed_behind(monkeypatch):
    calls = []

    async def fetch(path, params, lang, hi=False):
        calls.append(path)
        return {"n": len(calls)}

    monkeypatch.setattr(tmdb, "_fetch", fetch)

    async def go():
        first = await real_get("/trending/movie/week", {"page": 1})
        key = next(iter(tmdb._mem))
        _, data = tmdb._mem[key]
        tmdb._mem[key] = (time.time() - 10, data)  # expired, but inside the stale window
        stale = await real_get("/trending/movie/week", {"page": 1})
        await asyncio.sleep(0.05)  # let the background refresh land
        fresh = await real_get("/trending/movie/week", {"page": 1})
        return first, stale, fresh

    first, stale, fresh = run(go())
    assert first["n"] == 1 and stale["n"] == 1 and fresh["n"] == 2
    assert len(calls) == 2


def test_a_tap_goes_ahead_of_background_work():
    async def go():
        lim = tmdb._Limiter(50)  # one slot every 20 ms
        order = []

        async def lo(i):
            await lim.wait()
            order.append(f"lo{i}")

        async def hi():
            await lim.wait(hi=True)
            order.append("hi")

        tasks = [asyncio.create_task(lo(i)) for i in range(5)]
        await asyncio.sleep(0.005)  # the first background call has taken its slot
        tasks.append(asyncio.create_task(hi()))
        await asyncio.gather(*tasks)
        return order

    order = run(go())
    assert order.index("hi") <= 1


def test_recommendations_come_with_the_details_not_a_separate_call(client, user, fake_tmdb):
    swipe(client, user, 1, "watched")
    ids = [c["tmdb_id"] for c in queue(client, user)["cards"]]
    assert 8 in ids  # the recommended title still shows up
    assert not [p for p, _ in fake_tmdb.calls if p.endswith("/recommendations")]


def test_writing_the_same_title_twice_does_not_fail():
    from database.connection import SessionLocal
    from database.models import TitleCache

    tmdb._write_cached("movie", 5, "en", {"v": tmdb.SLIM_VERSION, "n": 1})
    tmdb._write_cached("movie", 5, "en", {"v": tmdb.SLIM_VERSION, "n": 2})  # the second one updates
    with SessionLocal() as s:
        assert s.get(TitleCache, ("movie", 5, "en")).data["n"] == 2
