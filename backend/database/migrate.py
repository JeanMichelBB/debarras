"""Tiny schema upgrade: create_all makes new tables but never adds a column to an existing one.

On startup, add any model column or index that the live database does not have yet.
Only additive changes. Nothing is dropped or altered.
"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from database.models import Base


def add_missing_columns(engine: Engine) -> list[str]:
    done: list[str] = []
    insp = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have:
                continue
            ddl = f"ALTER TABLE `{table.name}` ADD COLUMN `{col.name}` {col.type.compile(dialect=engine.dialect)}"
            if col.server_default is not None:
                ddl += f" DEFAULT {col.server_default.arg}"
            if not col.nullable and col.server_default is not None:
                ddl += " NOT NULL"
            with engine.begin() as conn:
                conn.execute(text(ddl))
            done.append(f"{table.name}.{col.name}")
        known = {i["name"] for i in insp.get_indexes(table.name)}
        for idx in table.indexes:
            if idx.name not in known and all(c.name in have or f"{table.name}.{c.name}" in done for c in idx.columns):
                idx.create(bind=engine, checkfirst=True)
        # A unique=True column makes an unnamed unique constraint, which create_all only adds with the table.
        for col in table.columns:
            if col.unique and f"{table.name}.{col.name}" in done:
                with engine.begin() as conn:
                    conn.execute(text(f"CREATE UNIQUE INDEX `uq_{table.name}_{col.name}` ON `{table.name}` (`{col.name}`)"))
    return done
