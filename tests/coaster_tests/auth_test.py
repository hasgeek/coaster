"""Test current_auth."""

# pylint: disable=redefined-outer-name

import typing as t
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from flask import Flask, g, has_request_context, render_template_string
from sqlalchemy.orm import Mapped

from coaster.auth import (
    add_auth_anchor,
    add_auth_attribute,
    current_auth,
    request_has_auth,
)
from coaster.sqlalchemy import BaseMixin

from .conftest import Model, db
from .sqlalchemy_models_test import User

# The unused imports above are present to mitigate a bug in sqlalchemy2-stubs for mypy

# --- App context ----------------------------------------------------------------------


class LoginManager:
    """Test login manager implementing _load_user method."""

    def __init__(self, _app: Flask) -> None:
        _app.login_manager = self  # type: ignore[attr-defined]
        self.user: t.Optional[User] = None

    def set_user_for_testing(self, user: User, load: bool = False) -> None:
        """Test auth by setting a user."""
        self.user = user
        if load:
            self._load_user()

    def _load_user(self) -> None:
        """Load user into current_auth."""
        if has_request_context():
            add_auth_attribute('user', self.user)
            if self.user:
                add_auth_attribute('username', self.user.username)


class FlaskLoginManager(LoginManager):
    """Test login manager implementing _load_user but only setting ``g._login_user``."""

    def _load_user(self) -> None:
        if g:
            g._login_user = self.user  # pylint: disable=protected-access


# --- Models ---------------------------------------------------------------------------


@pytest.fixture(scope='module')
def models() -> SimpleNamespace:
    """Model fixtures."""
    # pylint: disable=possibly-unused-variable

    class User(BaseMixin, Model):
        """Test user model."""

        __tablename__ = 'authenticated_user'
        username: Mapped[str] = sa.orm.mapped_column(sa.Unicode(80))
        fullname: Mapped[str] = sa.orm.mapped_column(sa.Unicode(80))

        def __repr__(self) -> str:
            return f'User(username={self.username!r}, fullname={self.fullname!r})'

    class AnonUser(BaseMixin, Model):
        """Test anonymous user model."""

        __tablename__ = 'anon_user'
        is_anonymous = True
        username = 'anon'
        fullname = 'Anonymous'

        def __repr__(self) -> str:
            return f'AnonUser(username={self.username!r}, fullname={self.fullname!r})'

    class Client(BaseMixin, Model):
        """Test client model."""

        __tablename__ = 'client'

    return SimpleNamespace(**locals())


# --- Fixtures -------------------------------------------------------------------------


@pytest.fixture()
def login_manager(app: Flask) -> t.Iterator[LoginManager]:
    """Login manager fixture."""
    yield LoginManager(app)
    del app.login_manager  # type: ignore[attr-defined]


@pytest.fixture()
def flask_login_manager(app: Flask) -> t.Iterator[FlaskLoginManager]:
    """Flask-Login style login manager fixture."""
    yield FlaskLoginManager(app)
    del app.login_manager  # type: ignore[attr-defined]


@pytest.fixture()
def request_ctx(app: Flask) -> t.Iterator:
    """Request context with database models."""
    ctx = app.test_request_context()
    ctx.push()
    db.create_all()
    yield ctx
    db.session.rollback()
    db.drop_all()
    ctx.pop()


# --- Tests ----------------------------------------------------------------------------


def test_current_auth_no_request() -> None:
    """Test for current_auth in placeholder mode with no app or request context."""
    assert current_auth.is_anonymous
    assert not current_auth.is_authenticated
    assert current_auth.user is None


@pytest.mark.usefixtures('request_ctx')
def test_current_auth_no_login_manager() -> None:
    """Test current_auth without a login manager."""
    assert current_auth.is_anonymous
    assert not current_auth.is_authenticated
    assert current_auth.user is None


@pytest.mark.usefixtures('request_ctx', 'login_manager')
def test_current_auth_without_user() -> None:
    """Test current_auth being used without a user."""
    assert current_auth.is_anonymous
    assert not current_auth.is_authenticated
    assert not current_auth
    assert current_auth.user is None
    assert current_auth.actor is None


@pytest.mark.usefixtures('request_ctx')
def test_current_auth_with_user(
    models: SimpleNamespace, login_manager: LoginManager
) -> None:
    """Test current_auth with a user via the login manager."""
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

    # current_auth is immutable
    with pytest.raises(TypeError, match="current_auth is read-only"):
        current_auth.username = 'bar'

    # For full attribute access, use the user object
    assert current_auth.user.username == 'foo'
    assert current_auth.user.fullname == 'Mr Foo'


