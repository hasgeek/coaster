"""
States and transitions
----------------------

:class:`StateManager` wraps a SQLAlchemy column with a
:class:`~coaster.utils.classes.LabeledEnum` to facilitate state inspection, and
to control state change via transitions. Sample usage::

    class MY_STATE(LabeledEnum):
        DRAFT = (0, "Draft")
        PENDING = (1, 'pending', "Pending")
        PUBLISHED = (2, "Published")

        UNPUBLISHED = {DRAFT, PENDING}


    # Classes can have more than one state variable
    class REVIEW_STATE(LabeledEnum):
        UNSUBMITTED = (0, "Unsubmitted")
        PENDING = (1, "Pending")
        REVIEWED = (2, "Reviewed")


    class MyPost(BaseMixin, db.Model):
        __tablename__ = 'my_post'

        # The underlying state value columns
        # (more than one state variable can exist)
        _state = db.Column('state', db.Integer,
            StateManager.check_constraint('state', MY_STATE),
            default=MY_STATE.DRAFT, nullable=False)
        _reviewstate = db.Column('reviewstate', db.Integer,
            StateManager.check_constraint('state', REVIEW_STATE),
            default=REVIEW_STATE.UNSUBMITTED, nullable=False)

        # The state managers controlling the columns
        state = StateManager('_state', MY_STATE, doc="The post's state")
        reviewstate = StateManager('_reviewstate', REVIEW_STATE,
            doc="Reviewer's state")

        # Datetime for the additional states and transitions
        datetime = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

        # Additional states:

        # RECENT = PUBLISHED + in the last one hour
        state.add_conditional_state('RECENT', state.PUBLISHED,
            lambda post: post.datetime > datetime.utcnow() - timedelta(hours=1))

        # REDRAFTABLE = DRAFT or PENDING or RECENT
        state.add_state_group('REDRAFTABLE',
            state.DRAFT, state.PENDING, state.RECENT)

        # Transitions change FROM one state TO another, and can have
        # an additional if_ condition (a callable) that must return True
        @state.transition(state.DRAFT, state.PENDING, if_=reviewstate.UNSUBMITTED)
        def submit(self):
            pass

        # Transitions can coordinate across state managers. All of them
        # must be in a valid FROM state for the transition to be available.
        # Transitions can also specify arbitrary metadata such as this `title`
        # attribute (on any of the decorators). These are made available in a
        # `data` dictionary, accessible here as `publish.data`
        @state.transition(state.UNPUBLISHED, state.PUBLISHED, title="Publish")
        @reviewstate.transition(reviewstate.UNSUBMITTED, reviewstate.PENDING)
        def publish(self):
            # A transition can do additional housekeeping
            self.datetime = datetime.utcnow()

        # A transition can use a conditional state. The condition is evaluated
        # before the transition can proceed
        @state.transition(state.RECENT, state.PENDING)
        @reviewstate.transition(reviewstate.PENDING, reviewstate.UNSUBMITTED)
        def undo(self):
            pass

        # Transitions can be defined FROM a group of states, but the TO
        # state must always be an individual state
        @state.transition(state.REDRAFTABLE, state.DRAFT)
        def redraft(self):
            pass

        # Transitions can abort without changing state, with or without raising
        # an exception to the caller
        @state.transition(state.REDRAFTABLE, state.DRAFT)
        def faulty_transition_examples(self):
            # Cancel the transition, but don't raise an exception to the caller
            raise AbortTransition()
            # Cancel the transition and return a result to the caller
            raise AbortTransition('failed')
            # Need to return a data structure? That works as well
            raise AbortTransition((False, 'faulty_failure'))
            raise AbortTransition({'status': 'error', 'error': 'faulty_failure'})
            # If any other exception is raised, it is passed up to the caller
            raise ValueError("Faulty transition")

        # The requires decorator specifies a transition that does not change
        # state. It can be used to limit a method's availability
        @state.requires(state.PUBLISHED)
        def send_email_alert(self):
            pass



Defining states and transitions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Adding a :class:`StateManager` to the class links the underlying column
(specified as a string) to the :class:`~coaster.utils.classes.LabeledEnum`
(specified as an object). The :class:`StateManager` is read-only and state can
only be mutated via transitions. The :class:`~coaster.utils.classes.LabeledEnum`
is not required after this point. All symbol names in it are available as
attributes on the state manager henceforth (as instances of
:class:`ManagedState`).

Conditional states can be defined with
:meth:`~StateManager.add_conditional_state` as a combination of an existing
state and a validator that receives the object (the instance of the class
the StateManager is present on). This can be used to evaluate for additional
conditions. For example, to distinguish between a static "published" state and
a dynamic "recently published" state.
:meth:`~StateManager.add_conditional_state` also takes an optional
``class_validator`` parameter that is used for queries against the class (see
below for query examples).

State groups can be defined with :meth:`~StateManager.add_state_group`. These
are similar to grouped values in a LabeledEnum, but can also contain
conditional states, and are stored as instances of :class:`ManagedStateGroup`.
Grouped values in a :class:`~coaster.utils.classes.LabeledEnum` are more
efficient for testing state against, so those should be preferred if the group
does not contain a conditional state.

Transitions connect one managed state or group to another state (but not
group). Transitions are defined as methods and decorated with
:meth:`~StateManager.transition`, which transforms them into instances of
:class:`StateTransition`, a callable class. If the transition raises an
exception, the state change is aborted. Transitions may also abort without
changing state using :exc:`AbortTransition`. Transitions have two additional
attributes, :attr:`~StateTransitionWrapper.is_available`, a boolean property
which indicates if the transition is currently available, and
:attr:`~StateTransition.data`, a dictionary that contains all additional
parameters passed to the :meth:`~StateManager.transition` decorator.

Transitions can be chained to coordinate a state change across state managers
if the class has more than one. All state managers must be in a valid ``from``
state for the transition to be available. A dictionary of currently available
transitions can be obtained from the state manager using the
:meth:`~StateManagerWrapper.transitions` method.


Queries
~~~~~~~

The current state of the object can be retrieved by calling the state
attribute or reading its ``value`` attribute::

    post = MyPost(_state=MY_STATE.DRAFT)
    post.state() == MY_STATE.DRAFT
    post.state.value == MY_STATE.DRAFT

The label associated with the state value can be accessed from the ``label`` attribute::

    post.state.label == "Draft"          # This is the string label from MY_STATE.DRAFT
    post.submit()                        # Change state from DRAFT to PENDING
    post.state.label.name == 'pending'   # Is the NameTitle tuple from MY_STATE.PENDING
    post.state.label.title == "Pending"  # The title part of NameTitle

States can be tested by direct reference using the names they were originally
defined with in the :class:`~coaster.utils.classes.LabeledEnum`::

    post.state.DRAFT        # True
    post.state.is_draft     # True (is_* attrs are lowercased aliases to states)
    post.state.PENDING      # False (since it's a draft)
    post.state.UNPUBLISHED  # True (grouped state values work as expected)
    post.publish()          # Change state from DRAFT to PUBLISHED
    post.state.RECENT       # True (calls the validator if the base state matches)

States can also be used for database queries when accessed from the class::

    # Generates MyPost._state == MY_STATE.DRAFT
    MyPost.query.filter(MyPost.state.DRAFT)

    # Generates MyPost._state.in_(MY_STATE.UNPUBLISHED)
    MyPost.query.filter(MyPost.state.UNPUBLISHED)

    # Generates and_(MyPost._state == MY_STATE.PUBLISHED,
    #     MyPost.datetime > datetime.utcnow() - timedelta(hours=1))
    MyPost.query.filter(MyPost.state.RECENT)

This works because :class:`StateManager`, :class:`ManagedState`
and :class:`ManagedStateGroup` behave in three different ways, depending on
context:

1. During class definition, the state manager returns the managed state. All
   methods on the state manager recognise these managed states and handle them
   appropriately.

2. After class definition, the state manager returns the result of calling the
   managed state instance. If accessed via the class, the managed state returns
   a SQLAlchemy filter condition.

3. After class definition, if accessed via an instance, the managed state
   returns itself wrapped in :class:`ManagedStateWrapper` (which holds context
   for the instance). This is an object that evaluates to ``True`` if the state
   is active, ``False`` otherwise. It also provides pass-through access to
   all attributes of the managed state.

States can be changed via transitions, defined as methods with the
:meth:`~StateManager.transition` decorator. They add more power and safeguards
over direct state value changes:

1. Original and final states can be specified, prohibiting arbitrary state
   changes.
2. The transition method can do additional validation and housekeeping.
3. Combined with the :func:`~coaster.sqlalchemy.roles.with_roles` decorator
   and :class:`~coaster.sqlalchemy.roles.RoleMixin`, transitions provide
   access control for state changes.
4. Signals are raised before and after a successful transition, or in case
   of failures, allowing for the attempts to be logged.
"""

