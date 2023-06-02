"""Reusable fixtures for Coaster tests."""
# pylint: disable=redefined-outer-name

from os import environ
from typing import cast
import unittest

from flask import Flask
from flask.ctx import RequestContext
from flask_sqlalchemy import SQLAlchemy
import pytest
import sqlalchemy as sa

from coaster.sqlalchemy import DeclarativeBase, ModelBase, Query


class Model(ModelBase, DeclarativeBase):
    """Model base class for test models."""


db = SQLAlchemy(query_class=Query, metadata=Model.metadata)  # type: ignore[arg-type]
Model.init_flask_sqlalchemy(db)


# This is NOT a fixture
def sqlalchemy_uri() -> str:
    """Return SQLAlchemy database URI (deferring to value in environment)."""
    return environ.get(
        'FLASK_SQLALCHEMY_DATABASE_URI', 'postgresql+psycopg://localhost/coaster_test'
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
def clsapp(request: pytest.FixtureRequest, app: Flask) -> Flask:
    """App fixture in unittest class."""
    request.cls.app = app
    return app


@pytest.mark.usefixtures('clsapp')
class AppTestCase(unittest.TestCase):  # skipcq: PTC-W0046
    """Base class for unit tests that need self.app."""

    app: Flask
    ctx: RequestContext
    session: sa.orm.Session

    def setUp(self) -> None:
        """Prepare test context."""
        self.ctx = cast(RequestContext, self.app.test_request_context())
        self.ctx.push()
        db.create_all()
        self.session = cast(sa.orm.Session, db.session)
        # SQLAlchemy doesn't fire mapper_configured events until the first time a
        # mapping is used
        db.configure_mappers()

    def tearDown(self) -> None:
        """Teardown test context."""
        self.session.rollback()
        db.drop_all()
        self.ctx.pop()
