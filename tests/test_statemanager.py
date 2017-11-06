# -*- coding: utf-8 -*-

from __future__ import absolute_import

import unittest
from datetime import datetime, timedelta
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from coaster.utils import LabeledEnum
from coaster.sqlalchemy import BaseMixin, StateManager, StateTransitionError, StateChangeError, StateReadonlyError


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
    state = StateManager('_state', MY_STATE, doc="The post's state")
    rwstate = StateManager('_state', MY_STATE, readonly=False, doc="The post's state (with write access)")
    datetime = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    state.add_conditional_state('RECENT', MY_STATE.PUBLISHED,
        lambda post: post.datetime > datetime.utcnow() - timedelta(hours=1))

    @state.transition(MY_STATE.DRAFT, MY_STATE.PENDING)
    def submit(self):
        pass

    @state.transition(MY_STATE.UNPUBLISHED, MY_STATE.PUBLISHED)
    def publish(self):
        if self.state.DRAFT:
            # Use AssertionError to distinguish from the wrapper's StateTransitionError (a TypeError) in tests below
            raise AssertionError("We don't actually support transitioning from draft to published")
        self.datetime = datetime.utcnow()

    @state.transition(state.conditional.RECENT, MY_STATE.PENDING)
    def undo(self):
        pass

    @state.transition([MY_STATE.DRAFT, MY_STATE.PENDING, state.conditional.RECENT], MY_STATE.DRAFT)
    def redraft(self):
        pass


# --- Tests -------------------------------------------------------------------