from __future__ import annotations

import functools
import typing as t

import sqlalchemy as sa

from werkzeug.exceptions import BadRequest

from ..signals import coaster_signals
from ..utils import NameTitle, is_collection
from .roles import RoleMixin

__all__ = [
    'StateManager',
    'ManagedState',
    'ManagedStateGroup',
    'StateTransition',
    'StateManagerWrapper',
    'ManagedStateWrapper',
    'StateTransitionWrapper',
    'StateTransitionError',
    'AbortTransition',
    'transition_error',
    'transition_before',
    'transition_after',
    'transition_exception',
]

# --- Internal types -------------------------------------------------------------------

T = t.TypeVar('T')


# --- Signals --------------------------------------------------------------------------

#: Signal raised when a transition fails validation
transition_error = coaster_signals.signal(
    'transition-error', doc="Signal raised when a transition fails validation"
)

#: Signal raised before a transition (after validation)
transition_before = coaster_signals.signal(
    'transition-before', doc="Signal raised before a transition (after validation)"
)

#: Signal raised after a successful transition
transition_after = coaster_signals.signal(
    'transition-after', doc="Signal raised after a successful transition"
)

#: Signal raised when a transition raises an exception
transition_exception = coaster_signals.signal(
    'transition-exception', doc="Signal raised when a transition raises an exception"
)


