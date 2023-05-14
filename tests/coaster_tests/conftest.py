"""Reusable fixtures for Coaster tests."""
# pylint: disable=redefined-outer-name

from os import environ

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import pytest

db = SQLAlchemy()


# This is NOT a fixture
def sqlalchemy_uri() -> str:
    """Return SQLAlchemy database URI (deferring to value in environment)."""
    return environ.get(
        'FLASK_SQLALCHEMY_DATABASE_URI', 'postgresql://localhost/coaster_test'
    )


@pytest.fixture(scope='module')
def app() -> Flask:
    """App fixture."""
    _app = Flask(__name__)
    _app.config['SQLALCHEMY_DATABASE_URI'] = sqlalchemy_uri()
    _app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(_app)
    return _app


@pytest.fixture(scope='class')
def clsapp(request, app: Flask) -> Flask:
    """App fixture in unittest class."""
    request.cls.app = app
    return app
