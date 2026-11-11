import io
import time


def swipe(client, headers, tmdb_id, status, media_type="movie", **extra):
    return client.post("/swipe", headers=headers, json={
        "media_type": media_type, "tmdb_id": tmdb_id, "status": status, "title": f"Movie {tmdb_id}", **extra})


def wait_job(client, headers, job_id):
    for _ in range(50):
        j = client.get(f"/import/{job_id}", headers=headers).json()
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("import did not finish")


def csv_file(text: str):
    return {"file": ("ratings.csv", io.BytesIO(text.encode("utf-8-sig")), "text/csv")}


# ── swipes ────────────────────────────────────────────────────────────────────
def test_swipe_flow_edit_and_undo(client, user):
    r = swipe(client, user, 1, "watched", rating=3, year="2001",
              poster="https://image.tmdb.org/t/p/w500/abc.jpg")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "watched" and body["rating"] == 3
    assert body["poster"] == "https://image.tmdb.org/t/p/w342/abc.jpg"  # path stored, size rebuilt

    swipe(client, user, 1, "want")  # change of mind
    item = client.get("/swipes", headers=user).json()["items"][0]
    assert item["status"] == "want" and item["rating"] is None  # rating only kept for watched

    assert client.get("/swipes/stats", headers=user).json() == {"watched": 0, "want": 1, "not_now": 0}
    assert client.delete("/swipe/movie/1", headers=user).status_code == 204
    assert client.delete("/swipe/movie/1", headers=user).status_code == 404
    assert client.get("/swipes", headers=user).json()["total"] == 0


def test_swipe_validation(client, user):
    assert swipe(client, user, 1, "maybe").status_code == 422
    assert swipe(client, user, 1, "watched", media_type="book").status_code == 422
    assert swipe(client, user, 1, "watched", rating=4).status_code == 422
    assert swipe(client, user, 0, "watched").status_code == 422
    assert swipe(client, user, 1, "watched", year="20x1").status_code == 422


def test_list_filters_search_and_paging(client, user):
    swipe(client, user, 1, "watched")
    swipe(client, user, 2, "watched")
    swipe(client, user, 3, "want")
    swipe(client, user, 4, "watched", media_type="tv")
    assert client.get("/swipes", headers=user, params={"status": "watched"}).json()["total"] == 3
    assert client.get("/swipes", headers=user, params={"media_type": "tv"}).json()["total"] == 1
    assert client.get("/swipes", headers=user, params={"q": "Movie 3"}).json()["total"] == 1
    assert client.get("/swipes", headers=user, params={"q": "%"}).json()["total"] == 0  # no wildcard injection
    page = client.get("/swipes", headers=user, params={"limit": 2, "offset": 2}).json()
    assert len(page["items"]) == 2 and page["total"] == 4


def test_users_cannot_see_each_others_swipes(client, register):
    a, _ = register()
    b, _ = register()
    swipe(client, a, 1, "watched")
    assert client.get("/swipes", headers=b).json()["total"] == 0
    assert client.delete("/swipe/movie/1", headers=b).status_code == 404
    assert client.get("/export/watched", headers=b).text.strip().splitlines() == ["Const,Title,Year"]


# ── import ────────────────────────────────────────────────────────────────────
RATINGS = (
    "Const,Your Rating,Date Rated,Title,Title Type,Year\n"
    "tt0000001,9,2020-01-01,Movie 1,movie,2001\n"
    "tt0000002,6,2020-01-01,Movie 2,movie,2003\n"
    "tt0000003,3,2020-01-01,Movie 3,movie,2005\n"
    "tt0000404,8,2020-01-01,Missing,movie,1999\n"
    "tt0000001,9,2020-01-01,Movie 1 again,movie,2001\n"
    "tt0005001,7,2020-01-01,Some Show,tvSeries,2010\n"
    "not-an-id,5,2020-01-01,Junk,movie,2000\n"
)


def test_import_ratings_maps_ratings_and_reports(client, user):
    r = client.post("/import", headers=user, files=csv_file(RATINGS), data={"status": "watched"})
    assert r.status_code == 202 and r.json()["total"] == 5  # dup and junk row dropped
    job = wait_job(client, user, r.json()["job_id"])
    assert job["status"] == "done"
    assert (job["imported"], job["not_found"], job["skipped"], job["done"]) == (4, 1, 0, 5)

    items = {i["tmdb_id"]: i for i in client.get("/swipes", headers=user, params={"limit": 100}).json()["items"]}
    assert items[1]["rating"] == 3 and items[2]["rating"] == 2 and items[3]["rating"] == 1  # 9->loved, 6->fine, 3->disliked
    assert items[1]["imdb_id"] == "tt0000001" and items[1]["title"] == "Movie 1"
    assert items[5001]["media_type"] == "tv"


