"""Test current_auth."""

# These unused imports are present to mitigate a bug in sqlalchemy2-stubs for mypy
from types import SimpleNamespace
import typing as t  # noqa: F401  # pylint: disable=unused-import
import uuid as uuid_  # noqa: F401  # pylint: disable=unused-import

from flask_sqlalchemy import SQLAlchemy
import sqlalchemy as sa  # noqa: F401  # pylint: disable=unused-import

from flask import Flask, g, has_request_context, render_template_string

import pytest

from coaster.auth import (
    add_auth_anchor,
    add_auth_attribute,
    current_auth,
    request_has_auth,
)
from coaster.sqlalchemy import BaseMixin

# --- App context ----------------------------------------------------------------------


class LoginManager:  # pylint: disable=too-few-public-methods
    """Test login manager implementing _load_user method."""

    def __init__(self, app):  # pylint: disable=redefined-outer-name
        app.login_manager = self
        self.user = None

    def set_user_for_testing(self, user, load=False):
        """Test auth by setting a user."""
        self.user = user
        if load:
            self._load_user()

    def _load_user(self):
        """Load user into current_auth."""
        if has_request_context():
            add_auth_attribute('user', self.user)
            if self.user:
                add_auth_attribute('username', self.user.username)


# --- Models ---------------------------------------------------------------------------


@pytest.fixture(scope='module')
def models(db) -> SimpleNamespace:
    """Model fixtures."""
    # pylint: disable=possibly-unused-variable

    class User(BaseMixin, db.Model):  # type: ignore[name-defined]
        """Test user model."""

        __tablename__ = 'authenticated_user'
        username = db.Column(db.Unicode(80))
        fullname = db.Column(db.Unicode(80))

    class AnonymousUser(BaseMixin, db.Model):  # type: ignore[name-defined]
        """Test anonymous user model."""

        __tablename__ = 'anonymous_user'
        is_anonymous = True
        username = 'anon'
        fullname = 'Anonymous'

    class Client(BaseMixin, db.Model):  # type: ignore[name-defined]
        """Test client model."""

        __tablename__ = 'client'

    return SimpleNamespace(**locals())


# --- Fixtures -------------------------------------------------------------------------


@pytest.fixture(scope='module')
def app() -> Flask:
    """App fixture."""
    _app = Flask(__name__)
    _app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    _app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    return _app


@pytest.fixture(scope='module')
def db(app) -> SQLAlchemy:
    """Database fixture."""
    _db = SQLAlchemy(app)
    return _db


@pytest.fixture()
def login_manager(app):
    """Login manager fixture."""
    return LoginManager(app)


@pytest.fixture()
def ctx(app, db):
    """App request context with database models."""
    db.init_app(app)
    _ctx = app.test_request_context()
    _ctx.push()
    db.create_all()
    yield _ctx
    db.session.rollback()
    db.drop_all()
    _ctx.pop()


# --- Tests ----------------------------------------------------------------------------


def test_current_auth_no_request():
    """Test case for no app or request context."""
    assert current_auth.is_anonymous
    assert not current_auth.is_authenticated
    assert current_auth.user is None


@pytest.mark.usefixtures('ctx')
def test_current_auth_no_login_manager():
    """Test current_auth without a login manager."""
    assert current_auth.is_anonymous
    assert not current_auth.is_authenticated
    assert current_auth.user is None


@pytest.mark.usefixtures('ctx', 'login_manager')
def test_current_auth_without_user():
    assert current_auth.is_anonymous
    assert not current_auth.is_authenticated
    assert not current_auth
    assert current_auth.user is None
    assert current_auth.actor is None


@pytest.mark.usefixtures('ctx')
def test_current_auth_with_user_unloaded(models, login_manager):
    user = models.User(username='foo', fullname='Mr Foo')
    login_manager.set_user_for_testing(user)

    assert not current_auth.is_anonymous
    assert current_auth.is_authenticated
    assert current_auth
    assert current_auth.user is not None
    assert current_auth.user == user
    assert current_auth.actor == user

    # Additional auth details (username only in this test) exposed by the login manager
    assert current_auth.username == 'foo'
    with pytest.raises(AttributeError):
        assert current_auth.fullname == 'Mr Foo'

    # current_user is immutable
    with pytest.raises(AttributeError):
        current_auth.username = 'bar'

    # For full attribute access, use the user object
    assert current_auth.user.username == 'foo'
    assert current_auth.user.fullname == 'Mr Foo'


