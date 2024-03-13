"""Tests for StateManager."""

# pylint: disable=protected-access,comparison-with-callable

import enum
import types
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

import pytest
import sqlalchemy as sa

from coaster.auth import add_auth_attribute
from coaster.sqlalchemy import (
    AbortTransition,
    BaseMixin,
    LazyRoleSet,
    ManagedStateInstance,
    StateManager,
    StateManagerInstance,
    StateTransitionError,
    with_roles,
)
from coaster.utils import DataclassFromType, LabeledEnum, NameTitle

from .conftest import AppTestCase, Model

# --- Models ---------------------------------------------------------------------------


# This enum makes mixed use of 2-tuples and 3-tuples. Never do this in real
# code for your own sanity. We're doing this here only to test that
# StateManager is agnostic to which syntax you use.
class MY_STATE(LabeledEnum):  # noqa: N801
    """Test states."""

    DRAFT = (0, "Draft")
    PENDING = (1, 'pending', "Pending")
    PUBLISHED = (2, 'published', "Published")

    UNPUBLISHED = {DRAFT, PENDING}
    PUBLISHED_AND_AFTER = {PUBLISHED}


class REVIEW_STATE(LabeledEnum):  # noqa: N801
    """More test states."""

    UNSUBMITTED = (0, "Unsubmitted")
    PENDING = (1, "Pending")
    LOCKED = (2, "Locked")

    UNLOCKED = {UNSUBMITTED, PENDING}


class MyPost(BaseMixin, Model):
    """Class for testing StateManager."""

    __tablename__ = 'my_post'
    # Database state columns
    _state = sa.orm.mapped_column(
        'state',
        sa.Integer,
        StateManager.check_constraint('state', MY_STATE),
        default=MY_STATE.DRAFT,
        nullable=False,
    )
    _reviewstate = sa.orm.mapped_column(
        'reviewstate',
        sa.Integer,
        StateManager.check_constraint('state', REVIEW_STATE),
        default=REVIEW_STATE.UNSUBMITTED,
        nullable=False,
    )
    # State managers
    state = StateManager('_state', MY_STATE, doc="The post's state")
    reviewstate = StateManager('_reviewstate', REVIEW_STATE, doc="Reviewer's state")

    # We do not use the LabeledEnum from now on. States must be accessed from the
    # state manager instead.

    # Model's data columns (used for tests)
    published_at = sa.orm.mapped_column(
        sa.DateTime, default=datetime.utcnow, nullable=False
    )

    # Conditional states (adds ManagedState instances)
    state.add_conditional_state(
        'RECENT',
        state.PUBLISHED,
        lambda post: post.published_at > datetime.utcnow() - timedelta(hours=1),
        label=NameTitle('recent', "Recently published"),
    )

    # State groups (apart from those in the LabeledEnum), used here to include the
    # conditional state in a group. Adds ManagedStateGroup instances
    state.add_state_group('REDRAFTABLE', state.DRAFT, state.PENDING, state.RECENT)

    # State transitions. When multiple state managers are involved, all of them
    # must be in a matching "from" state for the transition to be valid.
    # Specifying `None` for "from" state indicates that any "from" state is valid.
    @with_roles(call={'author'})
    @state.transition(state.DRAFT, state.PENDING)
    @reviewstate.transition(None, reviewstate.UNSUBMITTED, title="Submit")
    def submit(self) -> None:
        """Transition from DRAFT to PENDING state."""

    @with_roles(call={'author'})
    @state.transition(state.UNPUBLISHED, state.PUBLISHED)
    @reviewstate.transition(reviewstate.UNLOCKED, reviewstate.PENDING, title="Publish")
    def publish(self) -> None:
        """Transition to PUBLISHED state."""
        if self.state.DRAFT:
            # Use AssertionError to distinguish from the wrapper's StateTransitionError
            # (a TypeError) in tests below
            raise AssertionError(
                "We don't actually support transitioning from draft to published"
            )
        self.published_at = datetime.utcnow()

    @with_roles(call={'author'})
    @state.transition(state.RECENT, state.PENDING, title="Undo")
    @reviewstate.transition(reviewstate.UNLOCKED, reviewstate.UNSUBMITTED)
    def undo(self) -> None:
        """Undo publishing only if recently published."""

    @with_roles(call={'author'})
    @state.transition(state.REDRAFTABLE, state.DRAFT, title="Redraft")
    @reviewstate.transition(reviewstate.UNLOCKED, reviewstate.UNSUBMITTED)
    def redraft(self) -> None:
        """Restore to draft state."""

    @with_roles(call={'reviewer'})
    @reviewstate.transition(
        reviewstate.UNLOCKED,
        reviewstate.LOCKED,
        title="Lock",
    )
    @state.requires(state.PUBLISHED)
    def review_lock(self) -> None:
        """Add a validator for state transition."""

    @with_roles(call={'reviewer'})
    @reviewstate.transition(reviewstate.LOCKED, reviewstate.PENDING, title="Unlock")
    def review_unlock(self) -> None:
        """Transition to unlocked state."""

    @with_roles(call={'reviewer'})
    @state.requires(state.PUBLISHED, title="Rewind 2 hours")
    def rewind(self) -> None:
        """Allow this method only in a given state."""
        self.published_at = datetime.utcnow() - timedelta(hours=2)

    @with_roles(call={'author'})
    @state.transition(
        state.UNPUBLISHED, state.PUBLISHED, message="Abort this transition"
    )
    @reviewstate.transition(reviewstate.UNLOCKED, reviewstate.PENDING, title="Publish")
    def abort(
        self, success: bool = False, empty_abort: bool = False
    ) -> Optional[tuple[bool, str]]:
        """Demonstrate use of AbortTransition."""
        if not success:
            if empty_abort:
                raise AbortTransition()
            raise AbortTransition((success, 'failed'))
        return success, 'passed'

    def roles_for(
        self, actor: Optional[Any] = None, anchors: Sequence[Any] = ()
    ) -> LazyRoleSet:
        """Return roles for the actor."""
        roles = super().roles_for(actor, anchors)
        # Cheap hack for the sake of testing, using strings instead of objects
        if actor == 'author':
            roles.add('author')
        if actor == 'reviewer':
            roles.add('reviewer')
        return roles


