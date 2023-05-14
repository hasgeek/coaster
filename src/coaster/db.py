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

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.engine import Engine
import sqlalchemy.event as event  # pylint: disable=consider-using-from-import

try:
    from psycopg2.extensions import connection as PostgresConnection  # noqa: N812
except ModuleNotFoundError:
    PostgresConnection = None

__all__ = ['SQLAlchemy', 'db']


db = SQLAlchemy()


# Enable foreign key support in SQLite3. The command must
# be issued once per connection.
@event.listens_for(Engine, 'connect')
def _set_sqlite_pragma(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, SQLite3Connection):  # pragma: no cover
        cursor = dbapi_connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON;')
        cursor.close()


if PostgresConnection is not None:
    # Always use UTC timezone on PostgreSQL
    @event.listens_for(Engine, 'connect')
    def _set_postgresql_timezone(dbapi_connection, connection_record):
        if isinstance(dbapi_connection, PostgresConnection):  # pragma: no cover
            cursor = dbapi_connection.cursor()
            cursor.execute("SET TIME ZONE 'UTC';")
            cursor.close()
