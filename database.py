import os

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

#إنشاء قاعدة بيانات SQLLite محلية
# DATABASE_URL lets a deployment point this at a persistent-volume path
# (e.g. sqlite:////data/accounting.db on Fly.io) instead of the relative
# file next to the code, which would reset on every redeploy.
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./accounting.db")

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

sessionLocal = sessionmaker(autocommit = False, autoflush = False, bind = engine)

Base = declarative_base()


# Columns added after the first release. Base.metadata.create_all() creates
# missing TABLES but never adds columns to an existing one, so databases that
# predate a column get an idempotent ALTER TABLE at startup.
_ADDED_COLUMNS = {
    "TransactionsMaster": {
        "document": "BLOB",
        "document_mime": "VARCHAR",
        "document_name": "VARCHAR",
    },
}


def ensure_columns(bind=None) -> list[str]:
    """Adds any missing columns listed in _ADDED_COLUMNS. Safe to run on every
    startup. Returns the "table.column" names it added."""
    from sqlalchemy import inspect, text

    bind = bind or engine
    added = []
    inspector = inspect(bind)
    with bind.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if not inspector.has_table(table):
                continue  # create_all() will build it with every column
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, sql_type in columns.items():
                if name not in existing:
                    conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {sql_type}'))
                    added.append(f"{table}.{name}")
    return added

