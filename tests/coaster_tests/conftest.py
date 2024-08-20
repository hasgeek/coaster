"""Reusable fixtures for Coaster tests."""

# pylint: disable=redefined-outer-name

from __future__ import annotations

import asyncio
import contextvars
import sys
import traceback
import unittest
from collections.abc import Coroutine, Generator
from os import environ
from pathlib import Path
from typing import Any, Optional, Union, cast

import pytest
import sqlalchemy.orm as sa_orm
from flask import Flask
from flask.ctx import RequestContext
from flask_sqlalchemy import SQLAlchemy

from coaster.sqlalchemy import DeclarativeBase, ModelBase, Query

collect_ignore: list[str] = []
if sys.version_info < (3, 10):
    collect_ignore.append('utils_classes_dataclass_match_test.py')


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
    session: sa_orm.Session

    def setUp(self) -> None:
        """Prepare test context."""
        self.ctx = self.app.test_request_context()
        self.ctx.push()
        # SQLAlchemy doesn't fire mapper_configured events until the first time a
        # mapping is used
        db.configure_mappers()
        db.create_all()
        self.session = cast(sa_orm.Session, db.session)
        db.engine.echo = False

    def tearDown(self) -> None:
        """Teardown test context."""
        db.engine.echo = False
        self.session.rollback()
        db.drop_all()
        self.ctx.pop()


# Patch for asyncio tests, adapted from
# https://github.com/Donate4Fun/donate4fun/blob/273a4e/tests/fixtures.py


class CustomEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    def __init__(self, context: Optional[contextvars.Context]) -> None:
        super().__init__()
        self.context = context

    def task_factory(
        self,
        loop: asyncio.AbstractEventLoop,
        factory: Union[Coroutine, Generator],
        context: Optional[contextvars.Context] = None,
    ) -> Task311:
        if context is None:
            context = self.context
        stack = traceback.extract_stack()
        for frame in stack[-2::-1]:
            package_name = Path(frame.filename).parts[-2]
            if package_name != 'asyncio':
                if package_name == 'pytest_asyncio':
                    # This function was called from pytest_asyncio, use shared context
                    break
                # This function was called from somewhere else, create context copy
                context = None
                break
        return Task311(factory, loop=loop, context=context)

    def new_event_loop(self) -> asyncio.AbstractEventLoop:
        loop = super().new_event_loop()
        loop.set_task_factory(self.task_factory)  # type: ignore[arg-type]
        return loop


@pytest.fixture(scope='session')
def event_loop_policy() -> Generator[CustomEventLoopPolicy, Any, None]:
    policy = CustomEventLoopPolicy(contextvars.copy_context())
    yield policy
    policy.get_event_loop().close()


# pylint: disable=protected-access
class Task311(asyncio.tasks._PyTask):  # type: ignore[name-defined]
    """Backport of Task from CPython 3.11 for passing context from fixture to test."""

    def __init__(
        self,
        coro: Union[Coroutine, Generator],
        *,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        name: Optional[str] = None,
        context: Optional[contextvars.Context] = None,
    ) -> None:
        super(
            asyncio.tasks._PyTask,  # type: ignore[attr-defined]
            self,
        ).__init__(loop=loop)
        if self._source_traceback:
            del self._source_traceback[-1]
        if not asyncio.coroutines.iscoroutine(coro):
            # raise after Future.__init__(), attrs are required for __del__
            # prevent logging for pending task in __del__
            self._log_destroy_pending = False
            raise TypeError(f"a coroutine was expected, got {coro!r}")

        if name is None:
            self._name = f'Task-{asyncio.tasks._task_name_counter()}'  # type: ignore[attr-defined]
        else:
            self._name = str(name)

        self._num_cancels_requested = 0
        self._must_cancel = False
        self._fut_waiter = None
        self._coro = coro
        if context is None:
            self._context = contextvars.copy_context()
        else:
            self._context = context

        self._loop.call_soon(self._Task__step, context=self._context)
        asyncio.tasks._register_task(self)
