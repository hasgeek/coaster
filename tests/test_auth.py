# -*- coding: utf-8 -*-

from __future__ import absolute_import, unicode_literals

import unittest

from flask_sqlalchemy import SQLAlchemy

from flask import Flask, _request_ctx_stack, has_request_context

from coaster.auth import (
    AuthAnchors,
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


class TestAuthAnchors(unittest.TestCase):
    """Tests for the AuthAnchors class"""

    def test_empty(self):
        """Test the AuthAnchors container"""
        empty = AuthAnchors()
        self.assertEqual(len(empty), 0)
        self.assertFalse(empty)
        self.assertEqual(empty, set())

    def test_prefilled(self):
        prefilled = AuthAnchors({1, 2})
        self.assertEqual(len(prefilled), 2)
        self.assertTrue(prefilled)
        self.assertIn(1, prefilled)
        self.assertIn(2, prefilled)
        self.assertNotIn(3, prefilled)
        self.assertEqual(prefilled, {1, 2})

    def test_postfilled(self):
        postfilled = AuthAnchors()
        self.assertEqual(len(postfilled), 0)
        postfilled._add(1)
        self.assertIn(1, postfilled)
        self.assertNotIn(2, postfilled)
        postfilled._add(2)
        self.assertIn(2, postfilled)
        self.assertEqual(postfilled, {1, 2})


class TestCurrentUserNoRequest(unittest.TestCase):
    def test_current_auth_no_request(self):
        self.assertTrue(current_auth.is_anonymous)
        self.assertFalse(current_auth.is_authenticated)
        self.assertIsNone(current_auth.user)


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
        self.assertTrue(current_auth.is_anonymous)
        self.assertFalse(current_auth.is_authenticated)
        self.assertIsNone(current_auth.user)


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
        self.assertTrue(current_auth.is_anonymous)
        self.assertFalse(current_auth.is_authenticated)
        self.assertFalse(current_auth)
        self.assertIsNone(current_auth.user)
        self.assertIsNone(current_auth.actor)

    def test_current_auth_with_user_unloaded(self):
        user = User(username='foo', fullname='Mr Foo')
        self.login_manager.set_user_for_testing(user)

        self.assertFalse(current_auth.is_anonymous)
        self.assertTrue(current_auth.is_authenticated)
        self.assertTrue(current_auth)
        self.assertIsNotNone(current_auth.user)
        self.assertEqual(current_auth.user, user)
        self.assertEqual(current_auth.actor, user)

        # Additional auth details (username only in this test) exposed by the login manager
        self.assertEqual(current_auth.username, 'foo')
        with self.assertRaises(AttributeError):
            self.assertEqual(current_auth.fullname, 'Mr Foo')

        # current_user is immutable
        with self.assertRaises(AttributeError):
            current_auth.username = 'bar'

        # For full attribute access, use the user object
        self.assertEqual(current_auth.user.username, 'foo')
        self.assertEqual(current_auth.user.fullname, 'Mr Foo')

    def test_current_auth_with_flask_login_user(self):
        user = User(username='foo', fullname='Mr Foo')
        _request_ctx_stack.top.user = user

        self.assertFalse(current_auth.is_anonymous)
        self.assertTrue(current_auth.is_authenticated)
        self.assertTrue(current_auth)
        self.assertIsNotNone(current_auth.user)
        self.assertEqual(current_auth.user, user)
        self.assertEqual(current_auth.actor, user)

    def test_current_auth_with_user_loaded(self):
        self.assertTrue(current_auth.is_anonymous)
        self.assertFalse(current_auth.is_authenticated)
        self.assertFalse(current_auth)
        self.assertIsNone(current_auth.user)
        self.assertIsNone(current_auth.actor)

        user = User(username='foo', fullname='Mr Foo')
        self.login_manager.set_user_for_testing(user, load=True)

        self.assertFalse(current_auth.is_anonymous)
        self.assertTrue(current_auth.is_authenticated)
        self.assertTrue(current_auth)
        self.assertIsNotNone(current_auth.user)
        self.assertEqual(current_auth.user, user)
        self.assertEqual(current_auth.actor, user)

    def test_anonymous_user(self):
        self.assertTrue(current_auth.is_anonymous)
        self.assertFalse(current_auth.is_authenticated)
        self.assertFalse(current_auth)
        self.assertIsNone(current_auth.user)

        user = AnonymousUser()
        self.login_manager.set_user_for_testing(user, load=True)

        # is_anonymous == True, but current_auth.user is not None
        self.assertTrue(current_auth.is_anonymous)
        self.assertIsNotNone(current_auth.user)
        # is_authenticated == True, since there is an actor
        self.assertTrue(current_auth.is_authenticated)
        self.assertTrue(current_auth)
        self.assertIsNotNone(current_auth.actor)
        self.assertEqual(current_auth.user, user)
        self.assertEqual(current_auth.actor, user)

    def test_invalid_auth_attribute(self):
        for attr in (
            'actor',
            'anchors',
            'is_anonymous',
            'not_anonymous',
            'is_authenticated',
            'not_authenticated',
        ):
            with self.assertRaises(AttributeError):
                add_auth_attribute(attr, None)

    def test_other_actor_authenticated(self):
        self.assertTrue(current_auth.is_anonymous)
        self.assertFalse(current_auth.is_authenticated)
        self.assertFalse(current_auth)
        self.assertIsNone(current_auth.user)

        client = Client()
        add_auth_attribute('client', client, actor=True)

        self.assertFalse(current_auth.is_anonymous)
        self.assertTrue(current_auth.is_authenticated)
        self.assertTrue(current_auth)
        self.assertIsNone(current_auth.user)  # It's not the user
        self.assertEqual(current_auth.client, client)  # There's now a client attribute
        self.assertEqual(current_auth.actor, client)  # The client is also the actor

    def test_auth_anchor(self):
        """A request starts with zero anchors, but they can be added"""
        self.assertFalse(current_auth.anchors)
        add_auth_anchor('test-anchor')
        self.assertTrue(current_auth.anchors)
        self.assertEqual(current_auth.anchors, {'test-anchor'})

    def test_has_current_auth(self):
        """request_has_auth indicates if current_auth was invoked during a request"""
        self.assertFalse(request_has_auth())
        current_auth.is_anonymous  # Invoke current_auth
        self.assertTrue(request_has_auth())