class TestStateManager(unittest.TestCase):
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

    def test_state_already_exists(self):
        """
        Adding a conditional state with the name of an existing state will raise an error
        """
        with self.assertRaises(AttributeError):
            MyPost.__dict__['state'].add_conditional_state('PENDING', MY_STATE.DRAFT, lambda post: True)

    def test_transition_invalid_to(self):
        """
        Adding a transition with an invalid `to` state will raise an error
        """
        with self.assertRaises(StateTransitionError):
            MyPost.__dict__['state'].transition(MY_STATE.DRAFT, 'invalid_state')(lambda: None)

    def test_has_state(self):
        """
        A post has a state that can be tested with statemanager.NAME
        """
        self.assertEqual(self.post._state, MY_STATE.DRAFT)
        self.assertEqual(self.post.state(), MY_STATE.DRAFT)
        self.assertEqual(self.post.state.value, MY_STATE.DRAFT)
        self.assertTrue(self.post.state.DRAFT)
        self.assertFalse(self.post.state.PENDING)
        self.assertFalse(self.post.state.PUBLISHED)
        self.assertTrue(self.post.state.UNPUBLISHED)

    def test_change_state(self):
        """
        StateManager is read-only unless write access is requested
        """
        self.assertTrue(self.post.state.DRAFT)
        with self.assertRaises(StateReadonlyError):
            self.post.state = MY_STATE.PENDING
        self.assertTrue(self.post.state.DRAFT)
        self.post.rwstate = MY_STATE.PENDING
        self.assertFalse(self.post.state.DRAFT)
        self.assertTrue(self.post.state.PENDING)

    def test_change_state_invalid(self):
        """
        State cannot be changed to an invalid value
        """
        with self.assertRaises(StateChangeError):
            self.post.rwstate = 100

    def test_is_state(self):
        """
        A state can be tested using the `is_*` name, which is then uppercased to find the value
        """
        self.assertTrue(self.post.state.is_draft)
        self.assertTrue(self.post.state.is_unpublished)
        self.post.rwstate = MY_STATE.PUBLISHED
        self.assertFalse(self.post.state.is_unpublished)
        self.assertTrue(self.post.state.is_published)

    def test_added_state(self):
        """
        Added states include custom validators which are called to confirm the state
        """
        self.assertTrue(self.post.state.DRAFT)
        self.assertFalse(self.post.state.RECENT)
        self.post.rwstate = MY_STATE.PUBLISHED
        self.assertTrue(self.post.state.RECENT)
        self.assertTrue(self.post.state.is_recent)
        self.post.datetime = datetime.utcnow() - timedelta(hours=2)
        self.assertFalse(self.post.state.RECENT)
        self.assertFalse(self.post.state.is_recent)

    def test_sql_query_filter_length(self):
        """
        State inspection on the class returns one or two query filters
        """
        self.assertEqual(len(MyPost.state.DRAFT), 1)
        self.assertEqual(len(MyPost.state.PENDING), 1)
        self.assertEqual(len(MyPost.state.UNPUBLISHED), 1)
        self.assertEqual(len(MyPost.state.RECENT), 2)  # This one has two filter conditions

    def test_sql_query_single_value(self):
        """
        Different queries with the same state value work as expected
        """
        post1 = MyPost.query.filter(*MyPost.state.DRAFT).first()
        self.assertEqual(post1.id, self.post.id)
        post2 = MyPost.query.filter(*MyPost.state.PENDING).first()
        self.assertIsNone(post2)

    def test_sql_query_multi_value(self):
        """
        Same queries with different state values work as expected
        """
        post1 = MyPost.query.filter(*MyPost.state.UNPUBLISHED).first()
        self.assertEqual(post1.id, self.post.id)
        self.post.rwstate = MY_STATE.PUBLISHED
        self.session.commit()
        post2 = MyPost.query.filter(*MyPost.state.UNPUBLISHED).first()
        self.assertIsNone(post2)

    def test_sql_query_added_state(self):
        """
        Querying for an added state works as expected (with two filter conditions)
        """
        post1 = MyPost.query.filter(*MyPost.state.RECENT).first()
        self.assertIsNone(post1)
        self.post.rwstate = MY_STATE.PUBLISHED
        self.session.commit()
        post2 = MyPost.query.filter(*MyPost.state.RECENT).first()
        self.assertEqual(post2.id, self.post.id)

    def test_transition_submit(self):
        """
        `submit` transition works
        """
        self.assertEqual(self.post.state(), MY_STATE.DRAFT)
        self.post.submit()
        self.assertEqual(self.post.state(), MY_STATE.PENDING)
        with self.assertRaises(StateTransitionError):
            # Can only be called in draft state, which we are no longer in
            self.post.submit()
        # If there's an error, the state does not change
        self.assertEqual(self.post.state(), MY_STATE.PENDING)

    def test_transition_publish_invalid(self):
        """
        An exception in the transition aborts it
        """
        self.assertTrue(self.post.state.is_draft)
        with self.assertRaises(AssertionError):
            # publish() should raise AssertionError if we're a draft (custom exception, not decorator's)
            self.post.publish()
        # If there's an error, the state does not change
        self.assertTrue(self.post.state.is_draft)

    def test_transition_publish_datetime(self):
        """
        `publish` transition amends `datetime`
        """
        self.assertTrue(self.post.state.is_draft)
        self.post.submit()
        self.assertTrue(self.post.state.is_pending)
        self.post.datetime = None
        self.post.publish()
        self.assertIsNotNone(self.post.datetime)

    def test_state_labels(self):
        """
        The current state's label can be accessed from the `.label` attribute
        """
        self.assertTrue(self.post.state.is_draft)
        self.assertEqual(self.post.state.label, "Draft")
        self.post.submit()
        self.assertEqual(self.post.state.label.name, 'pending')
        self.assertEqual(self.post.state.label.title, "Pending")

    def test_added_state_transition(self):
        """
        Transition works with added states as a `from` state
        """
        self.assertTrue(self.post.state.DRAFT)
        self.post.submit()  # Change from DRAFT to PENDING
        self.post.publish()  # Change from PENDING to PUBLISHED
        self.assertTrue(self.post.state.PUBLISHED)
        self.assertTrue(self.post.state.RECENT)
        self.post.undo()  # Change from RECENT to PENDING

        self.post.publish()  # Change from PENDING to PUBLISHED
        self.assertTrue(self.post.state.RECENT)
        self.post.datetime = datetime.utcnow() - timedelta(hours=2)
        self.assertFalse(self.post.state.RECENT)
        # `undo` shouldn't work anymore because the post is no longer RECENT
        with self.assertRaises(StateTransitionError):
            self.post.undo()

    def test_added_regular_state_transition(self):
        """
        Transitions work with mixed use of regular and added states in the `from` state
        """
        self.assertTrue(self.post.state.DRAFT)
        self.post.submit()  # Change from DRAFT to PENDING
        self.assertTrue(self.post.state.PENDING)
        self.post.redraft()  # Change from PENDING back to DRAFT
        self.assertTrue(self.post.state.DRAFT)

        self.post.submit()  # Change from DRAFT to PENDING
        self.post.publish()  # Change from PENDING to PUBLISHED
        self.assertTrue(self.post.state.PUBLISHED)
        self.assertTrue(self.post.state.RECENT)
        self.post.redraft()  # Change from RECENT to DRAFT

        self.post.submit()  # Change from DRAFT to PENDING
        self.post.publish()  # Change from PENDING to PUBLISHED
        self.assertTrue(self.post.state.RECENT)
        self.post.datetime = datetime.utcnow() - timedelta(hours=2)
        self.assertFalse(self.post.state.RECENT)
        # `redraft` shouldn't work anymore because the post is no longer RECENT
        with self.assertRaises(StateTransitionError):
            self.post.redraft()
