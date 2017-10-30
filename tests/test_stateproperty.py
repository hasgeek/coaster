# -*- coding: utf-8 -*-

from __future__ import absolute_import

import unittest
from datetime import datetime, timedelta
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from coaster.utils import LabeledEnum
from coaster.sqlalchemy import BaseMixin, StateProperty


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


# --- Models ------------------------------------------------------------------

class MY_STATE(LabeledEnum):
    DRAFT = (0, "Draft")
    PENDING = (1, 'pending', "Pending")
    PUBLISHED = (2, "Published")

    UNPUBLISHED = {DRAFT, PENDING}


class MyPost(BaseMixin, db.Model):
    _state = db.Column('state', db.Integer, default=MY_STATE.DRAFT, nullable=False)
    state = StateProperty('_state', MY_STATE, doc="Post state")
    datetime = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    state.add_state('RECENT', MY_STATE.PUBLISHED,
        lambda post: post.datetime > datetime.utcnow() - timedelta(hours=1))

    @state.transition(MY_STATE.DRAFT, MY_STATE.PENDING)
    def submit(self):
        pass

    @state.transition(MY_STATE.UNPUBLISHED, MY_STATE.PUBLISHED)
    def publish(self):
        if self.state.DRAFT:
            # Use TypeError to distinguish from the wrapper's ValueError in tests below
            raise TypeError("We don't actually support transitioning from draft to published")
        self.datetime = datetime.utcnow()


# --- Tests -------------------------------------------------------------------

class TestStateProperty(unittest.TestCase):
    """SQLite tests"""
    app = app

    def setUp(self):
        self.ctx = self.app.test_request_context()
        self.ctx.push()
        db.create_all()
        self.session = db.session

        self.post = MyPost()
        self.session.add(self.post)
        self.session.commit()

    def tearDown(self):
        self.session.rollback()
        db.drop_all()
        self.ctx.pop()

    def test_has_state(self):
        """
        A post has a state that can be tested with stateproperty.NAME
        """
        self.assertEqual(self.post._state, MY_STATE.DRAFT)
        self.assertEqual(self.post.state(), MY_STATE.DRAFT)
        self.assertTrue(self.post.state.DRAFT)
        self.assertFalse(self.post.state.PENDING)
        self.assertFalse(self.post.state.PUBLISHED)
        self.assertTrue(self.post.state.UNPUBLISHED)

    def test_change_state(self):
        """
        When a post's state changes, the tests continue to work
        """
        self.assertTrue(self.post.state.DRAFT)
        self.post.state = MY_STATE.PENDING
        self.assertFalse(self.post.state.DRAFT)
        self.assertTrue(self.post.state.PENDING)

    def test_change_state_invalid(self):
        """
        State cannot be changed to an invalid value
        """
        with self.assertRaises(ValueError):
            self.post.state = 100

    def test_is_state(self):
        """
        A state can be tested using the `is_*` name, which is then uppercased to find the value
        """
        self.assertTrue(self.post.state.is_draft)
        self.assertTrue(self.post.state.is_unpublished)
        self.post.state = MY_STATE.PUBLISHED
        self.assertFalse(self.post.state.is_unpublished)
        self.assertTrue(self.post.state.is_published)

    def test_added_state(self):
        """
        Added states include custom validators which are called to confirm the state
        """
        self.assertTrue(self.post.state.DRAFT)
        self.assertFalse(self.post.state.RECENT)
        self.post.state = MY_STATE.PUBLISHED
        self.assertTrue(self.post.state.RECENT)
        self.assertTrue(self.post.state.is_recent)
        self.post.datetime = datetime.utcnow() - timedelta(hours=2)
        self.assertFalse(self.post.state.RECENT)
        self.assertFalse(self.post.state.is_recent)

    def test_sql_query_filter_length(self):
        self.assertEqual(len(MyPost.state.DRAFT), 1)
        self.assertEqual(len(MyPost.state.PENDING), 1)
        self.assertEqual(len(MyPost.state.UNPUBLISHED), 1)
        self.assertEqual(len(MyPost.state.RECENT), 2)  # This one has two filter conditions

    def test_sql_query_single_value(self):
        post1 = MyPost.query.filter(*MyPost.state.DRAFT).first()
        self.assertEqual(post1.id, self.post.id)
        post2 = MyPost.query.filter(*MyPost.state.PENDING).first()
        self.assertIsNone(post2)

    def test_sql_query_multi_value(self):
        post1 = MyPost.query.filter(*MyPost.state.UNPUBLISHED).first()
        self.assertEqual(post1.id, self.post.id)
        self.post.state = MY_STATE.PUBLISHED
        self.session.commit()
        post2 = MyPost.query.filter(*MyPost.state.UNPUBLISHED).first()
        self.assertIsNone(post2)

    def test_sql_query_added_state(self):
        post1 = MyPost.query.filter(*MyPost.state.RECENT).first()
        self.assertIsNone(post1)
        self.post.state = MY_STATE.PUBLISHED
        self.session.commit()
        post2 = MyPost.query.filter(*MyPost.state.RECENT).first()
        self.assertEqual(post2.id, self.post.id)

    def test_transition_submit(self):
        self.assertEqual(self.post.state(), MY_STATE.DRAFT)
        self.post.submit()
        self.assertEqual(self.post.state(), MY_STATE.PENDING)
        with self.assertRaises(ValueError):
            # Can only be called in draft state, which we are no longer in
            self.post.submit()
        # If there's an error, the state does not change
        self.assertEqual(self.post.state(), MY_STATE.PENDING)

    def test_transition_publish_invalid(self):
        self.assertTrue(self.post.state.is_draft)
        with self.assertRaises(TypeError):
            # publish() should raise TypeError if we're a draft (custom exception, not decorator's)
            self.post.publish()
        # If there's an error, the state does not change
        self.assertTrue(self.post.state.is_draft)

    def test_transition_publish_datetime(self):
        self.assertTrue(self.post.state.is_draft)
        self.post.submit()
        self.assertTrue(self.post.state.is_pending)
        self.post.datetime = None
        self.post.publish()
        self.assertIsNotNone(self.post.datetime)
