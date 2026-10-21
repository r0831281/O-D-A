"""Short, explicit SQLite transactions and packaged Alembic migrations."""

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection
from sqlalchemy.pool import NullPool

from nexus.schema import new_id as new_id
from nexus.schema import utcnow as utcnow


class DatabaseSettings(Protocol):
    state_dir: Path
    database_path: Path
    busy_timeout_ms: int

    def prepare_state(self) -> None: ...


class Database:
    """Connection factory; never retain a transaction across external work."""

    def __init__(self, settings: DatabaseSettings):
        settings.prepare_state()
        self.path = settings.database_path
        flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW
        descriptor = os.open(self.path, flags, 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise ValueError("State database must be an operator-owned regular file")
            if stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError("State database permissions must be 0600")
        finally:
            os.close(descriptor)
        self.engine = sa.create_engine(
            sa.URL.create("sqlite", database=str(self.path)),
            poolclass=NullPool,
            hide_parameters=True,
            connect_args={"check_same_thread": False, "timeout": settings.busy_timeout_ms / 1000},
        )

        @sa.event.listens_for(self.engine, "connect")
        def configure_connection(dbapi_connection, _record):
            # SQLAlchemy owns BEGIN; do not combine with driver autocommit=False.
            dbapi_connection.isolation_level = None
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute(f"PRAGMA busy_timeout={int(settings.busy_timeout_ms)}")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                if cursor.fetchone()[0].lower() != "wal":
                    raise RuntimeError("SQLite WAL mode is unavailable")
                cursor.execute("PRAGMA synchronous=FULL")
            finally:
                cursor.close()

        @sa.event.listens_for(self.engine, "begin")
        def begin_transaction(connection):
            if connection.get_execution_options().get("nexus_write", False):
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                connection.exec_driver_sql("BEGIN")

    @contextmanager
    def read(self) -> Iterator[Connection]:
        with self.engine.connect() as connection:
            with connection.begin():
                yield connection

    @contextmanager
    def write(self) -> Iterator[Connection]:
        with self.engine.connect().execution_options(nexus_write=True) as connection:
            with connection.begin():
                yield connection

    def close(self) -> None:
        self.engine.dispose()


def migrate(database: Database, revision: str = "head") -> None:
    """Upgrade using the same explicit transaction policy as command writes."""
    config = Config()
    config.set_main_option("script_location", "nexus:migrations")
    with database.write() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)