@pytest.mark.usefixtures('ctx', 'login_manager')
def test_current_auth_with_flask_login_user(models):
    user = models.User(username='foo', fullname='Mr Foo')
    g._login_user = user  # pylint: disable=protected-access

    assert not current_auth.is_anonymous
    assert current_auth.is_authenticated
    assert current_auth
    assert current_auth.user is not None
    assert current_auth.user == user
    assert current_auth.actor == user


@pytest.mark.usefixtures('ctx')
def test_current_auth_with_user_loaded(models, login_manager):
    assert current_auth.is_anonymous
    assert not current_auth.is_authenticated
    assert not current_auth
    assert current_auth.user is None
    assert current_auth.actor is None

    user = models.User(username='foo', fullname='Mr Foo')
    login_manager.set_user_for_testing(user, load=True)

    assert not current_auth.is_anonymous
    assert current_auth.is_authenticated
    assert current_auth
    assert current_auth.user is not None
    assert current_auth.user == user  # type: ignore[unreachable]
    assert current_auth.actor == user


@pytest.mark.usefixtures('ctx')
def test_anonymous_user(models, login_manager):
    assert current_auth.is_anonymous
    assert not current_auth.is_authenticated
    assert not current_auth
    assert current_auth.user is None

    user = models.AnonymousUser()
    login_manager.set_user_for_testing(user, load=True)

    # is_authenticated == True, since there is an actor
    assert current_auth.is_authenticated  # type: ignore[unreachable]
    assert current_auth
    assert current_auth.actor is not None
    assert current_auth.user == user
    assert current_auth.actor == user


@pytest.mark.usefixtures('ctx', 'login_manager')
def test_invalid_auth_attribute():
    for attr in (
        'actor',
        'anchors',
        'is_anonymous',
        'is_authenticated',
    ):
        with pytest.raises(AttributeError):
            add_auth_attribute(attr, None)


@pytest.mark.usefixtures('ctx', 'login_manager')
def test_other_actor_authenticated(models):
    assert current_auth.is_anonymous
    assert not current_auth.is_authenticated
    assert not current_auth
    assert current_auth.user is None

    client = models.Client()
    add_auth_attribute('client', client, actor=True)

    assert not current_auth.is_anonymous
    assert current_auth.is_authenticated
    assert current_auth
    assert current_auth.user is None  # It's not the user
    assert current_auth.client == client  # There's now a client attribute
    assert current_auth.actor == client  # The client is also the actor


@pytest.mark.usefixtures('ctx', 'login_manager')
def test_auth_anchor():
    """A request starts with zero anchors, but they can be added"""
    assert not current_auth.anchors
    add_auth_anchor('test-anchor')
    assert current_auth.anchors
    assert current_auth.anchors == {'test-anchor'}


@pytest.mark.usefixtures('ctx', 'login_manager')
def test_has_current_auth():
    """request_has_auth indicates if current_auth was invoked during a request"""
    assert not request_has_auth()
    # Invoke current_auth
    current_auth.is_anonymous  # pylint: disable=W0104
    assert request_has_auth()


@pytest.mark.usefixtures('ctx', 'login_manager')
def test_jinja2_no_auth(app):
    """Test that current_auth is available in Jinja2."""
    app.jinja_env.globals['current_auth'] = current_auth
    assert not request_has_auth()
    assert render_template_string("{% if config %}Yes{% else %}No{% endif %}") == 'Yes'
    assert not request_has_auth()
    assert (
        render_template_string('{% if current_auth %}Yes{% else %}No{% endif %}')
        == 'No'
    )
    assert (
        render_template_string(
            '{% if current_auth.is_authenticated %}Yes{% else %}No{% endif %}'
        )
        == 'No'
    )
    assert request_has_auth()


@pytest.mark.usefixtures('ctx')
def test_jinja2_auth(app, models, login_manager):
    """Test that current_auth is available in Jinja2."""
    app.jinja_env.globals['current_auth'] = current_auth
    user = models.User(username='user', fullname="User")
    login_manager.set_user_for_testing(user)
    assert not request_has_auth()
    assert render_template_string("{% if config %}Yes{% else %}No{% endif %}") == 'Yes'
    assert not request_has_auth()
    assert (
        render_template_string('{% if current_auth %}Yes{% else %}No{% endif %}')
        == 'Yes'
    )
    assert request_has_auth()
    assert (
        render_template_string(
            '{% if current_auth.is_authenticated %}Yes{% else %}No{% endif %}'
        )
        == 'Yes'
    )
    assert request_has_auth()
    assert render_template_string('{{ current_auth.user.username }}') == 'user'
