from datetime import date, datetime, timedelta, timezone

import routes_calendar
from test_swipes_io import swipe


def day(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


def link(client, user) -> str:
    return client.post("/me/calendar", headers=user).json()["path"]


def test_no_link_until_created_and_feed_needs_the_secret(client, user):
    assert client.get("/me/calendar", headers=user).json() == {"path": None}
    path = link(client, user)
    assert client.get("/me/calendar", headers=user).json() == {"path": path}
    assert client.get(path).status_code == 200  # no sign-in: the token is the key
    assert client.get("/calendar/short.ics").status_code == 404
    assert client.get("/calendar/" + "x" * 43 + ".ics").status_code == 404


def test_feed_lists_release_day_of_upcoming_want_titles_only(client, user):
    swipe(client, user, 1, "want", release_date=day(10))
    swipe(client, user, 2, "want", release_date=day(-10))     # already out
    swipe(client, user, 3, "watched", release_date=day(20))   # not Want
    swipe(client, user, 4, "not_now", release_date=day(30))
    r = client.get(link(client, user))
    assert r.headers["content-type"].startswith("text/calendar")
    text = r.text
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert text.count("BEGIN:VEVENT") == 1
    d = date.today() + timedelta(days=10)
    assert f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}" in text
    assert f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}" in text
    assert "SUMMARY:Movie 1" in text and "UID:movie-1@" in text


def test_new_link_replaces_the_old_one_and_delete_removes_it(client, user):
    old = link(client, user)
    new = link(client, user)
    assert old != new
    assert client.get(old).status_code == 404 and client.get(new).status_code == 200
    assert client.delete("/me/calendar", headers=user).status_code == 204
    assert client.get(new).status_code == 404
    assert client.get("/me/calendar", headers=user).json() == {"path": None}


def test_feed_only_shows_that_users_titles(client, register):
    a, _ = register()
    b, _ = register()
    swipe(client, a, 1, "want", release_date=day(5))
    swipe(client, b, 2, "want", release_date=day(6))
    text = client.get(link(client, a)).text
    assert "movie-1@" in text and "movie-2@" not in text


def test_old_want_titles_get_their_release_date_from_tmdb(client, user, monkeypatch):
    swipe(client, user, 5, "want")  # saved without a date; no year, so it may still be unreleased
    swipe(client, user, 6, "want", year="1999")  # old title: not looked up
    text = client.get(link(client, user)).text
    assert text.count("BEGIN:VEVENT") == 0  # the fake TMDb date (2001) is in the past
    items = client.get("/swipes", headers=user).json()["items"]
    dates = {i["tmdb_id"]: i["release_date"] for i in items}
    assert dates[5] == "2001-01-01" and dates[6] is None


def test_ics_escapes_and_folds_long_lines():
    text = routes_calendar.build_ics(
        [("u@x", "A, B; C\nD " + "é" * 60, "2030-01-02", "d")], "Cal", datetime(2030, 1, 1, tzinfo=timezone.utc))
    for line in text.split("\r\n"):
        assert len(line.encode()) <= 75
    unfolded = text.replace("\r\n ", "")
    assert "SUMMARY:A\\, B\; C\\nD " in unfolded