def test_import_skips_titles_already_decided(client, user):
    client.post("/swipe", headers=user, json={"media_type": "movie", "tmdb_id": 1, "status": "not_now"})
    r = client.post("/import", headers=user, files=csv_file(RATINGS), data={"status": "watched"})
    job = wait_job(client, user, r.json()["job_id"])
    assert job["skipped"] == 1 and job["imported"] == 3
    assert client.get("/swipes", headers=user, params={"status": "not_now"}).json()["total"] == 1  # not overwritten


def test_import_watchlist_into_want_has_no_ratings(client, user):
    csv = "Position,Const,Created,Title,Title Type\n1,tt0000001,2020-01-01,Movie 1,movie\n"
    r = client.post("/import", headers=user, files=csv_file(csv), data={"status": "want"})
    wait_job(client, user, r.json()["job_id"])
    item = client.get("/swipes", headers=user).json()["items"][0]
    assert item["status"] == "want" and item["rating"] is None


def test_import_rejects_bad_files(client, user):
    assert client.post("/import", headers=user, files=csv_file("a,b\n1,2\n")).status_code == 400
    assert client.post("/import", headers=user, files=csv_file("Const\nnope\n")).status_code == 400
    assert client.post("/import", headers=user, files=csv_file(RATINGS), data={"status": "bad"}).status_code == 422


def test_import_job_is_private(client, register):
    a, _ = register()
    b, _ = register()
    job_id = client.post("/import", headers=a, files=csv_file(RATINGS)).json()["job_id"]
    assert client.get(f"/import/{job_id}", headers=b).status_code == 404


def test_import_is_rate_limited(client, user):
    codes = [client.post("/import", headers=user, files=csv_file(RATINGS)).status_code for _ in range(6)]
    assert codes[:5] == [202] * 5 and codes[5] == 429


# ── export ────────────────────────────────────────────────────────────────────
def test_export_resolves_missing_imdb_ids_and_is_imdb_import_ready(client, user, fake_tmdb):
    swipe(client, user, 5, "watched")  # no imdb_id stored yet
    swipe(client, user, 6, "want")
    r = client.get("/export/watched", headers=user)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert 'filename="debarras-watched.csv"' in r.headers["content-disposition"]
    assert r.text.strip().splitlines() == ["Const,Title,Year", "tt0000005,Movie 5,"]
    assert r.headers["x-missing-imdb"] == "0"

    client.get("/export/watched", headers=user)
    assert len([c for c in fake_tmdb.calls if c[0] == "/movie/5/external_ids"]) == 1  # saved, not re-fetched


def test_export_counts_titles_without_imdb_id(client, user, monkeypatch):
    import tmdb
    from fastapi import HTTPException

    async def no_ids(path, params=None, *, lang="en", cache=True):
        raise HTTPException(404, "nope")

    swipe(client, user, 5, "watched")
    monkeypatch.setattr(tmdb, "tmdb_get", no_ids)
    r = client.get("/export/watched", headers=user)
    assert r.text.strip().splitlines() == ["Const,Title,Year"] and r.headers["x-missing-imdb"] == "1"


def test_export_neutralizes_spreadsheet_formulas(client, user):
    client.post("/swipe", headers=user, json={
        "media_type": "movie", "tmdb_id": 7, "status": "watched", "title": "=HYPERLINK(\"http://evil\")", "year": "2020"})
    line = client.get("/export/watched", headers=user).text.strip().splitlines()[1]
    assert line.startswith("tt0000007,\"'=HYPERLINK")


def test_import_then_export_round_trip(client, user):
    job = client.post("/import", headers=user, files=csv_file(RATINGS)).json()["job_id"]
    wait_job(client, user, job)
    lines = client.get("/export/watched", headers=user).text.strip().splitlines()
    assert lines[0] == "Const,Title,Year"
    assert {l.split(",")[0] for l in lines[1:]} == {"tt0000001", "tt0000002", "tt0000003", "tt0005001"}
