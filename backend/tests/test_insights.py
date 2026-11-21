from test_swipes_io import swipe


def many(client, headers, n, status="watched", start=100, **extra):
    for i in range(start, start + n):
        swipe(client, headers, i, status, **extra)


# ── taste card ────────────────────────────────────────────────────────────────
def test_taste_is_not_ready_before_25_swipes(client, user):
    many(client, user, 24)
    t = client.get("/me/taste", headers=user).json()
    assert t["count"] == 24 and t["ready"] is False and t["full"] is False
    many(client, user, 1, start=200)
    assert client.get("/me/taste", headers=user).json()["ready"] is True


def test_taste_counts_genres_decade_kind_and_keep_ratio(client, user):
    many(client, user, 10, "watched", 100, genre_ids=[18], year="1994")
    many(client, user, 8, "want", 200, genre_ids=[35, 18], year="1996")
    many(client, user, 4, "want", 300, media_type="tv", genre_ids=[35], year="2010")
    many(client, user, 8, "not_now", 400, genre_ids=[18], year="2020")
    t = client.get("/me/taste", headers=user).json()
    assert t["count"] == 30 and t["ready"]
    # Not now titles do not count towards taste: Drama 18, Comedy 12.
    assert [(g["name"], g["n"]) for g in t["genres"]] == [("Drama", 18), ("Comedy", 12)]
    assert t["decade"] == 1990
    assert (t["movies"], t["tv"]) == (18, 4)
    assert t["keep_percent"] == 73  # 22 of 30
    assert t["people"] == []


def test_taste_full_card_names_a_director_after_100_swipes(client, user):
    many(client, user, 100, "watched", 1)
    # Details of two liked titles are in the cache: same director "Dir A".
    client.get("/titles/movie/1", headers=user)
    client.get("/titles/movie/2", headers=user)
    t = client.get("/me/taste", headers=user).json()
    assert t["full"] is True
    assert {"name": "Dir A", "role": "director", "n": 2} in t["people"]


def test_taste_is_private(client, register):
    a, _ = register()
    b, _ = register()
    many(client, a, 30)
    assert client.get("/me/taste", headers=b).json()["count"] == 0


# ── badges ────────────────────────────────────────────────────────────────────
def test_badges_progress_and_milestone(client, user):
    many(client, user, 25, "want", year="2001")
    b = {x["key"]: x for x in client.get("/me/badges", headers=user).json()["badges"]}
    assert b["swipes-25"]["earned"] and not b["swipes-100"]["earned"]
    assert b["swipes-100"]["have"] == 25
    assert b["every-decade"]["have"] == 0  # only Seen movies count


def test_badge_every_decade_and_rewatch_lover(client, user):
    for i, y in enumerate(("1975", "1985", "1995", "2005", "2015", "2025")):
        swipe(client, user, 10 + i, "watched", year=y)
    for i in range(5):
        client.patch(f"/swipe/movie/{10 + i}", headers=user, json={"rewatch": True})
    b = {x["key"]: x for x in client.get("/me/badges", headers=user).json()["badges"]}
    assert b["every-decade"]["earned"] and b["rewatch-lover"]["earned"]


def test_badge_for_a_finished_collection(client, user):
    for i in (1, 2):
        swipe(client, user, i, "watched")
    assert client.get("/me/badges", headers=user).json()["collections"] == []
    swipe(client, user, 3, "watched")
    assert client.get("/me/badges", headers=user).json()["collections"] == [{"key": "star-wars", "name": "Hero Collection"}]


# ── collections ───────────────────────────────────────────────────────────────
def test_collections_list_shows_progress_and_started_first(client, user):
    swipe(client, user, 1, "watched")
    swipe(client, user, 2, "watched")
    swipe(client, user, 3, "want")
    rows = client.get("/collections", headers=user).json()["collections"]
    first = rows[0]
    assert first["key"] == "star-wars" and first["name"] == "Hero Collection"
    assert (first["seen"], first["want"], first["total"], first["complete"]) == (2, 1, 3, False)
    marvel = next(r for r in rows if r["key"] == "marvel")
    assert marvel["total"] == 32 and marvel["seen"] == 0
    assert marvel["poster"]


def test_collection_detail_in_release_order_with_my_status(client, user):
    swipe(client, user, 1, "watched")
    swipe(client, user, 3, "want")
    d = client.get("/collections/star-wars", headers=user).json()
    assert [i["tmdb_id"] for i in d["items"]] == [1, 2, 3]  # by release date
    assert [i["status"] for i in d["items"]] == ["watched", None, "want"]
    assert (d["seen"], d["total"]) == (1, 3)
    assert client.get("/collections/nope", headers=user).status_code == 404
