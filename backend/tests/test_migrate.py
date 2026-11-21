from sqlalchemy import create_engine, inspect, text

from database.migrate import add_missing_columns
from database.models import Base


def test_old_database_gets_the_new_columns_and_keeps_its_rows(tmp_path):
    """A production table made before these columns existed must be upgraded in place."""
    engine = create_engine(f"sqlite:///{tmp_path}/old.db")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, handle VARCHAR(32) UNIQUE, display_name VARCHAR(40),"
                       " lang VARCHAR(2), region VARCHAR(2), created_at DATETIME)"))
        c.execute(text("CREATE TABLE user_titles (id INTEGER PRIMARY KEY, user_id INTEGER, media_type VARCHAR(8),"
                       " tmdb_id INTEGER, imdb_id VARCHAR(16), title VARCHAR(255), year VARCHAR(4),"
                       " poster_path VARCHAR(255), status VARCHAR(10), rating SMALLINT, decided_at DATETIME)"))
        c.execute(text("INSERT INTO users (id, handle, lang, region) VALUES (1, 'h', 'en', 'CA')"))
        c.execute(text("INSERT INTO user_titles (id, user_id, media_type, tmdb_id, title, status) VALUES (1, 1, 'movie', 5, 'Old', 'want')"))
    done = add_missing_columns(engine)
    assert {"users.cal_token", "user_titles.rewatch", "user_titles.genre_ids", "user_titles.release_date"} <= set(done)
    cols = {c["name"] for c in inspect(engine).get_columns("user_titles")}
    assert {"rewatch", "genre_ids", "release_date"} <= cols
    with engine.connect() as c:
        assert c.execute(text("SELECT title, rewatch FROM user_titles")).one() == ("Old", 0)
    assert add_missing_columns(engine) == []  # second run changes nothing


def test_a_fresh_database_needs_no_upgrade(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/new.db")
    Base.metadata.create_all(engine)
    assert add_missing_columns(engine) == []
