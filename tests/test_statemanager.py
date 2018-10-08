# -*- coding: utf-8 -*-

from __future__ import absolute_import

import unittest
from datetime import datetime, timedelta
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from coaster.utils import LabeledEnum
from coaster.auth import add_auth_attribute
from coaster.sqlalchemy import (with_roles, BaseMixin,
    StateManager, StateTransitionError, AbortTransition)
from coaster.sqlalchemy.statemanager import ManagedStateWrapper


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


# --- Models ------------------------------------------------------------------

# This enum makes mixed use of 2-tuples and 3-tuples. Never do this in real
# code for your own sanity. We're doing this here only to test that
# StateManager is agnostic to which syntax you use.
class MY_STATE(LabeledEnum):
    DRAFT = (0, "Draft")
    PENDING = (1, 'pending', "Pending")
    PUBLISHED = (2, 'published', "Published")

    __order__ = (DRAFT, PENDING, PUBLISHED)
    UNPUBLISHED = {DRAFT, PENDING}
    PUBLISHED_AND_AFTER = {PUBLISHED}


class REVIEW_STATE(LabeledEnum):
    UNSUBMITTED = (0, "Unsubmitted")
    PENDING = (1, "Pending")
    LOCKED = (2, "Locked")

    UNLOCKED = {UNSUBMITTED, PENDING}


