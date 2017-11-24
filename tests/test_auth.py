# -*- coding: utf-8 -*-

from __future__ import absolute_import, unicode_literals
import unittest
from flask import Flask, has_request_context
from flask_sqlalchemy import SQLAlchemy
from coaster.auth import add_auth_attribute, current_auth
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


# --- Tests -------------------------------------------------------------------

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
        self.assertIsNone(current_auth.user)

    def test_current_auth_with_user_unloaded(self):
        user = User(username='foo', fullname='Mr Foo')
        self.login_manager.set_user_for_testing(user)

        self.assertFalse(current_auth.is_anonymous)
        self.assertTrue(current_auth.is_authenticated)
        self.assertIsNotNone(current_auth.user)
        self.assertEqual(current_auth.user, user)

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

    def test_current_auth_with_user_loaded(self):
        self.assertTrue(current_auth.is_anonymous)
        self.assertFalse(current_auth.is_authenticated)
        self.assertIsNone(current_auth.user)

        user = User(username='foo', fullname='Mr Foo')
        self.login_manager.set_user_for_testing(user, load=True)

        self.assertFalse(current_auth.is_anonymous)
        self.assertTrue(current_auth.is_authenticated)
        self.assertIsNotNone(current_auth.user)
        self.assertEqual(current_auth.user, user)

    def test_anonymous_user(self):
        self.assertTrue(current_auth.is_anonymous)
        self.assertFalse(current_auth.is_authenticated)
        self.assertIsNone(current_auth.user)

        user = AnonymousUser()
        self.login_manager.set_user_for_testing(user, load=True)

        # is_anonymous == True, but current_auth.user is not None
        self.assertTrue(current_auth.is_anonymous)
        self.assertFalse(current_auth.is_authenticated)
        self.assertIsNotNone(current_auth.user)
        self.assertEqual(current_auth.user.username, 'anon')