# --- Exceptions -----------------------------------------------------------------------


class StateTransitionError(BadRequest, TypeError):
    """Raised if a transition is attempted from a non-matching state."""


class AbortTransition(Exception):  # noqa: N818
    """
    Transitions may raise :exc:`AbortTransition` to return without changing state.

    The parameter to this exception is returned as the transition's result.

    This exception is a signal to :class:`StateTransition` and will not be raised to
    the transition's caller.

    :param result: Value to return to the transition's caller
    """

    def __init__(self, result=None):  # pylint:disable=useless-super-delegation
        super().__init__(result)


# --- Classes --------------------------------------------------------------------------


class ManagedState:
    """
    Represents a state managed by a :class:`StateManager`.

    Do not use this class directly. Use :meth:`~StateManager.add_conditional_state`
    instead.
    """

    def __init__(
        self,
        name: str,
        statemanager: StateManager,
        value: t.Any,
        label: t.Optional[str] = None,
        validator: t.Callable[[t.Any], bool] = None,
        class_validator: t.Optional[t.Callable[[t.Any], None]] = None,
        cache_for: t.Union[None, int, t.Callable] = None,
    ):
        self.name = name
        self.statemanager = statemanager
        self.value = value
        self.label = label
        self.validator = validator
        self.class_validator = class_validator
        self.cache_for = cache_for

    @property
    def is_conditional(self):
        """Test for a conditional state."""
        return self.validator is not None

    @property
    def is_scalar(self):
        """
        Test for a scalar state.

        A scalar state is not a group of states, and may or may not have a condition.
        """
        return not is_collection(self.value)

    @property
    def is_direct(self):
        """
        Test for a direct state.

        A direct state is a scalar state without a condition.
        """
        return self.validator is None and not is_collection(self.value)

    def __repr__(self):
        return f'{self.statemanager.name}.{self.name}'

    def _eval(self, obj, cls=None):
        # TODO: Respect cache as specified in `cache_for`
        if obj is not None:  # We're being called with an instance
            if is_collection(self.value):
                valuematch = self.statemanager._value(obj, cls) in self.value
            else:
                valuematch = self.statemanager._value(obj, cls) == self.value
            if self.validator is not None:
                return valuematch and self.validator(obj)
            return valuematch
        # We have a class, so return a filter condition, for use as
        # cls.query.filter(result)
        if is_collection(self.value):
            valuematch = self.statemanager._value(obj, cls).in_(self.value)
        else:
            valuematch = self.statemanager._value(obj, cls) == self.value
        cv = self.class_validator
        if cv is None:
            cv = self.validator
        if cv is not None:
            return sa.and_(valuematch, cv(cls))
        return valuematch

    def __call__(self, obj, cls=None):
        """
        Test for whether a state is currently active.

        If called on the model, this will return a SQLAlchemy query filter.

        If called on the instance, this will return a wrapper that supports boolean
        evaluation.
        """
        # FIXME: Always return a ManagedStateWrapper. This requires either
        # (a) all existing use of model-level state tests to switch to call syntax:
        #     ``Model.state.PARTICULAR_STATE()`` (note parenthesis), or
        # (b) ManagedStateWrapper must implement SQLAlchemy interfaces so it becomes
        #     an expression when needed.

        if obj is not None:
            return ManagedStateWrapper(self, obj, cls)
        return self._eval(obj, cls)


