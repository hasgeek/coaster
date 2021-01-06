from __future__ import absolute_import

from sqlite3 import Connection as SQLite3Connection

from flask_sqlalchemy import SQLAlchemy
from psycopg2.extensions import connection as PostgresConnection  # NOQA: N812
from sqlalchemy import event
from sqlalchemy.engine import Engine

try:
    # PySqlite is only available for Python 2.x
    import pysqlite2.dbapi2

    PySQLite3Connection = pysqlite2.dbapi2.Connection  # pragma: no cover
except ImportError:
    PySQLite3Connection = SQLite3Connection

__all__ = ['SQLAlchemy', 'db']


db = SQLAlchemy()


# Enable foreign key support in SQLite3. The command must
# be issued once per connection.
@event.listens_for(Engine, 'connect')
def _set_sqlite_pragma(dbapi_connection, connection_record):
    if isinstance(  # pragma: no cover
        dbapi_connection, (SQLite3Connection, PySQLite3Connection)
    ):
        cursor = dbapi_connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON;')
        cursor.close()


# Always use UTC timezone on PostgreSQL
@event.listens_for(Engine, 'connect')
def _set_postgresql_timezone(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, PostgresConnection):  # pragma: no cover
        cursor = dbapi_connection.cursor()
        cursor.execute("SET TIME ZONE 'UTC';")
        cursor.close()
