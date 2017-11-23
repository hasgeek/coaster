# -*- coding: utf-8 -*-

from __future__ import absolute_import, unicode_literals
import unittest
from flask import Flask, _request_ctx_stack, has_request_context
from flask_sqlalchemy import SQLAlchemy
from coaster.user import current_user
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
            _request_ctx_stack.top.user = self.user


# --- Models ------------------------------------------------------------------

class User(BaseMixin, db.Model):
    __tablename__ = 'authenticated_user'
    username = db.Column(db.Unicode(80), nullable=False)
    fullname = db.Column(db.Unicode(80), nullable=False)


class AnonymousUser(BaseMixin, db.Model):
    __tablename__ = 'anonymous_user'
    is_anonymous = True
    username = None


# --- Tests -------------------------------------------------------------------

class TestCurrentUserNoRequest(unittest.TestCase):
    def test_current_user_no_request(self):
        self.assertTrue(current_user.is_anonymous)
        self.assertFalse(current_user.is_authenticated)
        self.assertIsNone(current_user.self)


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

    def test_current_user_no_login_manager(self):
        self.assertTrue(current_user.is_anonymous)
        self.assertFalse(current_user.is_authenticated)
        self.assertIsNone(current_user.self)


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

    def test_current_user_without_user(self):
        self.assertTrue(current_user.is_anonymous)
        self.assertFalse(current_user.is_authenticated)
        self.assertIsNone(current_user.self)

    def test_current_user_with_user_unloaded(self):
        user = User(username='foo', fullname="Mr Foo")
        self.login_manager.set_user_for_testing(user)

        self.assertFalse(current_user.is_anonymous)
        self.assertTrue(current_user.is_authenticated)
        self.assertIsNotNone(current_user.self)
        self.assertEqual(current_user.self, user)

        self.assertEqual(current_user.username, 'foo')
        self.assertEqual(current_user.self.username, 'foo')
        self.assertEqual(current_user.fullname, "Mr Foo")
        self.assertEqual(current_user.self.fullname, "Mr Foo")

        # Setting attributes passes them through
        current_user.username = 'bar'
        self.assertEqual(user.username, 'bar')

    def test_current_user_with_user_loaded(self):
        self.assertTrue(current_user.is_anonymous)
        self.assertFalse(current_user.is_authenticated)
        self.assertIsNone(current_user.self)

        user = User(username='foo', fullname="Mr Foo")
        self.login_manager.set_user_for_testing(user, load=True)

        self.assertFalse(current_user.is_anonymous)
        self.assertTrue(current_user.is_authenticated)
        self.assertIsNotNone(current_user.self)
        self.assertEqual(current_user.self, user)

    def test_anonymous_user(self):
        self.assertTrue(current_user.is_anonymous)
        self.assertFalse(current_user.is_authenticated)
        self.assertIsNone(current_user.self)

        user = AnonymousUser()
        self.login_manager.set_user_for_testing(user, load=True)

        # is_anonymous == True, but current_user.self is not None
        self.assertTrue(current_user.is_anonymous)
        self.assertFalse(current_user.is_authenticated)
        self.assertIsNotNone(current_user.self)
        self.assertEqual(current_user.username, None)
        # Attribute error raised if we try to access attributes that are not present
        with self.assertRaises(AttributeError):
            self.assertEqual(current_user.fullname, None)