# --- Tests ----------------------------------------------------------------------------


@pytest.mark.filterwarnings("ignore::coaster.utils.classes.LabeledEnumWarning")
def test_check_constraint_labeledenum():
    """Test check_constraint with a LabeledEnum."""

    class TestEnum1(LabeledEnum):
        ONE = (1, "One")
        TWO = (2, "Two")
        THREE = (3, "Three")

    class TestEnum2(LabeledEnum):
        ONE = (1, "one", "One")
        TWO = (2, "two", "Two")
        THREE = (3, "three", "Three")

    class TestEnumStr(LabeledEnum):
        YES = ('y', "Yes")
        NO = ('n', "No")
        MAYBE = ('m', "Maybe")

    assert (
        str(
            StateManager.check_constraint('state', TestEnum1).sqltext.compile(
                compile_kwargs={'literal_binds': True}
            )
        )
        == 'state IN (1, 2, 3)'
    )
    assert (
        str(
            StateManager.check_constraint('state', TestEnum2).sqltext.compile(
                compile_kwargs={'literal_binds': True}
            )
        )
        == 'state IN (1, 2, 3)'
    )
    assert (
        str(
            StateManager.check_constraint('state', TestEnumStr).sqltext.compile(
                compile_kwargs={'literal_binds': True}
            )
        )
        == "state IN ('y', 'n', 'm')"
    )


def test_check_constraint_enum():
    """Test check_constraint with an Enum."""

    class TestEnumInt(enum.Enum):
        ONE = 1
        TWO = 2
        THREE = 3

    @dataclass(frozen=True)
    class IntLabel(DataclassFromType, int):
        label: str

    class TestEnumIntLabel(IntLabel, enum.Enum):
        ONE = 1, "one"
        TWO = 2, "two"
        THREE = 3, "three"

    class TestEnumStr(enum.Enum):
        YES = 'y'
        NO = 'n'
        MAYBE = 'm'

    @dataclass(frozen=True)
    class StrLabel(DataclassFromType, str):
        label: str

    class TestEnumStrLabel(StrLabel, enum.Enum):
        YES = 'y', "Yes"
        NO = 'n', "No"
        MAYBE = 'm', "Maybe"

    assert (
        str(
            StateManager.check_constraint('state', TestEnumInt).sqltext.compile(
                compile_kwargs={'literal_binds': True}
            )
        )
        == 'state IN (1, 2, 3)'
    )
    assert (
        str(
            StateManager.check_constraint(
                'state', TestEnumIntLabel, sa.Integer
            ).sqltext.compile(compile_kwargs={'literal_binds': True})
        )
        == 'state IN (1, 2, 3)'
    )
    assert (
        str(
            StateManager.check_constraint('state', TestEnumStr).sqltext.compile(
                compile_kwargs={'literal_binds': True}
            )
        )
        == "state IN ('y', 'n', 'm')"
    )
    assert (
        str(
            StateManager.check_constraint(
                'state', TestEnumStrLabel, sa.String
            ).sqltext.compile(compile_kwargs={'literal_binds': True})
        )
        == "state IN ('y', 'n', 'm')"
    )


