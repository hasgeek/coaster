"""
Flask-SQLAlchemy instance
-------------------------

.. deprecated:: 0.7.0
    Coaster provides a global instance of Flask-SQLAlchemy for convenience, but this is
    deprecated as of Flask-SQLAlchemy 3.0 as it now applies metadata isolation between
    binds even within the same app.
"""

from __future__ import annotations

from sqlite3 import Connection as SQLite3Connection
from typing import Any

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine

from .sqlalchemy import Query

try:
    from psycopg2.extensions import connection as Psycopg2Connection  # noqa: N812
except ModuleNotFoundError:
    Psycopg2Connection = None

try:
    from psycopg import Connection as Psycopg3Connection
except ModuleNotFoundError:
    Psycopg3Connection = None  # type: ignore[assignment,misc]

__all__ = ['SQLAlchemy', 'db']


db = SQLAlchemy(query_class=Query)  # type: ignore[arg-type]


@event.listens_for(Engine, 'connect')
def _emit_engine_directives(dbapi_connection: Any, _connection_record: Any) -> None:
    if isinstance(dbapi_connection, SQLite3Connection):  # pragma: no cover
        # Enable foreign key support in SQLite3. The command must
        # be issued once per connection.
        cursor: Any = dbapi_connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON;')
        cursor.close()
    if (
        Psycopg2Connection is not None
        and isinstance(dbapi_connection, Psycopg2Connection)
        or Psycopg3Connection is not None
        and isinstance(dbapi_connection, Psycopg3Connection)
    ):
        # Always use UTC timezone on PostgreSQL
        cursor = dbapi_connection.cursor()
        cursor.execute("SET TIME ZONE 'UTC';")
        cursor.close()