class MyPost(BaseMixin, db.Model):
    __tablename__ = 'my_post'
    # Database state columns
    _state = db.Column('state', db.Integer, StateManager.check_constraint('state', MY_STATE),
        default=MY_STATE.DRAFT, nullable=False)
    _reviewstate = db.Column('reviewstate', db.Integer, StateManager.check_constraint('state', REVIEW_STATE),
        default=REVIEW_STATE.UNSUBMITTED, nullable=False)
    # State managers
    state = StateManager('_state', MY_STATE, doc="The post's state")
    reviewstate = StateManager('_reviewstate', REVIEW_STATE, doc="Reviewer's state")

    # We do not use the LabeledEnum from now on. States must be accessed from the
    # state manager instead.

    # Model's data columns (used for tests)
    datetime = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Conditional states (adds ManagedState instances)
    state.add_conditional_state('RECENT', state.PUBLISHED,
        lambda post: post.datetime > datetime.utcnow() - timedelta(hours=1),
        label=('recent', "Recently published"))

    # State groups (apart from those in the LabeledEnum), used here to include the
    # conditional state in a group. Adds ManagedStateGroup instances
    state.add_state_group('REDRAFTABLE', state.DRAFT, state.PENDING, state.RECENT)

    # State transitions. When multiple state managers are involved, all of them
    # must be in a matching "from" state for the transition to be valid.
    # Specifying `None` for "from" state indicates that any "from" state is valid.
    @with_roles(call={'author'})
    @state.transition(state.DRAFT, state.PENDING)
    @reviewstate.transition(None, reviewstate.UNSUBMITTED, title="Submit")
    def submit(self):
        pass

    @with_roles(call={'author'})
    @state.transition(state.UNPUBLISHED, state.PUBLISHED)
    @reviewstate.transition(reviewstate.UNLOCKED, reviewstate.PENDING, title="Publish")
    def publish(self):
        if self.state.DRAFT:
            # Use AssertionError to distinguish from the wrapper's StateTransitionError (a TypeError) in tests below
            raise AssertionError("We don't actually support transitioning from draft to published")
        self.datetime = datetime.utcnow()

    @with_roles(call={'author'})
    @state.transition(state.RECENT, state.PENDING, title="Undo")
    @reviewstate.transition(reviewstate.UNLOCKED, reviewstate.UNSUBMITTED)
    def undo(self):
        pass

    @with_roles(call={'author'})
    @state.transition(state.REDRAFTABLE, state.DRAFT, title="Redraft")
    @reviewstate.transition(reviewstate.UNLOCKED, reviewstate.UNSUBMITTED)
    def redraft(self):
        pass

    @with_roles(call={'reviewer'})
    @reviewstate.transition(reviewstate.UNLOCKED, reviewstate.LOCKED, if_=state.PUBLISHED, title="Lock")
    def review_lock(self):
        pass

    @with_roles(call={'reviewer'})
    @reviewstate.transition(reviewstate.LOCKED, reviewstate.PENDING, title="Unlock")
    def review_unlock(self):
        pass

    @with_roles(call={'reviewer'})
    @state.requires(state.PUBLISHED, title="Rewind 2 hours")
    def rewind(self):
        self.datetime = datetime.utcnow() - timedelta(hours=2)

    @with_roles(call={'author'})
    @state.transition(state.UNPUBLISHED, state.PUBLISHED, message=u"Abort this transition")
    @reviewstate.transition(reviewstate.UNLOCKED, reviewstate.PENDING, title="Publish")
    def abort(self, success=False, empty_abort=False):
        if not success:
            if empty_abort:
                raise AbortTransition()
            else:
                raise AbortTransition((success, 'failed'))
        return success, 'passed'

    def roles_for(self, actor, anchors=()):
        roles = super(MyPost, self).roles_for(actor, anchors)
        # Cheap hack for the sake of testing, using strings instead of objects
        if actor == 'author':
            roles.add('author')
        if actor == 'reviewer':
            roles.add('reviewer')
        return roles


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
        state = MyPost.__dict__['state']
        with self.assertRaises(AttributeError):
            state.add_conditional_state('PENDING', state.DRAFT, lambda post: True)

    def test_conditional_state_unmanaged_state(self):
        """Conditional states require a managed state as base"""
        state = MyPost.__dict__['state']
        reviewstate = MyPost.__dict__['reviewstate']
        with self.assertRaises(TypeError):
            state.add_conditional_state('TEST_STATE1', MY_STATE.DRAFT, lambda post: True)
        with self.assertRaises(ValueError):
            state.add_conditional_state('TEST_STATE2', reviewstate.UNSUBMITTED, lambda post: True)

    def test_conditional_state_label(self):
        """Conditional states can have labels"""
        self.assertEqual(MyPost.__dict__['state'].RECENT.label.name, 'recent')
        self.assertEqual(self.post.state.RECENT.label.name, 'recent')

    def test_transition_invalid_from_to(self):
        """
        Adding a transition with an invalid `from_` or `to` state will raise an error
        """
        state = MyPost.__dict__['state']
        reviewstate = MyPost.__dict__['reviewstate']
        # Invalid from (needs to be managed)
        with self.assertRaises(StateTransitionError):
            state.transition(MY_STATE.DRAFT, state.PENDING)(lambda: None)
        # Invalid from (not managed by this state manager)
        with self.assertRaises(StateTransitionError):
            state.transition(reviewstate.UNSUBMITTED, state.PENDING)(lambda: None)
        # Invalid to (needs to be managed)
        with self.assertRaises(StateTransitionError):
            state.transition(state.DRAFT, 'invalid_state')(lambda: None)
        # Invalid to (not managed by this state manager)
        with self.assertRaises(StateTransitionError):
            state.transition(state.DRAFT, reviewstate.UNSUBMITTED)(lambda: None)
        # Invalid to (can't be a grouped value)
        with self.assertRaises(StateTransitionError):
            state.transition(state.DRAFT, state.UNPUBLISHED)(lambda: None)
        # Invalid to (can't be a conditional state)
        with self.assertRaises(StateTransitionError):
            state.transition(state.DRAFT, state.RECENT)(lambda: None)
        # Invalid to (can't be a state group)
        with self.assertRaises(StateTransitionError):
            state.transition(state.DRAFT, state.REDRAFTABLE)(lambda: None)

    def test_has_state(self):
        """
        A post has a state that can be tested with statemanager.NAME
        """
        self.assertEqual(self.post._state, MY_STATE.DRAFT)
        self.assertEqual(self.post.state.value, MY_STATE.DRAFT)
        self.assertTrue(self.post.state.DRAFT)
        self.assertFalse(self.post.state.PENDING)
        self.assertFalse(self.post.state.PUBLISHED)
        self.assertTrue(self.post.state.UNPUBLISHED)

    def test_has_nonstate(self):
        """
        StateManagerWrapper will refuse access to non-state attributes
        """
        with self.assertRaises(AttributeError):
            self.post.state.does_not_exist
        with self.assertRaises(AttributeError):
            self.post.state.transition

    def test_readonly(self):
        """
        StateManager is read-only
        """
        self.assertTrue(self.post.state.DRAFT)
        with self.assertRaises(AttributeError):
            self.post.state = MY_STATE.PENDING
        self.assertTrue(self.post.state.DRAFT)
        self.post._state = MY_STATE.PENDING
        self.assertFalse(self.post.state.DRAFT)
        self.assertTrue(self.post.state.PENDING)

    def test_change_state_invalid(self):
        """
        State cannot be changed to an invalid value
        """
        state = MyPost.__dict__['state']
        with self.assertRaises(ValueError):
            # We'd never call this outside a test; it's only to test the validator within
            state._set(self.post, 100)

    def test_is_state(self):
        """
        A state can be tested using the `is_*` name, which is then uppercased to find the value
        """
        self.assertTrue(self.post.state.is_draft)
        self.assertTrue(self.post.state.is_unpublished)
        self.post._state = MY_STATE.PUBLISHED
        self.assertFalse(self.post.state.is_unpublished)
        self.assertTrue(self.post.state.is_published)

    def test_conditional_state(self):
        """
        Conditional states include custom validators which are called to confirm the state
        """
        self.assertTrue(self.post.state.DRAFT)
        self.assertFalse(self.post.state.RECENT)
        self.post._state = MY_STATE.PUBLISHED
        self.assertTrue(self.post.state.RECENT)
        self.assertTrue(self.post.state.is_recent)
        self.post.rewind()
        self.assertFalse(self.post.state.RECENT)
        self.assertFalse(self.post.state.is_recent)

    def test_bestmatch_state(self):
        """
        The best matching state prioritises conditional over direct
        """
        self.assertTrue(self.post.state.DRAFT)
        self.assertEqual(self.post.state.bestmatch(), self.post.state.DRAFT)
        self.assertFalse(self.post.state.RECENT)

        self.post._state = MY_STATE.PUBLISHED

        self.assertTrue(self.post.state.RECENT)
        self.assertTrue(self.post.state.is_recent)
        self.assertTrue(self.post.state.PUBLISHED)
        self.assertEqual(self.post.state.bestmatch(), self.post.state.RECENT)
        self.assertEqual(self.post.state.label.name, 'recent')

        self.post.rewind()

        self.assertFalse(self.post.state.RECENT)
        self.assertFalse(self.post.state.is_recent)
        self.assertTrue(self.post.state.PUBLISHED)
        self.assertEqual(self.post.state.bestmatch(), self.post.state.PUBLISHED)
        self.assertEqual(self.post.state.label.name, 'published')

    def test_added_state_group(self):
        """Added state groups can be tested"""
        self.assertTrue(self.post.state.DRAFT)
        # True because DRAFT state matches
        self.assertTrue(self.post.state.REDRAFTABLE)
        self.post.submit()
        self.post.publish()
        # True because RECENT conditional state matches
        self.assertTrue(self.post.state.REDRAFTABLE)
        self.post.rewind()
        self.assertFalse(self.post.state.REDRAFTABLE)

    def test_state_group_invalid(self):
        """add_state_group validates the states being added"""
        state = MyPost.__dict__['state']
        reviewstate = MyPost.__dict__['reviewstate']
        # Can't add an existing state name
        with self.assertRaises(AttributeError):
            state.add_state_group('DRAFT', state.PENDING)
        # Can't add a state from another state manager
        with self.assertRaises(ValueError):
            state.add_state_group('OTHER', reviewstate.UNSUBMITTED)
        # Can't group a conditional state with the main state
        with self.assertRaises(ValueError):
            state.add_state_group('MIXED1', state.PUBLISHED, state.RECENT)
        # Can't group a conditional state with group containing main state
        with self.assertRaises(ValueError):
            state.add_state_group('MIXED2', state.PUBLISHED_AND_AFTER, state.RECENT)

    def test_sql_query_single_value(self):
        """
        Different queries with the same state value work as expected
        """
        post1 = MyPost.query.filter(MyPost.state.DRAFT).first()
        self.assertEqual(post1.id, self.post.id)
        post2 = MyPost.query.filter(MyPost.state.PENDING).first()
        self.assertIsNone(post2)
        post3 = MyPost.query.filter(~MyPost.state.DRAFT).first()
        self.assertIsNone(post3)
        post4 = MyPost.query.filter(~MyPost.state.PENDING).first()
        self.assertEqual(post4.id, self.post.id)

    def test_sql_query_multi_value(self):
        """
        Same queries with different state values work as expected
        """
        post1 = MyPost.query.filter(MyPost.state.UNPUBLISHED).first()
        self.assertEqual(post1.id, self.post.id)
        self.post._state = MY_STATE.PUBLISHED
        self.session.commit()
        post2 = MyPost.query.filter(MyPost.state.UNPUBLISHED).first()
        self.assertIsNone(post2)

    def test_sql_query_added_state(self):
        """
        Querying for an added state works as expected (with two filter conditions combined with and_)
        """
        post1 = MyPost.query.filter(MyPost.state.RECENT).first()
        self.assertIsNone(post1)
        self.post._state = MY_STATE.PUBLISHED
        self.session.commit()
        post2 = MyPost.query.filter(MyPost.state.RECENT).first()
        self.assertEqual(post2.id, self.post.id)

    def test_sql_query_state_group(self):
        """
        Querying for a state group works as expected (with multiple filter conditions combined with or_)
        """
        post1 = MyPost.query.filter(MyPost.state.REDRAFTABLE).first()
        self.assertEqual(post1.id, self.post.id)
        self.post._state = MY_STATE.PUBLISHED
        self.session.commit()
        post2 = MyPost.query.filter(MyPost.state.REDRAFTABLE).first()
        self.assertEqual(post2.id, self.post.id)
        self.post.rewind()
        self.session.commit()
        post3 = MyPost.query.filter(MyPost.state.REDRAFTABLE).first()
        self.assertIsNone(post3)

    def test_transition_submit(self):
        """
        `submit` transition works
        """
        self.assertEqual(self.post.state.value, MY_STATE.DRAFT)
        self.post.submit()
        self.assertEqual(self.post.state.value, MY_STATE.PENDING)
        with self.assertRaises(StateTransitionError):
            # Can only be called in draft state, which we are no longer in
            self.post.submit()
        # If there's an error, the state does not change
        self.assertEqual(self.post.state.value, MY_STATE.PENDING)

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

    def test_requires(self):
        """
        The `requires` decorator behaves similarly to a transition, but doesn't state change
        """
        self.assertTrue(self.post.state.is_draft)
        with self.assertRaises(StateTransitionError):
            # Can only be called in published state
            self.post.rewind()
        self.post.submit()
        self.post.publish()
        self.assertTrue(self.post.state.is_published)
        d = self.post.datetime
        # Now we can call it
        self.post.rewind()
        self.assertTrue(self.post.state.is_published)
        self.assertLess(self.post.datetime, d)

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
        self.post.rewind()
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
        self.post.rewind()
        self.assertFalse(self.post.state.RECENT)
        # `redraft` shouldn't work anymore because the post is no longer RECENT
        with self.assertRaises(StateTransitionError):
            self.post.redraft()

    def test_reviewstate_also_changes(self):
        """Transitions with two decorators change state on both managers"""
        self.assertTrue(self.post.state.DRAFT)
        self.assertTrue(self.post.reviewstate.UNSUBMITTED)
        self.post.submit()  # This changes only `state`
        self.assertFalse(self.post.state.DRAFT)
        self.assertTrue(self.post.state.PENDING)
        self.assertTrue(self.post.reviewstate.UNSUBMITTED)
        self.post.publish()  # Now this changes both states
        self.assertFalse(self.post.state.PENDING)
        self.assertFalse(self.post.reviewstate.UNSUBMITTED)
        self.assertTrue(self.post.state.PUBLISHED)
        self.assertTrue(self.post.reviewstate.PENDING)

    def test_transition_state_lock(self):
        """Both states must be in valid state for a transition to be available"""
        self.post.submit()
        self.assertTrue(self.post.state.PENDING)
        self.assertTrue(self.post.reviewstate.UNSUBMITTED)
        self.post.publish()  # Publish works
        self.assertTrue(self.post.state.PUBLISHED)
        self.post.undo()  # Go back to PENDING
        self.assertTrue(self.post.state.PENDING)
        self.assertTrue(self.post.reviewstate.UNSUBMITTED)
        self.post.publish()  # Publish again
        self.post.review_lock()  # Now lock it, preventing undo
        self.assertTrue(self.post.state.PUBLISHED)
        self.assertFalse(self.post.reviewstate.UNSUBMITTED)
        self.assertTrue(self.post.reviewstate.LOCKED)
        with self.assertRaises(StateTransitionError):
            self.post.undo()  # Undo isn't available now

    def test_transition_from_none(self):
        """Transition from None ignores initial state"""
        self.assertTrue(self.post.state.DRAFT)
        self.post._reviewstate = REVIEW_STATE.LOCKED
        self.assertTrue(self.post.state.DRAFT)
        self.assertTrue(self.post.reviewstate.LOCKED)
        self.post.submit()  # submit overrides LOCKED status
        self.assertFalse(self.post.reviewstate.LOCKED)
        self.assertTrue(self.post.state.PENDING)

    def test_transition_abort(self):
        """Transitions can abort without changing state or raising an exception"""
        self.assertTrue(self.post.state.DRAFT)

        # A transition can abort returning a value (a 2-tuple here)
        success, message = self.post.abort(success=False)
        self.assertEqual(success, False)
        self.assertEqual(message, "failed")
        self.assertTrue(self.post.state.DRAFT)  # state has not changed

        # A transition can abort without returning a value
        result = self.post.abort(success=False, empty_abort=True)
        self.assertEqual(result, None)
        self.assertTrue(self.post.state.DRAFT)  # state has not changed

        success, message = self.post.abort(success=True)
        self.assertEqual(success, True)
        self.assertEqual(message, 'passed')
        self.assertTrue(self.post.state.PUBLISHED)  # state has changed

    def test_transition_is_available(self):
        """A transition's is_available property is reliable"""
        self.assertTrue(self.post.state.DRAFT)
        self.assertTrue(self.post.submit.is_available)
        self.post.submit()
        self.assertFalse(self.post.submit.is_available)
        with self.assertRaises(StateTransitionError):
            self.post.submit()
        self.assertTrue(self.post.publish.is_available)
        self.post.publish()
        self.assertTrue(self.post.undo.is_available)
        self.assertTrue(self.post.review_lock.is_available)
        self.post.review_lock()
        self.assertFalse(self.post.undo.is_available)

    def test_transition_data(self):
        """Additional data defined on a transition works regardless of decorator order"""
        # Titles are defined on different decorators on these:
        self.assertEqual(self.post.publish.data['title'], "Publish")
        self.assertEqual(self.post.undo.data['title'], "Undo")
        # Also available via the class
        self.assertEqual(MyPost.publish.data['title'], "Publish")
        self.assertEqual(MyPost.undo.data['title'], "Undo")

    def test_transition_data_name_invalid(self):
        """The `name` data field on transitions is reserved and cannot be specified"""
        state = MyPost.__dict__['state']
        with self.assertRaises(TypeError):
            @state.transition(None, state.DRAFT, name='invalid_data_field')
            def name_test(self):
                pass

    def test_duplicate_transition(self):
        """Transitions can't be decorated twice with the same state manager"""
        state = MyPost.__dict__['state']
        with self.assertRaises(TypeError):
            @state.transition(state.DRAFT, state.PENDING)
            @state.transition(state.PENDING, state.PUBLISHED)
            def dupe_decorator(self):
                pass

    def test_available_transitions(self):
        """State managers indicate the currently available transitions"""
        self.assertTrue(self.post.state.DRAFT)
        self.assertIn('submit', self.post.state.transitions(current=False))
        self.post.state.transitions(current=False)['submit']()
        self.assertFalse(self.post.state.DRAFT)
        self.assertTrue(self.post.state.PENDING)

    def test_available_transitions_order(self):
        """State managers maintain the order of transitions from the class definition"""
        self.assertTrue(self.post.state.DRAFT)
        # `submit` must come before `publish`
        self.assertEqual(list(self.post.state.transitions(current=False).keys()[:2]), ['submit', 'publish'])

    def test_currently_available_transitions(self):
        """State managers indicate the currently available transitions (using current_auth)"""
        self.assertTrue(self.post.state.DRAFT)
        self.assertNotIn('submit', self.post.state.transitions())
        add_auth_attribute('user', 'author')  # Add a user using the string 'author' (see MyPost.roles_for)
        self.assertIn('submit', self.post.state.transitions())
        self.post.state.transitions()['submit']()
        self.assertFalse(self.post.state.DRAFT)
        self.assertTrue(self.post.state.PENDING)

    def test_available_transitions_for(self):
        """State managers indicate the currently available transitions (using access_for)"""
        self.assertTrue(self.post.state.DRAFT)
        self.assertNotIn('submit', self.post.state.transitions_for(roles={'reviewer'}))
        self.assertIn('submit', self.post.state.transitions_for(roles={'author'}))
        self.post.state.transitions_for(roles={'author'})['submit']()
        self.assertFalse(self.post.state.DRAFT)
        self.assertTrue(self.post.state.PENDING)

    def test_current_states(self):
        """All states that are currently active"""
        current = self.post.state.current()
        self.assertEqual(set(current.keys()), set(['DRAFT', 'UNPUBLISHED', 'REDRAFTABLE']))
        self.assertTrue(current['DRAFT']())
        self.assertEqual(current['DRAFT'].value, MY_STATE.DRAFT)

        # Classes don't have a current state
        self.assertEqual(MyPost.state.current(), None)

    def test_managed_state_wrapper(self):
        """ManagedStateWrapper will only wrap a managed state or group"""
        draft = MyPost.__dict__['state'].DRAFT
        wdraft = ManagedStateWrapper(draft, self.post, MyPost)
        self.assertEqual(draft.value, wdraft.value)
        self.assertTrue(wdraft())  # Result is False
        self.assertTrue(wdraft)    # Object is falsy
        self.assertEqual(self.post.state.DRAFT, wdraft)
        self.post.submit()
        self.assertFalse(wdraft())
        self.assertFalse(wdraft)
        self.assertEqual(self.post.state.DRAFT(), wdraft())       # False == False
        self.assertEqual(self.post.state.DRAFT, wdraft)           # Object remains the same even if not active
        self.assertNotEqual(self.post.state.PENDING, wdraft)      # These objects don't match
        self.assertNotEqual(self.post.state.PENDING(), wdraft())  # True != False

        with self.assertRaises(TypeError):
            ManagedStateWrapper(MY_STATE.DRAFT, self.post)

    def test_role_proxy_transitions(self):
        """with_roles works on the transition decorator"""
        self.assertTrue(self.post.state.DRAFT)
        # Create access proxies for each of these roles
        author = self.post.access_for({'author'})
        reviewer = self.post.access_for({'reviewer'})

        # Transitions are listed in the proxy even if not callable
        self.assertIn('submit', author)
        self.assertIn('publish', author)
        self.assertIn('undo', author)
        self.assertIn('redraft', author)
        self.assertNotIn('review_lock', author)
        self.assertNotIn('review_unlock', author)

        self.assertNotIn('submit', reviewer)
        self.assertNotIn('publish', reviewer)
        self.assertNotIn('undo', reviewer)
        self.assertNotIn('redraft', reviewer)
        self.assertIn('review_lock', reviewer)
        self.assertIn('review_unlock', reviewer)

        # The `is_available` test can be accessed through the proxy
        self.assertTrue(author.submit.is_available)
        self.assertFalse(author.undo.is_available)
        # Transitions can be accessed through the proxy
        author.submit()
        author.publish()
        self.assertFalse(author.submit.is_available)
        self.assertTrue(author.undo.is_available)

    def test_group_by_state(self):
        """StateManager.group returns a dictionary grouping items by their state."""
        self.assertTrue(self.post.state.DRAFT)
        post2 = MyPost(_state=MY_STATE.PUBLISHED)
        post3 = MyPost(_state=MY_STATE.PUBLISHED)
        self.session.add_all([post2, post3])
        self.session.commit()
        groups1 = MyPost.state.group(MyPost.query.all())
        # Order is preserved. Draft before Published. No Pending.
        self.assertEqual([g.label for g in groups1.keys()],
            [MY_STATE[MY_STATE.DRAFT], MY_STATE[MY_STATE.PUBLISHED]])
        # Order is preserved. Draft before Pending before Published.
        groups2 = MyPost.state.group(MyPost.query.all(), keep_empty=True)
        self.assertEqual([g.label for g in groups2.keys()],
            [MY_STATE[MY_STATE.DRAFT], MY_STATE[MY_STATE.PENDING], MY_STATE[MY_STATE.PUBLISHED]])
        self.assertEqual(list(groups1.values()),
            [[self.post], [post2, post3]])
        self.assertEqual(list(groups2.values()),
            [[self.post], [], [post2, post3]])

        with self.assertRaises(TypeError):
            MyPost.state.group([self.post, "Invalid type"])