class TestStateManager(AppTestCase):
    """Tests for StateManager."""

    post: MyPost

    def setUp(self) -> None:
        """Prepare testcase."""
        super().setUp()
        self.post = MyPost()
        self.session.add(self.post)
        self.session.commit()

    def test_state_already_exists(self) -> None:
        """Conditional state with the name of an existing state will raise an error."""
        state = MyPost.__dict__['state']
        with pytest.raises(AttributeError):
            state.add_conditional_state('PENDING', state.DRAFT, lambda post: True)

    def test_conditional_state_unmanaged_state(self) -> None:
        """Conditional states require a managed state as base."""
        state = MyPost.__dict__['state']
        reviewstate = MyPost.__dict__['reviewstate']
        with pytest.raises(TypeError):
            state.add_conditional_state(
                'TEST_STATE1', MY_STATE.DRAFT, lambda post: True
            )
        with pytest.raises(ValueError, match="not associated with this state manager"):
            state.add_conditional_state(
                'TEST_STATE2', reviewstate.UNSUBMITTED, lambda post: True
            )

    def test_conditional_state_label(self) -> None:
        """Conditional states can have labels."""
        assert MyPost.__dict__['state'].RECENT.label.name == 'recent'
        assert self.post.state.RECENT.label.name == 'recent'

    def test_transition_invalid_from_to(self) -> None:
        """Transition requires valid from_ and to states."""
        state = MyPost.__dict__['state']
        reviewstate = MyPost.__dict__['reviewstate']
        # Invalid from (needs to be managed)
        with pytest.raises(StateTransitionError):
            state.transition(MY_STATE.DRAFT, state.PENDING)(lambda: None)
        # Invalid from (not managed by this state manager)
        with pytest.raises(StateTransitionError):
            state.transition(reviewstate.UNSUBMITTED, state.PENDING)(lambda: None)
        # Invalid to (needs to be managed)
        with pytest.raises(StateTransitionError):
            state.transition(state.DRAFT, 'invalid_state')(lambda: None)
        # Invalid to (not managed by this state manager)
        with pytest.raises(StateTransitionError):
            state.transition(state.DRAFT, reviewstate.UNSUBMITTED)(lambda: None)
        # Invalid to (can't be a grouped value)
        with pytest.raises(StateTransitionError):
            state.transition(state.DRAFT, state.UNPUBLISHED)(lambda: None)
        # Invalid to (can't be a conditional state)
        with pytest.raises(StateTransitionError):
            state.transition(state.DRAFT, state.RECENT)(lambda: None)
        # Invalid to (can't be a state group)
        with pytest.raises(StateTransitionError):
            state.transition(state.DRAFT, state.REDRAFTABLE)(lambda: None)

    def test_has_state(self) -> None:
        """A post has a state that can be tested with state_manager.NAME."""
        assert self.post._state == MY_STATE.DRAFT
        assert self.post.state.value == MY_STATE.DRAFT
        assert self.post.state.DRAFT
        assert not self.post.state.PENDING
        assert not self.post.state.PUBLISHED
        assert self.post.state.UNPUBLISHED

    def test_has_nonstate(self) -> None:
        """Test that StateManagerWrapper is only a proxy to StateManager's attrs."""
        with pytest.raises(AttributeError):
            self.post.state.does_not_exist  # pylint: disable=pointless-statement
        assert isinstance(self.post.state.transition, types.MethodType)

    def test_readonly(self) -> None:
        """The StateManager is read-only."""
        assert self.post.state.DRAFT
        with pytest.raises(AttributeError):
            self.post.state = MY_STATE.PENDING
        assert isinstance(self.post.state, StateManagerInstance)
        assert self.post.state.DRAFT
        self.post._state = MY_STATE.PENDING
        assert not self.post.state.DRAFT
        assert self.post.state.PENDING

    def test_change_state_invalid(self) -> None:
        """State cannot be changed to an invalid value."""
        state = MyPost.__dict__['state']
        with pytest.raises(ValueError, match="Not a valid value"):
            # We'd never call this outside a test; it's only to test the validator
            # within
            state._set_state_value(self.post, 100)

    def test_conditional_state(self) -> None:
        """
        Conditional states include custom validators which are called to confirm the state
        """
        assert self.post.state.DRAFT
        assert not self.post.state.RECENT
        self.post._state = MY_STATE.PUBLISHED
        assert self.post.state.RECENT
        self.post.rewind()
        assert not self.post.state.RECENT

    def test_bestmatch_state(self) -> None:
        """
        The best matching state prioritises conditional over direct
        """
        assert self.post.state.DRAFT
        assert self.post.state.bestmatch() == self.post.state.DRAFT
        assert not self.post.state.RECENT

        self.post._state = MY_STATE.PUBLISHED

        assert self.post.state.RECENT
        assert self.post.state.PUBLISHED
        assert self.post.state.bestmatch() == self.post.state.RECENT
        assert self.post.state.label.name == 'recent'

        self.post.rewind()

        assert not self.post.state.RECENT
        assert self.post.state.PUBLISHED
        assert self.post.state.bestmatch() == self.post.state.PUBLISHED
        assert self.post.state.label.name == 'published'

    def test_added_state_group(self) -> None:
        """Added state groups can be tested"""
        assert self.post.state.DRAFT
        # True because DRAFT state matches
        assert self.post.state.REDRAFTABLE
        self.post.submit()
        self.post.publish()
        # True because RECENT conditional state matches
        assert self.post.state.REDRAFTABLE
        self.post.rewind()
        assert not self.post.state.REDRAFTABLE

    def test_state_group_invalid(self) -> None:
        """add_state_group validates the states being added"""
        state = MyPost.__dict__['state']
        reviewstate = MyPost.__dict__['reviewstate']
        # Can't add an existing state name
        with pytest.raises(AttributeError):
            state.add_state_group('DRAFT', state.PENDING)
        # Can't add a state from another state manager
        with pytest.raises(ValueError):
            state.add_state_group('OTHER', reviewstate.UNSUBMITTED)
        # Can't group a conditional state with the main state
        with pytest.raises(ValueError):
            state.add_state_group('MIXED1', state.PUBLISHED, state.RECENT)
        # Can't group a conditional state with group containing main state
        with pytest.raises(ValueError):
            state.add_state_group('MIXED2', state.PUBLISHED_AND_AFTER, state.RECENT)

    def test_sql_query_single_value(self) -> None:
        """
        Different queries with the same state value work as expected
        """
        post1 = MyPost.query.filter(MyPost.state.DRAFT).first()
        assert post1 is not None
        assert post1.id == self.post.id
        post2 = MyPost.query.filter(MyPost.state.PENDING).first()
        assert post2 is None
        post3 = MyPost.query.filter(~(MyPost.state.DRAFT)).first()
        assert post3 is None
        post4 = MyPost.query.filter(~(MyPost.state.PENDING)).first()
        assert post4 is not None
        assert post4.id == self.post.id

    def test_sql_query_multi_value(self) -> None:
        """
        Same queries with different state values work as expected
        """
        post1 = MyPost.query.filter(MyPost.state.UNPUBLISHED).first()
        assert post1 is not None
        assert post1.id == self.post.id
        self.post._state = MY_STATE.PUBLISHED
        self.session.commit()
        post2 = MyPost.query.filter(MyPost.state.UNPUBLISHED).first()
        assert post2 is None

    def test_sql_query_added_state(self) -> None:
        """
        Querying for an added state works as expected (with two filter conditions combined with and_)
        """
        post1 = MyPost.query.filter(MyPost.state.RECENT).first()
        assert post1 is None
        self.post._state = MY_STATE.PUBLISHED
        self.session.commit()
        post2 = MyPost.query.filter(MyPost.state.RECENT).first()
        assert post2 is not None
        assert post2.id == self.post.id

    def test_sql_query_state_group(self) -> None:
        """
        Querying for a state group works as expected (with multiple filter conditions combined with or_)
        """
        post1 = MyPost.query.filter(MyPost.state.REDRAFTABLE).first()
        assert post1 is not None
        assert post1.id == self.post.id
        self.post._state = MY_STATE.PUBLISHED
        self.session.commit()
        post2 = MyPost.query.filter(MyPost.state.REDRAFTABLE).first()
        assert post2 is not None
        assert post2.id == self.post.id
        self.post.rewind()
        self.session.commit()
        post3 = MyPost.query.filter(MyPost.state.REDRAFTABLE).first()
        assert post3 is None

    def test_transition_submit(self) -> None:
        """
        `submit` transition works
        """
        assert self.post.state.value == MY_STATE.DRAFT
        self.post.submit()
        assert self.post.state.value == MY_STATE.PENDING
        with pytest.raises(StateTransitionError):
            # Can only be called in draft state, which we are no longer in
            self.post.submit()
        # If there's an error, the state does not change
        assert self.post.state.value == MY_STATE.PENDING

    def test_transition_publish_invalid(self) -> None:
        """
        An exception in the transition aborts it
        """
        assert self.post.state.DRAFT
        with pytest.raises(AssertionError):
            # publish() should raise AssertionError if we're a draft (custom exception, not decorator's)
            self.post.publish()
        # If there's an error, the state does not change
        assert self.post.state.DRAFT

    def test_transition_publish_datetime(self) -> None:
        """
        `publish` transition amends `datetime`
        """
        assert self.post.state.DRAFT
        self.post.submit()
        assert self.post.state.PENDING
        self.post.published_at = None
        self.post.publish()
        assert self.post.published_at is not None

    def test_requires(self) -> None:
        """
        The `requires` decorator behaves similarly to a transition, but doesn't state change
        """
        assert self.post.state.DRAFT
        with pytest.raises(StateTransitionError):
            # Can only be called in published state
            self.post.rewind()
        self.post.submit()
        self.post.publish()
        assert self.post.state.PUBLISHED
        d = self.post.published_at
        # Now we can call it
        self.post.rewind()
        assert self.post.state.PUBLISHED
        assert self.post.published_at < d

    def test_state_labels(self) -> None:
        """
        The current state's label can be accessed from the `.label` attribute
        """
        assert self.post.state.DRAFT
        assert self.post.state.label == "Draft"
        self.post.submit()
        assert self.post.state.label.name == 'pending'
        assert self.post.state.label.title == "Pending"

    def test_added_state_transition(self) -> None:
        """
        Transition works with added states as a `from` state
        """
        assert self.post.state.DRAFT
        self.post.submit()  # Change from DRAFT to PENDING
        self.post.publish()  # Change from PENDING to PUBLISHED
        assert self.post.state.PUBLISHED
        assert self.post.state.RECENT
        self.post.undo()  # Change from RECENT to PENDING

        self.post.publish()  # Change from PENDING to PUBLISHED
        assert self.post.state.RECENT
        self.post.rewind()
        assert not self.post.state.RECENT
        # `undo` shouldn't work anymore because the post is no longer RECENT
        with pytest.raises(StateTransitionError):
            self.post.undo()

    def test_added_regular_state_transition(self) -> None:
        """
        Transitions work with mixed use of regular and added states in the `from` state
        """
        assert self.post.state.DRAFT
        self.post.submit()  # Change from DRAFT to PENDING
        assert self.post.state.PENDING
        self.post.redraft()  # Change from PENDING back to DRAFT
        assert self.post.state.DRAFT

        self.post.submit()  # Change from DRAFT to PENDING
        self.post.publish()  # Change from PENDING to PUBLISHED
        assert self.post.state.PUBLISHED
        assert self.post.state.RECENT
        self.post.redraft()  # Change from RECENT to DRAFT

        self.post.submit()  # Change from DRAFT to PENDING
        self.post.publish()  # Change from PENDING to PUBLISHED
        assert self.post.state.RECENT
        self.post.rewind()
        assert not self.post.state.RECENT
        # `redraft` shouldn't work anymore because the post is no longer RECENT
        with pytest.raises(StateTransitionError):
            self.post.redraft()

    def test_reviewstate_also_changes(self) -> None:
        """Transitions with two decorators change state on both managers"""
        assert self.post.state.DRAFT
        assert self.post.reviewstate.UNSUBMITTED
        self.post.submit()  # This changes only `state`
        assert not self.post.state.DRAFT
        assert self.post.state.PENDING
        assert self.post.reviewstate.UNSUBMITTED
        self.post.publish()  # Now this changes both states
        assert not self.post.state.PENDING
        assert not self.post.reviewstate.UNSUBMITTED
        assert self.post.state.PUBLISHED
        assert self.post.reviewstate.PENDING

    def test_transition_state_lock(self) -> None:
        """Both states must be in valid state for a transition to be available"""
        self.post.submit()
        assert self.post.state.PENDING
        assert self.post.reviewstate.UNSUBMITTED
        self.post.publish()  # Publish works
        assert self.post.state.PUBLISHED
        self.post.undo()  # Go back to PENDING
        assert self.post.state.PENDING
        assert self.post.reviewstate.UNSUBMITTED
        self.post.publish()  # Publish again
        self.post.review_lock()  # Now lock it, preventing undo
        assert self.post.state.PUBLISHED
        assert not self.post.reviewstate.UNSUBMITTED
        assert self.post.reviewstate.LOCKED
        with pytest.raises(StateTransitionError):
            self.post.undo()  # Undo isn't available now

    def test_transition_from_none(self) -> None:
        """Transition from None ignores initial state."""
        assert self.post.state.DRAFT
        self.post._reviewstate = REVIEW_STATE.LOCKED
        assert self.post.state.DRAFT
        assert self.post.reviewstate.LOCKED
        self.post.submit()  # submit overrides LOCKED status
        assert not self.post.reviewstate.LOCKED
        assert self.post.state.PENDING

    def test_transition_abort(self) -> None:
        """Transitions can abort without changing state or raising an exception."""
        assert self.post.state.DRAFT

        # A transition can abort returning a value (a 2-tuple here)
        success, message = self.post.abort(success=False)  # type: ignore[misc]
        assert success is False
        assert message == "failed"
        assert self.post.state.DRAFT  # state has not changed

        # A transition can abort without returning a value
        result = self.post.abort(success=False, empty_abort=True)
        assert result is None
        assert self.post.state.DRAFT  # state has not changed

        success, message = self.post.abort(success=True)  # type: ignore[misc]
        assert success is True
        assert message == 'passed'
        assert self.post.state.PUBLISHED  # state has changed

    def test_transition_is_available(self) -> None:
        """A transition's is_available property is reliable"""
        assert self.post.state.DRAFT
        assert self.post.submit.is_available
        self.post.submit()
        assert not self.post.submit.is_available
        with pytest.raises(StateTransitionError):  # type: ignore[unreachable]
            self.post.submit()
        assert self.post.publish.is_available
        self.post.publish()
        assert self.post.undo.is_available
        assert self.post.review_lock.is_available
        self.post.review_lock()
        assert not self.post.undo.is_available

    def test_transition_data(self) -> None:
        """Additional data defined on a transition works regardless of decorator order"""
        # Titles are defined on different decorators on these:
        assert self.post.publish.data['title'] == "Publish"
        assert self.post.undo.data['title'] == "Undo"
        # Also available via the class
        assert MyPost.publish.data['title'] == "Publish"
        assert MyPost.undo.data['title'] == "Undo"

    def test_transition_data_name_invalid(self) -> None:
        """The `name` data field on transitions is reserved and cannot be specified"""
        state = MyPost.__dict__['state']
        with pytest.raises(TypeError):

            @state.transition(None, state.DRAFT, name='invalid_data_field')
            def name_test(self):
                pass

    def test_duplicate_transition(self) -> None:
        """Transitions can't be decorated twice with the same state manager"""
        state = MyPost.__dict__['state']
        with pytest.raises(TypeError):

            @state.transition(state.DRAFT, state.PENDING)
            @state.transition(state.PENDING, state.PUBLISHED)
            def dupe_decorator(self):
                pass

        state.transitions.remove('dupe_decorator')

    def test_available_transitions(self) -> None:
        """State managers indicate the currently available transitions"""
        assert self.post.state.DRAFT
        assert 'submit' in self.post.state.transitions(current=False)
        self.post.state.transitions(current=False)['submit']()
        assert not self.post.state.DRAFT
        assert self.post.state.PENDING

    def test_available_transitions_order(self) -> None:
        """State managers maintain the order of transitions from the class definition"""
        assert self.post.state.DRAFT
        # `submit` must come before `publish`
        assert list(self.post.state.transitions(current=False).keys())[:2] == [
            'submit',
            'publish',
        ]

    def test_currently_available_transitions(self) -> None:
        """State managers indicate the currently available transitions (using current_auth)"""
        assert self.post.state.DRAFT
        assert 'submit' not in self.post.state.transitions()
        add_auth_attribute(
            'user', 'author'
        )  # Add a user using the string 'author' (see MyPost.roles_for)
        assert 'submit' in self.post.state.transitions()
        self.post.state.transitions()['submit']()
        assert not self.post.state.DRAFT
        assert self.post.state.PENDING

    def test_available_transitions_for(self) -> None:
        """State managers indicate the currently available transitions (using access_for)"""
        assert self.post.state.DRAFT
        assert 'submit' not in self.post.state.transitions_for(roles={'reviewer'})
        assert 'submit' in self.post.state.transitions_for(roles={'author'})
        self.post.state.transitions_for(roles={'author'})['submit']()
        assert not self.post.state.DRAFT
        assert self.post.state.PENDING

    def test_current_states(self) -> None:
        """All states that are currently active"""
        current = self.post.state.current()
        assert set(current.keys()) == {'DRAFT', 'UNPUBLISHED', 'REDRAFTABLE'}
        assert current['DRAFT']
        assert current['DRAFT'].value == MY_STATE.DRAFT

        # Classes don't have a current state
        with pytest.raises(TypeError):
            MyPost.state.current()

    def test_managed_state_wrapper(self) -> None:
        """ManagedStateWrapper will only wrap a managed state or group"""
        draft = MyPost.__dict__['state'].DRAFT
        wdraft = ManagedStateInstance(draft, self.post)
        assert draft.value == wdraft.value
        assert wdraft  # Object is falsy
        assert self.post.state.DRAFT == wdraft
        self.post.submit()
        assert not wdraft
        # Object remains the same even if not active
        assert self.post.state.DRAFT == wdraft
        assert self.post.state.PENDING != wdraft  # These objects don't match

        with pytest.raises(TypeError):
            ManagedStateInstance(MY_STATE.DRAFT, self.post)  # type: ignore[arg-type]

    def test_role_proxy_transitions(self) -> None:
        """with_roles works on the transition decorator"""
        assert self.post.state.DRAFT
        # Create access proxies for each of these roles
        author = self.post.access_for(roles={'author'})
        reviewer = self.post.access_for(roles={'reviewer'})

        # Transitions are listed in the proxy even if not callable
        assert 'submit' in author
        assert 'publish' in author
        assert 'undo' in author
        assert 'redraft' in author
        assert 'review_lock' not in author
        assert 'review_unlock' not in author

        assert 'submit' not in reviewer
        assert 'publish' not in reviewer
        assert 'undo' not in reviewer
        assert 'redraft' not in reviewer
        assert 'review_lock' in reviewer
        assert 'review_unlock' in reviewer

        # The `is_available` test can be accessed through the proxy
        assert author.submit.is_available
        assert not author.undo.is_available
        # Transitions can be accessed through the proxy
        author.submit()
        author.publish()
        assert not author.submit.is_available
        assert author.undo.is_available

    def test_group_by_state(self) -> None:
        """StateManager.group returns a dictionary grouping items by their state."""
        assert self.post.state.DRAFT
        post2 = MyPost(_state=MY_STATE.PUBLISHED)
        post3 = MyPost(_state=MY_STATE.PUBLISHED)
        self.session.add_all([post2, post3])
        self.session.commit()
        groups1 = MyPost.state.group(MyPost.query.all())
        # Order is preserved. Draft before Published. No Pending.
        assert [g.label for g in groups1.keys()] == [
            MY_STATE[MY_STATE.DRAFT],
            MY_STATE[MY_STATE.PUBLISHED],
        ]
        # Order is preserved. Draft before Pending before Published.
        groups2 = MyPost.state.group(MyPost.query.all(), keep_empty=True)
        assert [g.label for g in groups2.keys()] == [
            MY_STATE[MY_STATE.DRAFT],
            MY_STATE[MY_STATE.PENDING],
            MY_STATE[MY_STATE.PUBLISHED],
        ]
        assert list(groups1.values()) == [[self.post], [post2, post3]]
        assert list(groups2.values()) == [[self.post], [], [post2, post3]]

        with pytest.raises(TypeError):
            MyPost.state.group([self.post, "Invalid type"])
