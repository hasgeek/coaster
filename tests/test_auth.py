# -*- coding: utf-8 -*-

from __future__ import absolute_import, unicode_literals

import unittest

from flask_sqlalchemy import SQLAlchemy

from flask import Flask, _request_ctx_stack, has_request_context

import pytest

from coaster.auth import (
    add_auth_anchor,
    add_auth_attribute,
    current_auth,
    request_has_auth,
)
from coaster.sqlalchemy import BaseMixin

# --- App context -------------------------------------------------------------

db = SQLAlchemy()


class LoginManager(object):
    def __init__(self, app):
        app.login_manager = self
        self.user = None

    def set_user_for_testing(self, user, load=False):
        self.user = user
        if load:
            self._load_user()

    def _load_user(self):
        if has_request_context():
            add_auth_attribute('user', self.user)
            if self.user:
                add_auth_attribute('username', self.user.username)


# --- Models ------------------------------------------------------------------


class User(BaseMixin, db.Model):
    __tablename__ = 'authenticated_user'
    username = db.Column(db.Unicode(80))
    fullname = db.Column(db.Unicode(80))


class AnonymousUser(BaseMixin, db.Model):
    __tablename__ = 'anonymous_user'
    is_anonymous = True
    username = 'anon'
    fullname = 'Anonymous'


class Client(BaseMixin, db.Model):
    __tablename__ = 'client'


# --- Tests -------------------------------------------------------------------


class TestCurrentUserNoRequest(unittest.TestCase):
    def test_current_auth_no_request(self):
        assert current_auth.is_anonymous
        assert not current_auth.is_authenticated
        assert current_auth.user is None


class TestCurrentUserNoLoginManager(unittest.TestCase):
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    def setUp(self):
        db.init_app(self.app)
        self.ctx = self.app.test_request_context()
        self.ctx.push()
        db.create_all()
        self.session = db.session

    def tearDown(self):
        self.session.rollback()
        db.drop_all()
        self.ctx.pop()

    def test_current_auth_no_login_manager(self):
        assert current_auth.is_anonymous
        assert not current_auth.is_authenticated
        assert current_auth.user is None


class TestCurrentUserWithLoginManager(unittest.TestCase):
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    login_manager = LoginManager(app)

    def setUp(self):
        db.init_app(self.app)
        self.ctx = self.app.test_request_context()
        self.ctx.push()
        db.create_all()
        self.session = db.session

    def tearDown(self):
        self.login_manager.set_user_for_testing(None, load=True)
        self.session.rollback()
        db.drop_all()
        self.ctx.pop()

    def test_current_auth_without_user(self):
        assert current_auth.is_anonymous
        assert not current_auth.is_authenticated
        assert not current_auth
        assert current_auth.user is None
        assert current_auth.actor is None

    def test_current_auth_with_user_unloaded(self):
        user = User(username='foo', fullname='Mr Foo')
        self.login_manager.set_user_for_testing(user)

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

    def test_current_auth_with_flask_login_user(self):
        user = User(username='foo', fullname='Mr Foo')
        _request_ctx_stack.top.user = user

        assert not current_auth.is_anonymous
        assert current_auth.is_authenticated
        assert current_auth
        assert current_auth.user is not None
        assert current_auth.user == user
        assert current_auth.actor == user

    def test_current_auth_with_user_loaded(self):
        assert current_auth.is_anonymous
        assert not current_auth.is_authenticated
        assert not current_auth
        assert current_auth.user is None
        assert current_auth.actor is None

        user = User(username='foo', fullname='Mr Foo')
        self.login_manager.set_user_for_testing(user, load=True)

        assert not current_auth.is_anonymous
        assert current_auth.is_authenticated
        assert current_auth
        assert current_auth.user is not None
        assert current_auth.user == user
        assert current_auth.actor == user

    def test_anonymous_user(self):
        assert current_auth.is_anonymous
        assert not current_auth.not_anonymous
        assert not current_auth.is_authenticated
        assert current_auth.not_authenticated
        assert not current_auth
        assert current_auth.user is None

        user = AnonymousUser()
        self.login_manager.set_user_for_testing(user, load=True)

        # is_anonymous == True, but current_auth.user is not None
        assert current_auth.is_anonymous
        assert current_auth.user is not None
        # is_authenticated == True, since there is an actor
        assert current_auth.is_authenticated
        assert current_auth
        assert current_auth.actor is not None
        assert current_auth.user == user
        assert current_auth.actor == user

    def test_invalid_auth_attribute(self):
        for attr in (
            'actor',
            'anchors',
            'is_anonymous',
            'not_anonymous',
            'is_authenticated',
            'not_authenticated',
        ):
            with pytest.raises(AttributeError):
                add_auth_attribute(attr, None)

    def test_other_actor_authenticated(self):
        assert current_auth.is_anonymous
        assert not current_auth.is_authenticated
        assert not current_auth
        assert current_auth.user is None

        client = Client()
        add_auth_attribute('client', client, actor=True)

        assert not current_auth.is_anonymous
        assert current_auth.is_authenticated
        assert current_auth
        assert current_auth.user is None  # It's not the user
        assert current_auth.client == client  # There's now a client attribute
        assert current_auth.actor == client  # The client is also the actor

    def test_auth_anchor(self):
        """A request starts with zero anchors, but they can be added"""
        assert not current_auth.anchors
        add_auth_anchor('test-anchor')
        assert current_auth.anchors
        assert current_auth.anchors == {'test-anchor'}

    def test_has_current_auth(self):
        """request_has_auth indicates if current_auth was invoked during a request"""
        assert not request_has_auth()
        # Invoke current_auth
        current_auth.is_anonymous  # skipcq: PYL-W0104
        assert request_has_auth()
