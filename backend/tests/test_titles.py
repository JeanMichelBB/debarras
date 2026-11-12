import wiki
from database.connection import SessionLocal
from database.models import TitleCache


def swipe(client, headers, tmdb_id, status, media_type="movie", **extra):
    r = client.post("/swipe", headers=headers, json={
        "media_type": media_type, "tmdb_id": tmdb_id, "status": status, "title": f"Movie {tmdb_id}", **extra})
    assert r.status_code == 200, r.text
    return r.json()


def queue(client, headers, **params):
    r = client.get("/titles/queue", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_cold_start_queue_is_trending_interleaved(client, user):
    cards = queue(client, user)["cards"]
    assert [c["tmdb_id"] for c in cards] == [800, 900, 801, 901]
    assert {c["reason"] for c in cards} == {"Trending"}
    assert cards[0]["poster"].startswith("https://image.tmdb.org/t/p/w500/")


def test_queue_finishes_franchise_then_director_then_cast_then_similar(client, user):
    swipe(client, user, 1, "watched")
    cards = queue(client, user)["cards"]
    ids = [c["tmdb_id"] for c in cards]
    # franchise in release order (1 is decided so skipped), director (2 dup skipped), cast, recs, trending
    assert ids[:6] == [2, 3, 4, 7, 9, 8]
    assert cards[0]["reason"] == "Same franchise: Hero Collection"
    assert cards[2]["reason"] == "By Dir A"
    assert cards[3]["reason"] == "With Actor A"
    assert cards[5]["reason"] == "Because you liked Movie 1"
    assert 1 not in ids and 99 not in ids  # decided title and non-director credit excluded


def test_disliked_titles_do_not_seed_related_picks(client, user):
    swipe(client, user, 1, "watched", rating=1)
    ids = [c["tmdb_id"] for c in queue(client, user)["cards"]]
    assert 2 not in ids and 3 not in ids


def test_not_now_is_not_shown_again(client, user):
    swipe(client, user, 800, "not_now")
    ids = [c["tmdb_id"] for c in queue(client, user)["cards"]]
    assert 800 not in ids


def test_queue_exclude_param_dedupes_client_stack(client, user):
    ids = [c["tmdb_id"] for c in queue(client, user, exclude="movie:800,tv:900")["cards"]]
    assert 800 not in ids and 900 not in ids and 801 in ids


def test_queue_media_type_filter(client, user):
    swipe(client, user, 1, "watched")
    cards = queue(client, user, media_type="tv")["cards"]
    assert cards and all(c["media_type"] == "tv" for c in cards)


def test_queue_filters_use_discover(client, user, fake_tmdb):
    cards = queue(client, user, genres="35", year_min=2000, min_rating=6, media_type="movie")["cards"]
    assert [c["tmdb_id"] for c in cards] == [700, 701]
    path, params = next((p, q) for p, q in fake_tmdb.calls if p == "/discover/movie")
    assert params["with_genres"] == "35"
    assert params["primary_release_date.gte"] == "2000-01-01"
    assert params["vote_average.gte"] == 6.0


def test_queue_filters_reject_non_matching_seed_candidates(client, user):
    swipe(client, user, 1, "watched")
    cards = queue(client, user, genres="35", media_type="movie")["cards"]
    assert all(c["tmdb_id"] >= 700 for c in cards)  # franchise/director picks are genre 18, filtered out


def test_queue_rejects_bad_genres(client, user):
    assert client.get("/titles/queue", headers=user, params={"genres": "a,b"}).status_code == 422


def test_queue_never_returns_more_than_limit(client, user):
    assert len(queue(client, user, limit=2)["cards"]) == 2


def test_title_details_shape_region_and_cache(client, user, fake_tmdb):
    r = client.get("/titles/movie/1", headers=user)
    assert r.status_code == 200
    d = r.json()
    assert d["title"] == "Movie 1" and d["imdb_id"] == "tt0000001"
    assert d["providers"]["flatrate"][0]["name"] == "Netflix"  # default region CA
    assert [v["key"] for v in d["videos"]] == ["trail", "tease"]  # trailer first, Vimeo dropped
    assert [c["job"] for c in d["crew"]] == ["Director"]  # Camera dropped
    assert d["my_status"] is None
    assert d["reviews"][0]["rating"] == 9

    client.get("/titles/movie/1", headers=user)
    detail_calls = [c for c in fake_tmdb.calls if c[0] == "/movie/1"]
    assert len(detail_calls) == 1  # second request served from title_cache

    client.patch("/me", headers=user, json={"region": "FR"})
    d = client.get("/titles/movie/1", headers=user).json()
    assert "rent" in d["providers"] and d["region"] == "FR"


def test_title_details_include_my_status(client, user):
    swipe(client, user, 1, "want")
    assert client.get("/titles/movie/1", headers=user).json()["my_status"] == "want"


def test_title_details_unknown_title_is_404(client, user):
    assert client.get("/titles/movie/404", headers=user).status_code == 404
    assert client.get("/titles/book/1", headers=user).status_code == 422


def test_details_cache_is_per_language(client, user, fake_tmdb):
    client.get("/titles/movie/1", headers=user)
    client.patch("/me", headers=user, json={"lang": "fr"})
    client.get("/titles/movie/1", headers=user)
    assert len([c for c in fake_tmdb.calls if c[0] == "/movie/1"]) == 2
    db = SessionLocal()
    try:
        assert {r.lang for r in db.query(TitleCache).all()} == {"en", "fr"}
    finally:
        db.close()


def test_stale_cache_is_served_when_tmdb_fails(client, user, monkeypatch):
    from datetime import timedelta

    from database.models import utcnow

    client.get("/titles/movie/1", headers=user)
    db = SessionLocal()
    try:
        row = db.query(TitleCache).one()
        row.refreshed_at = utcnow() - timedelta(days=30)
        db.commit()
    finally:
        db.close()

    from fastapi import HTTPException

    import tmdb

    async def down(*a, **k):
        raise HTTPException(502, "TMDb unreachable")

    monkeypatch.setattr(tmdb, "tmdb_get", down)
    r = client.get("/titles/movie/1", headers=user)
    assert r.status_code == 200 and r.json()["title"] == "Movie 1"


def test_genres(client, user):
    assert client.get("/meta/genres", headers=user).json()["movie"][0]["name"] == "Drama"


# ── Wikipedia facts ───────────────────────────────────────────────────────────
EXTRACT = """Intro text about the show.

== Production ==
Development began when the network asked for a pilot, and the creators wrote the first episodes quickly. It was shot on location in a small town over the course of several months.

== Cast ==
Short.

== Reception ==
The second season saw viewership decline after a key creator stepped back from daily involvement, which many critics blamed for a loss of focus. The series was later reappraised.

=== Legacy ===
Long-lasting influence on television drama. Many later series borrowed its tone and structure, and it is still widely discussed today.
"""


def test_parse_and_pick_sections():
    sections = wiki.parse_sections(EXTRACT)
    assert [h for h, _ in sections] == ["Production", "Cast", "Reception", "Legacy"]
    picked = wiki.pick_sections(sections, "en")
    assert [p["heading"] for p in picked] == ["Production", "Reception"]
    # "Production" is also a French heading; "Reception" is not ("Accueil"/"Réception" are)
    assert [p["heading"] for p in wiki.pick_sections(sections, "fr")] == ["Production"]


def test_pick_sections_matches_real_world_headings():
    """Headings seen on the real Twin Peaks article: substring match, most specific stem first."""
    long = "Lynch and Frost were less involved in the second season, and quality fell. " * 3
    sections = [
        ("Development", long), ("Casting", long), ("Filming", long),
        ("Reception and legacy", long), ("Critical acclaim", long), ("Declining ratings", "Ratings fell. " * 20),
    ]
    picked = wiki.pick_sections(sections, "en")
    assert [p["heading"] for p in picked] == ["Development", "Declining ratings"]
    assert wiki.pick_sections([("Accueil critique", long), ("Genèse", long)], "fr")[0]["heading"] == "Genèse"
    assert wiki.pick_sections([("Accueil critique", long)], "fr")[0]["heading"] == "Accueil critique"


def test_excerpt_cuts_at_sentence_boundary():
    text = "First sentence here. " * 60
    out = wiki.excerpt(text, limit=100)
    assert len(out) <= 100 and out.endswith(".")


def test_facts_endpoint_returns_attribution_and_caches(client, user, monkeypatch):
    calls = []

    async def fake_fetch(imdb_id, lang):
        calls.append((imdb_id, lang))
        return {"source": "Wikipedia", "lang": "en", "url": "https://en.wikipedia.org/wiki/X",
                "license": "CC BY-SA 4.0", "sections": [{"heading": "Production", "text": "t"}]}

    monkeypatch.setattr(wiki, "fetch_facts", fake_fetch)
    for _ in range(2):
        r = client.get("/titles/movie/1/facts", headers=user)
        assert r.status_code == 200
        assert r.json()["facts"]["license"] == "CC BY-SA 4.0"
    assert calls == [("tt0000001", "en")]  # second call from fact_cache


def test_facts_negative_result_is_cached(client, user, monkeypatch):
    calls = []

    async def none_fetch(imdb_id, lang):
        calls.append(1)
        return None

    monkeypatch.setattr(wiki, "fetch_facts", none_fetch)
    for _ in range(2):
        assert client.get("/titles/movie/1/facts", headers=user).json() == {"facts": None}
    assert len(calls) == 1


def test_is_released_filters_unreleased():
    from datetime import date
    from queue_builder import is_released

    today = date(2026, 11, 11)
    assert is_released({"release_date": "2001-01-01"}, today)
    assert is_released({"first_air_date": "2026-11-11"}, today)
    assert not is_released({"release_date": "2028-01-01"}, today)
    assert not is_released({"release_date": ""}, today)
    assert not is_released({}, today)


def test_is_game_article():
    from wiki import is_game_article

    assert is_game_article("Halo Wars is a 2009 real-time strategy video game developed by Ensemble Studios.\n\nGameplay")
    assert not is_game_article("Tomb Raider is a 2018 action film based on the video game.\n\nPlot")
    assert not is_game_article("Twin Peaks is an American television series.")


def test_login_posters_are_public_random_and_distinct(client):
    r = client.get("/public/login-posters")  # no sign-in
    assert r.status_code == 200
    posters = r.json()["posters"]
    assert len(posters) == 3 and len(set(posters)) == 3
    seen = {tuple(client.get("/public/login-posters").json()["posters"]) for _ in range(8)}
    assert len(seen) > 1  # not always the same three