class ManagedStateGroup:
    """
    Represents a group of managed states in a :class:`StateManager`.

    Do not use this class directly. Use :meth:`~StateManager.add_state_group` instead.
    """

    def __init__(self, name, statemanager, states):
        self.name = name
        self.statemanager = statemanager
        self.states = []

        # First, ensure all provided states are StateManager instances and associated
        # with the state manager
        for state in states:
            if (
                not isinstance(state, ManagedState)
                or state.statemanager != statemanager
            ):
                raise ValueError(f"Invalid state {state!r} for state group {self!r}")

        # Second, separate conditional from regular states (regular states may still be
        # grouped states)
        regular_states = [s for s in states if not s.is_conditional]
        conditional_states = [s for s in states if s.is_conditional]

        # Third, add all the regular states and keep a copy of their state values
        values = set()
        for state in regular_states:
            self.states.append(state)
            if is_collection(state.value):
                values.update(state.value)
            else:
                values.add(state.value)

        # Fourth, prevent adding a conditional state if the value is already present
        # from a regular state. This is an error as the condition will never be tested
        for state in conditional_states:
            # Prevent grouping of conditional states with their original states
            state_values = set(
                state.value if is_collection(state.value) else [state.value]
            )
            if state_values & values:  # They overlap
                raise ValueError(
                    f"The value for state {state!r} is already in this state group"
                )
            self.states.append(state)
            values.update(state_values)

    def __repr__(self):
        return f'{self.statemanager.name}.{self.name}'

    def _eval(self, obj, cls=None):
        if obj is not None:  # We're being called with an instance
            return any(s(obj, cls) for s in self.states)
        return sa.or_(*(s(obj, cls) for s in self.states))

    def __call__(self, obj, cls=None):
        """
        Test whether any of a group of states is currently active.

        If called on the model, this will return a SQLAlchemy query filter.

        If called on the instance, this will return a wrapper that supports boolean
        evaluation.
        """
        # FIXME: Always return a ManagedStateWrapper. This requires either
        # (a) all existing use of model-level state tests to switch to call syntax:
        #     ``Model.state.PARTICULAR_STATE()`` (note parenthesis), or
        # (b) ManagedStateWrapper must implement SQLAlchemy interfaces so it becomes
        #     an expression when needed.

        if obj is not None:
            return ManagedStateWrapper(self, obj, cls)
        return self._eval(obj, cls)


class ManagedStateWrapper:
    """
    Provides instance-level access to a managed state or group.

    This class is automatically constructed by :class:`StateManager` when a state is
    accessed from an instance.
    """

    def __init__(self, mstate, obj, cls=None):
        if not isinstance(mstate, (ManagedState, ManagedStateGroup)):
            raise TypeError(f"Parameter is not a managed state: {mstate!r}")
        self._mstate = mstate
        self._obj = obj
        self._cls = cls

    def __repr__(self):
        return f'<ManagedStateWrapper {self._mstate!r}>'

    def __call__(self):
        """Evaluate whether the state or state group is currently active."""
        return self._mstate._eval(self._obj, self._cls)

    def __getattr__(self, attr):
        return getattr(self._mstate, attr)

    def __eq__(self, other):
        return (
            isinstance(other, ManagedStateWrapper)
            and self._mstate == other._mstate
            and self._obj == other._obj
            and self._cls == other._cls
        )

    def __ne__(self, other):
        return not self.__eq__(other)

    def __bool__(self):
        return self()


