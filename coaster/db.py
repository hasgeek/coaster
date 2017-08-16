# -*- coding: utf-8 -*-

from __future__ import absolute_import
from flask_sqlalchemy import SQLAlchemy

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlite3 import Connection as SQLite3Connection
try:
    # PySqlite is only available for Python 2.x
    import pysqlite2.dbapi2
    PySQLite3Connection = pysqlite2.dbapi2.Connection
except ImportError:
    PySQLite3Connection = SQLite3Connection

__all__ = ['SQLAlchemy', 'db']


db = SQLAlchemy()


# Enable foreign key support in SQLite3. The command must
# be issued once per connection.
@event.listens_for(Engine, 'connect')
def _set_sqlite_pragma(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, (SQLite3Connection, PySQLite3Connection)):  # pragma: no cover
        cursor = dbapi_connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON;')
        cursor.close()