@pytest.mark.usefixtures('request_ctx')
def test_current_auth_with_flask_login_user_implicit(
    app: Flask, models: SimpleNamespace
) -> None:
    """Flask-Login's user is no longer implicitly valid."""
    assert not hasattr(app, 'login_manager')
    user = models.User(username='bar', fullname='Ms Bar')
    g._login_user = user  # pylint: disable=protected-access

    assert current_auth.is_anonymous
    assert not current_auth.is_authenticated
    assert not current_auth
    assert current_auth.user is None


@pytest.mark.usefixtures('request_ctx')
def test_current_auth_with_flask_login_user_explicit(
    models: SimpleNamespace, flask_login_manager: FlaskLoginManager
) -> None:
    """Flask-Login's login manager is called and its user is accepted."""
    user = models.User(username='baz', fullname='Mr Baz')
    flask_login_manager.set_user_for_testing(user)

    assert not current_auth.is_anonymous
    assert current_auth.is_authenticated
    assert current_auth
    assert current_auth.user is not None
    assert current_auth.user == user


@pytest.mark.usefixtures('request_ctx')
def test_current_auth_with_user_loaded(
    models: SimpleNamespace, login_manager: LoginManager
) -> None:
    """Test for current_auth working when the login manager is able to load a user."""
    assert current_auth.is_anonymous
    assert not current_auth.is_authenticated
    assert not current_auth
    assert current_auth.user is None
    assert current_auth.actor is None

    user = models.User(username='qux', fullname='Ms Qux')
    login_manager.set_user_for_testing(user, load=True)

    assert not current_auth.is_anonymous
    assert current_auth.is_authenticated  # type: ignore[unreachable]
    assert current_auth
    assert current_auth.user is not None
    assert current_auth.user == user
    assert current_auth.actor == user


@pytest.mark.usefixtures('request_ctx')
def test_anonymous_user(models: SimpleNamespace, login_manager: LoginManager) -> None:
    """Test for current_auth having an anonymous actor."""
    assert current_auth.is_anonymous
    assert not current_auth.is_authenticated
    assert not current_auth
    assert current_auth.user is None

    user = models.AnonUser()
    login_manager.set_user_for_testing(user, load=True)

    # is_authenticated == True, since there is an actor
    assert current_auth.is_authenticated
    assert current_auth  # type: ignore[unreachable]
    assert current_auth.actor is not None
    assert current_auth.user == user
    assert current_auth.actor == user


@pytest.mark.usefixtures('request_ctx', 'login_manager')
def test_invalid_auth_attribute() -> None:
    """Test to confirm current_auth will not accept reserved keywords as attrs."""
    for attr in (
        'actor',
        'anchors',
        'is_anonymous',
        'is_authenticated',
    ):
        with pytest.raises(AttributeError):
            add_auth_attribute(attr, None)


@pytest.mark.usefixtures('request_ctx', 'login_manager')
def test_other_actor_authenticated(models: SimpleNamespace) -> None:
    """Test for current_auth having an actor who is not a user."""
    assert current_auth.is_anonymous
    assert not current_auth.is_authenticated
    assert not current_auth
    assert current_auth.user is None

    client = models.Client()
    add_auth_attribute('client', client, actor=True)

    assert not current_auth.is_anonymous
    assert current_auth.is_authenticated  # type: ignore[unreachable]
    assert current_auth
    assert current_auth.user is None  # It's not the user
    assert current_auth.client == client  # There's now a client attribute
    assert current_auth.actor == client  # The client is also the actor


@pytest.mark.usefixtures('request_ctx', 'login_manager')
def test_auth_anchor() -> None:
    """A request starts with zero anchors, but they can be added"""
    assert not current_auth.anchors
    add_auth_anchor('test-anchor')
    assert current_auth.anchors
    assert current_auth.anchors == {'test-anchor'}


@pytest.mark.usefixtures('request_ctx', 'login_manager')
def test_has_current_auth() -> None:
    """Test that request_has_auth indicates if current_auth was invoked."""
    assert not request_has_auth()
    # Invoke current_auth without checking for a user
    assert not current_auth.is_placeholder
    assert not request_has_auth()
    # Invoke current_auth to check for a user
    current_auth.is_anonymous  # pylint: disable=W0104
    assert request_has_auth()


@pytest.mark.usefixtures('request_ctx', 'login_manager')
def test_jinja2_no_auth(app: Flask) -> None:
    """Test that current_auth is available in Jinja2 and has no side effects."""
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


@pytest.mark.usefixtures('request_ctx')
def test_jinja2_auth(
    app: Flask, models: SimpleNamespace, login_manager: LoginManager
) -> None:
    """Test that current_auth is available in Jinja2 and records if it was used."""
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