class StateTransition:
    """
    Defines a transition from one state to another.

    Do not use this class directly. Use the :meth:`StateManager.transition` decorator
    instead. It creates an instance of this class to replace.
    """

    def __init__(self, func, statemanager, from_, to, if_=None, data=None):
        self.func = func
        functools.update_wrapper(self, func)
        self.name = func.__name__

        # Repeated use of @StateManager.transition will add to this dictionary
        # by calling add_transition directly
        self.transitions = {}
        # Repeated use of @StateManager.transition will update this dictionary
        # instead of replacing it
        self.data = {}
        self.add_transition(statemanager, from_, to, if_, data)

    def add_transition(self, statemanager, from_, to, if_=None, data=None):
        """Add a transition. For internal use by :meth:`ManagedState.transition`."""
        if statemanager in self.transitions:
            raise StateTransitionError("Duplicate transition decorator")
        if from_ is not None and not isinstance(
            from_, (ManagedState, ManagedStateGroup)
        ):
            raise StateTransitionError(f"From state is not a managed state: {from_!r}")
        if from_ and from_.statemanager != statemanager:
            raise StateTransitionError(
                f"From state is not managed by this state manager: {from_!r}"
            )
        if to is not None:
            if not isinstance(to, ManagedState):
                raise StateTransitionError(f"To state is not a managed state: {to!r}")
            if to.statemanager != statemanager:
                raise StateTransitionError(
                    f"To state is not managed by this state manager: {to!r}"
                )
            if not to.is_direct:
                raise StateTransitionError(f"To state must be a direct state: {to!r}")
        if data:
            if 'name' in data:
                raise TypeError("Invalid transition data parameter 'name'")
            self.data.update(data)
        self.data['name'] = self.name

        if if_ is None:
            if_ = []
        elif callable(if_):
            if_ = [if_]

        if from_ is None:
            state_values = None
        else:
            # Unroll grouped values so we can do a quick IN test when performing the
            # transition
            state_values = {}  # Value: ManagedState
            # Step 1: Convert ManagedStateGroup into a list of ManagedState items
            if isinstance(from_, ManagedStateGroup):
                from_ = from_.states
            else:  # ManagedState
                from_ = [from_]
            # Step 2: Unroll grouped values from the original LabeledEnum
            for mstate in from_:
                if is_collection(mstate.value):
                    for value in mstate.value:
                        state_values[value] = mstate
                else:
                    state_values[mstate.value] = mstate

        self.transitions[statemanager] = {
            'from': state_values,  # Dict of scalar_value: ManagedState
            'to': to,  # ManagedState (is_direct) of new state
            'if': if_,  # Additional conditions that must ALL pass
        }

    def __set_name__(self, owner, name):  # pragma: no cover
        self.name = name
        self.data['name'] = name

    # Make the transition a non-data descriptor
    def __get__(self, obj, cls=None):
        if obj is None:
            return self
        return StateTransitionWrapper(self, obj)


class StateTransitionWrapper:
    """
    Wraps :class:`StateTransition` with the context of the object it is accessed from.

    Automatically constructed by :class:`StateTransition`.
    """

    def __init__(self, statetransition, obj):
        self.statetransition = statetransition
        self.obj = obj

    @property
    def data(self):
        """Return data as provided to the :meth:`~StateManager.transition` decorator."""
        return self.statetransition.data

    def _state_invalid(self):
        """
        If the state is invalid for the transition, return details on what didn't match.

        :return: Tuple of (state manager, current state, label for current state)
        """
        for statemanager, conditions in self.statetransition.transitions.items():
            current_state = getattr(self.obj, statemanager.propname)
            if conditions['from'] is None:
                state_valid = True
            else:
                mstate = conditions['from'].get(current_state)
                state_valid = mstate and mstate(self.obj)
            if state_valid and conditions['if']:
                state_valid = all(v(self.obj) for v in conditions['if'])
            if not state_valid:
                return (
                    statemanager,
                    current_state,
                    statemanager.lenum.get(current_state),
                )

    @property
    def is_available(self):
        """Property that indicates whether this transition is currently available."""
        return not self._state_invalid()

    def __getattr__(self, name):
        return getattr(self.statetransition, name)

    def __call__(self, *args, **kwargs):
        """Perform the state transition."""
        # Validate that each of the state managers is in the correct state
        state_invalid = self._state_invalid()
        if state_invalid:
            transition_error.send(
                self.obj, transition=self.statetransition, statemanager=state_invalid[0]
            )
            label = state_invalid[2]
            if isinstance(label, NameTitle):
                label = label.title
            raise StateTransitionError(
                f"Invalid state for transition {self.statetransition.name}:"
                f" {state_invalid[0]!r} = {label}"
            )

        # Send a transition-before signal
        transition_before.send(self.obj, transition=self.statetransition)
        # Call the transition method
        try:
            result = self.statetransition.func(self.obj, *args, **kwargs)
        except AbortTransition as e:
            transition_exception.send(
                self.obj, transition=self.statetransition, exception=e
            )
            return e.args[0]
        except Exception as e:  # noqa: B902
            transition_exception.send(
                self.obj, transition=self.statetransition, exception=e
            )
            raise

        # Change the state for each of the state managers
        for statemanager, conditions in self.statetransition.transitions.items():
            if (
                conditions['to'] is not None
            ):  # Allow to=None for the @requires decorator
                statemanager._set(self.obj, conditions['to'].value)  # Change state
        # Send a transition-after signal
        transition_after.send(self.obj, transition=self.statetransition)
        return result


class StateManager:
    """
    Provides state management around a database column or property.

    Wraps a property with a :class:`~coaster.utils.classes.LabeledEnum` to
    facilitate state inspection and control state changes.

    This is the main export of this module.

    :param str propname: Name of the property that is to be wrapped
    :param LabeledEnum lenum: The :class:`~coaster.utils.classes.LabeledEnum` containing
        valid values
    :param str doc: Optional docstring
    """

    def __init__(self, propname, lenum, doc=None):
        self.owner = None  # Depend on __set_name__ or __get__ to correct
        self.propname = propname
        self.name = propname  # Incorrect, so we depend on __set_name__ to correct this
        self.lenum = lenum
        self.__doc__ = doc

        # name: ManagedState/ManagedStateGroup
        self.states = {}
        # value: ManagedState (no conditional states or groups)
        self.states_by_value = {}
        # Same, but as a list including conditional states
        self.all_states_by_value = {}
        self.transitions = []  # names of transitions linked to this state manager

        # Make a copy of all states in the lenum within the state manager as a
        # ManagedState. We do NOT convert grouped states into a ManagedStateGroup
        # instance, as ManagedState is more efficient at testing whether a value is in
        # a group: it uses the `in` operator while ManagedStateGroup does
        # `any(s() for s in states)`.
        for state_name, value in lenum.__names__.items():
            self._add_state_internal(
                state_name,
                value,
                # Grouped states are represented as sets and can't have labels, so be
                # careful about those
                label=lenum[value] if not isinstance(value, (list, set)) else None,
            )

    def __set_name__(self, owner, name):
        self.owner = owner
        self.name = name

    def __repr__(self):
        if self.owner is not None:
            return f'{self.owner.__name__}.{self.name}'
        return f'<StateManager {self.name}>'

    def __get__(
        self, obj: t.Optional[T], cls: t.Optional[t.Type[T]] = None
    ) -> StateManagerWrapper[T]:
        return StateManagerWrapper(self, obj, cls)

    def __set__(self, obj, value):
        raise AttributeError("States are read-only; use a transition")

    # Since __get__ never returns self, the following methods will only be available
    # within the owning class's namespace. It will not be possible to call them outside
    # the class to add conditional states or transitions. If a use case arises,
    # add wrapper methods to StateManagerWrapper.

    def _set(self, obj, value):
        """Set state; internal method called by meth:`StateTransition.__call__`."""
        if value not in self.lenum:
            raise ValueError(f"Not a valid value: {value!r}")

        type(obj).__dict__[self.propname].__set__(obj, value)

    def _add_state_internal(
        self,
        name,
        value,
        label=None,
        validator=None,
        class_validator=None,
        cache_for=None,
    ):
        # Also see `add_state_group` for similar code
        if hasattr(self, name):  # Don't clobber self with a state name
            raise AttributeError(
                f"State name {name!r} conflicts with an existing attribute in the state"
                f" manager"
            )
        mstate = ManagedState(
            name=name,
            statemanager=self,
            value=value,
            label=label,
            validator=validator,
            class_validator=class_validator,
            cache_for=cache_for,
        )
        # XXX: Since mstate.statemanager == self, the following assignments setup
        # looping references and could cause a memory leak if the statemanager is ever
        # deleted. We depend on it being permanent for the lifetime of the process in
        # typical use (or for advanced memory management that can detect loops).
        self.states[name] = mstate
        if mstate.is_direct:
            self.states_by_value[value] = mstate
        if mstate.is_scalar:
            self.all_states_by_value.setdefault(value, []).insert(0, mstate)
        # Make the ManagedState available as `statemanager.STATE` (assuming original was
        # uppercased)
        setattr(self, name, mstate)
        # Also make available as `statemanager.is_state`
        setattr(self, 'is_' + name.lower(), mstate)

    # Stub for mypy to recognise names added by _add_state_internal
    def __getattr__(self, name: str) -> t.Union[ManagedState, ManagedStateGroup]:
        raise AttributeError(name)

    def add_state_group(self, name, *states):
        """
        Add a group of managed states.

        Groups can be specified directly in the
        :class:`~coaster.utils.classes.LabeledEnum`. This method is only useful for
        grouping a conditional state with existing states. It cannot be used to form a
        group of groups.

        :param str name: Name of this group
        :param states: :class:`ManagedState` instances to be grouped together
        """
        # See `_add_state_internal` for explanation of the following
        if hasattr(self, name):
            raise AttributeError(
                f"State group name {name!r} conflicts with an existing "
                f"attribute in the state manager"
            )
        mstate = ManagedStateGroup(name, self, states)
        self.states[name] = mstate
        setattr(self, name, mstate)
        setattr(self, 'is_' + name.lower(), mstate)

    def add_conditional_state(
        self,
        name: str,
        state: t.Union[ManagedState, ManagedStateGroup],
        validator: t.Callable[[t.Any], bool],
        class_validator: t.Optional[t.Callable[[t.Any], bool]] = None,
        cache_for: t.Union[None, int, t.Callable] = None,
        label: t.Union[None, str, t.Tuple[str, str]] = None,
    ):
        """
        Add a conditional state (direct state + condition validator).

        The validator receives the state manager's host object and must return `True` if
        the condition exists.

        :param str name: Name of the new state
        :param ManagedState state: Existing state that this is based on
        :param validator: Function that will be called with the host object as a
            parameter
        :param class_validator: Function that will be called when the state is queried
            on the class instead of the instance. Falls back to ``validator`` if not
            specified. Receives the class as the parameter
        :param cache_for: Integer or function that indicates how long ``validator``'s
            result can be cached (not applicable to ``class_validator``). ``None``
            implies no cache, ``0`` implies indefinite cache (until invalidated by a
            transition) and any other integer is the number of seconds for which to
            cache the assertion
        :param label: Label for this state (string or 2-tuple)

        TODO: `cache_for`'s implementation is currently pending a test case
        demonstrating how it will be used.
        """
        # We'll accept a ManagedState with grouped values, but not a ManagedStateGroup
        if not isinstance(state, ManagedState):
            raise TypeError(f"Not a managed state: {state!r}")
        if state.statemanager != self:
            raise ValueError(
                f"State {state!r} is not associated with this state manager"
            )
        if isinstance(label, tuple) and len(label) == 2:
            label = NameTitle(*label)
        self._add_state_internal(
            name,
            state.value,
            label=label,
            validator=validator,
            class_validator=class_validator,
            cache_for=cache_for,
        )

    def transition(self, from_, to, if_=None, **data):
        """
        Decorate a method to transition from one state to another.

        The decorated method can accept any necessary parameters and perform additional
        processing, or raise an exception to abort the transition. If it returns without
        an error, the state value is updated automatically. Transitions may also abort
        without raising an exception using :exc:`AbortTransition`.

        :param from_: Required state to allow this transition (can be a state group)
        :param to: The state of the object after this transition (automatically set if
            no exception is raised)
        :param if_: Validator(s) that, given the object, must all return True for the
            transition to proceed
        :param data: Additional metadata, stored on the `StateTransition` object as a
            :attr:`data` attribute
        """

        def decorator(f):
            if isinstance(f, StateTransition):
                f.add_transition(self, from_, to, if_, data)
                st = f
            else:
                st = StateTransition(f, self, from_, to, if_, data)
            self.transitions.append(st.name)
            return st

        return decorator

    def requires(
        self,
        from_: t.Union[ManagedState, ManagedStateGroup],
        if_: t.Optional[t.Callable[[t.Any], bool]] = None,
        **data,
    ):
        """
        Decorate a method to only be callable when the given state is currently active.

        Registers a transition internally, but does not change the state.

        :param from_: Required state to allow this call (can be a state group)
        :param if_: Validator(s) that, given the object, must all return True for the
            call to proceed
        :param data: Additional metadata, stored on the `StateTransition` object as a
            :attr:`data` attribute
        """
        return self.transition(from_, None, if_, **data)

    def _value(self, obj, cls=None):
        """Return state value (called from the wrapper)."""
        if obj is not None:
            return getattr(obj, self.propname)
        return getattr(cls, self.propname)

    @staticmethod
    def check_constraint(column, lenum, **kwargs):
        """
        Construct a SQL CHECK constraint.

        Requires a column name and a :class:`~coaster.utils.classes.LabeledEnum`
        containing valid values. Usage::

            class MyModel(db.Model):
                _state = db.Column(
                    'state',
                    db.Integer,
                    StateManager.check_constraint('state', MY_ENUM),
                    default=MY_ENUM.DEFAULT
                )
                state = StateManager(_state, MY_ENUM)

        Alembic may not detect the CHECK constraint when autogenerating migrations, so
        you may need to do this manually using the Python console to extract the SQL
        string::

            from coaster.sqlalchemy import StateManager
            from your_app.models import YOUR_ENUM

            print(str(StateManager.check_constraint('your_column', YOUR_ENUM).sqltext))

        :param str column: Column name
        :param LabeledEnum lenum: :class:`~coaster.utils.classes.LabeledEnum` to
            retrieve valid values from
        :param kwargs: Additional options passed to CheckConstraint
        """
        return sa.CheckConstraint(
            str(
                sa.column(column)
                .in_(lenum.keys())
                .compile(compile_kwargs={'literal_binds': True})
            ),
            **kwargs,
        )


class StateManagerWrapper(t.Generic[T]):
    """
    Wraps :class:`StateManager` with the context of the containing object.

    Automatically constructed when a :class:`StateManager` is accessed from either a
    class or an instance.
    """

    def __init__(self, statemanager, obj: t.Optional[T], cls: t.Optional[t.Type[T]]):
        self.statemanager = statemanager  # StateManager
        # Instance we're being called on, None if called on the class instead
        self.obj = obj
        # The class of the instance we're being called on
        self.cls = cls

    def __repr__(self):
        return (
            f'<StateManagerWrapper({type(self.obj).__name__}.{self.statemanager.name})>'
        )

    @property
    def value(self):
        """Return current state's value."""
        return self.statemanager._value(self.obj, self.cls)

    @property
    def label(self):
        """Label for the current state's value (using :meth:`bestmatch`)."""
        return self.bestmatch().label

    def bestmatch(self):
        """
        Return best matching current scalar state (direct or conditional).

        Only applicable when accessed via an instance.
        """
        if self.obj is not None:
            for mstate in self.statemanager.all_states_by_value[self.value]:
                msw = mstate(self.obj, self.cls)  # This returns a wrapper
                if msw:  # If the wrapper evaluates to True, it's our best match
                    return msw

    def current(self):
        """Return all states and state groups that are currently active."""
        if self.obj is not None:
            return {
                name: mstate(self.obj, self.cls)
                for name, mstate in self.statemanager.states.items()
                if mstate(self.obj, self.cls)
            }

    def transitions(self, current=True) -> t.Dict[str, StateTransitionWrapper]:
        """
        Return available transitions for the current state.

        :param bool current: Limit to transitions available in ``obj.``
           :meth:`~coaster.sqlalchemy.mixins.RoleMixin.current_access`
        """
        if current and isinstance(self.obj, RoleMixin):
            proxy = self.obj.current_access()
        else:
            proxy = {}
            current = False  # In case the host object is not a RoleMixin
        return {
            name: transition
            for name, transition in
            # Retrieve transitions from the host object to activate the descriptor.
            ((name, getattr(self.obj, name)) for name in self.statemanager.transitions)
            if transition.is_available and (name in proxy if current else True)
        }

    def transitions_for(
        self, roles=None, actor=None, anchors=()
    ) -> t.Dict[str, StateTransitionWrapper]:
        """
        Return currently available transitions for the given actor or roles.

        This requires the host object to be derived from
        :class:`~coaster.sqlalchemy.mixins.RoleMixin`.
        """
        # Mypy complains because it can't infer that self.obj is RoleMixin instance.
        proxy = self.obj.access_for(  # type: ignore[union-attr]
            roles=roles, actor=actor, anchors=anchors
        )
        return {
            name: transition
            for name, transition in self.transitions(current=False).items()
            if name in proxy
        }

    def group(
        self, items: t.Iterable[T], keep_empty=False
    ) -> t.Dict[ManagedState, t.List[T]]:
        """
        Given an iterable of instances, groups them by state.

        Uses :class:`ManagedState` instances as dictionary keys. Returns a dict that
        preserves the order of states from the source
        :class:`~coaster.utils.classes.LabeledEnum`.

        :param bool keep_empty: If ``True``, empty states are included in the result
        """
        cls = (
            self.cls if self.cls is not None else type(self.obj)
        )  # Class of the item being managed
        groups: t.Dict[ManagedState, t.List[T]] = {}
        for mstate in self.statemanager.states_by_value.values():
            # Ensure we sort groups using the order of states in the source LabeledEnum.
            # We'll discard the unused states later.
            groups[mstate] = []
        # Now process the items by state
        for item in items:
            # Use isinstance instead of `type(item) != cls` to account for subclasses
            if not isinstance(item, cls):
                raise TypeError(
                    f"Item {item!r} is not an instance of type {self.cls!r}"
                )
            statevalue = self.statemanager._value(item)
            mstate = self.statemanager.states_by_value[statevalue]
            groups[mstate].append(item)
        if not keep_empty:
            for key, value in list(groups.items()):
                if not value:
                    del groups[key]
        return groups

    def __getattr__(self, name):
        """
        Retrieve a state.

        1. If called on an instance, returns a :class:`ManagedStateWrapper`, which
           implements `__bool__` to test for the state being active.
        2. If called on a class, returns a query filter.

        (This logic is handled in :class:`ManagedState` and :class:`ManagedStateGroup`,
        not here.)

        :raises AttributeError: if the state is not known
        """
        if hasattr(self.statemanager, name):
            mstate = getattr(self.statemanager, name)
            if isinstance(mstate, (ManagedState, ManagedStateGroup)):
                return mstate(self.obj, self.cls)
        raise AttributeError(f"Not a state: {name}")
