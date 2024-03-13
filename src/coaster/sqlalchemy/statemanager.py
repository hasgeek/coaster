"""
States and transitions
----------------------

:class:`StateManager` wraps a SQLAlchemy column with an enum to facilitate state
inspection, and to control state change via transitions. Sample usage::

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


    class MyPost(BaseMixin, Model):
        __tablename__ = 'my_post'

        # The underlying state value columns
        # (more than one state variable can exist)
        _state: Mapped[int] = sa.orm.mapped_column(
            'state',
            sa.Integer,
            StateManager.check_constraint('state', MY_STATE, sa.Integer),
            default=MY_STATE.DRAFT,
            nullable=False
        )
        _reviewstate: Mapped[int] = sa.orm.mapped_column(
            'reviewstate',
            sa.Integer,
            StateManager.check_constraint('reviewstate', REVIEW_STATE, sa.Integer),
            default=REVIEW_STATE.UNSUBMITTED,
            nullable=False
        )

        # The state managers controlling the columns. If the host type is optionally
        # provided as a generic type argument, it will be applied to the lambda
        # functions in add_conditional_state for static type checking
        state = StateManager['MyPost']('_state', MY_STATE, doc="The post's state")
        reviewstate = StateManager(
            '_reviewstate', REVIEW_STATE, doc="Reviewer's state"
        )

        # Datetime for the additional states and transitions
        timestamp: Mapped[datetime] = sa.orm.mapped_column(
            sa.DateTime, default=datetime.utcnow, nullable=False
        )

        # Additional states:

        # RECENT = PUBLISHED + in the last one hour
        state.add_conditional_state(
            'RECENT',
            state.PUBLISHED,
            lambda post: post.datetime > datetime.utcnow() - timedelta(hours=1)
        )

        # REDRAFTABLE = DRAFT or PENDING or RECENT
        state.add_state_group(
            'REDRAFTABLE', state.DRAFT, state.PENDING, state.RECENT
        )

        # Transitions change FROM one state TO another, and can require another state
        # manager to be in a specific state
        @state.transition(state.DRAFT, state.PENDING)
        @reviewstate.requires(reviewstate.UNSUBMITTED)
        def submit(self) -> None:
            pass

        # Transitions can coordinate across state managers. All of them must be in a
        # valid FROM state for the transition to be available. Transitions can also
        # specify arbitrary metadata such as this `title` attribute (on any of the
        # decorators). These are made available in a `data` dictionary, accessible here
        # as `publish.data`
        @state.transition(state.UNPUBLISHED, state.PUBLISHED, title="Publish")
        @reviewstate.transition(reviewstate.UNSUBMITTED, reviewstate.PENDING)
        def publish(self) -> None:
            # A transition can do additional housekeeping
            self.timestamp = datetime.utcnow()

        # A transition can use a conditional state. The condition is evaluated before
        # the transition can proceed
        @state.transition(state.RECENT, state.PENDING)
        @reviewstate.transition(reviewstate.PENDING, reviewstate.UNSUBMITTED)
        def undo(self) -> None:
            pass

        # Transitions can be defined FROM a group of states, but the TO state must
        # always be an individual state
        @state.transition(state.REDRAFTABLE, state.DRAFT)
        def redraft(self) -> None:
            pass

        # Transitions can abort without changing state, with or without raising an
        # exception to the caller
        @state.transition(state.REDRAFTABLE, state.DRAFT)
        def faulty_transition_examples(self) -> Union[str, Tuple[bool, str], dict]:
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
        def send_email_alert(self) -> None:
            pass



Defining states and transitions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Adding a :class:`StateManager` to the class links the underlying column (specified as a
string) to the :class:`~coaster.utils.classes.LabeledEnum` (specified as an object).
The :class:`StateManager` is read-only and state can only be mutated via transitions.
The :class:`~coaster.utils.classes.LabeledEnum` is not required after this point. All
symbol names in it are available as attributes on the state manager henceforth (as
instances of :class:`ManagedState`).

Conditional states can be defined with :meth:`~StateManager.add_conditional_state` as a
combination of an existing state and a validator that receives the object (the instance
of the class the StateManager is present on). This can be used to evaluate for
additional conditions. For example, to distinguish between a static "published" state
and a dynamic "recently published" state. :meth:`~StateManager.add_conditional_state`
also takes an optional ``class_validator`` parameter that is used for queries against
the class (see below for query examples).

State groups can be defined with :meth:`~StateManager.add_state_group`. These are
similar to grouped values in a LabeledEnum, but can also contain conditional states,
and are stored as instances of :class:`ManagedStateGroup`. Grouped values in a
:class:`~coaster.utils.classes.LabeledEnum` are more efficient for testing state
against, so those should be preferred if the group does not contain a conditional state.

Transitions connect one managed state or group to another state (but not group).
Transitions are defined as methods and decorated with :meth:`~StateManager.transition`,
which transforms them into instances of :class:`StateTransition`, a callable class. If
the transition raises an exception, the state change is aborted. Transitions may also
abort without raising an exception to the caller using the special exception
:exc:`AbortTransition`. Transitions have two additional attributes,
:attr:`~StateTransitionWrapper.is_available`, a boolean property which indicates if the
transition is available given the object's current state, and
:attr:`~StateTransition.data`, a dictionary that contains all additional parameters
passed to the :meth:`~StateManager.transition` decorator. :attr:`~StateTransition.data`
``['name']`` will always be the wrapped method's name.

Transitions can be chained to coordinate a state change across state managers if the
class has more than one. All state managers must be in a valid ``from`` state for the
transition to be available. A dictionary of currently available transitions can be
obtained from the state manager using the :meth:`~StateManagerWrapper.transitions`
method.

Namespace
~~~~~~~~~

The StateManager's methods and states share a single namespace under the assumption that
method names are always lowercase and states are always uppercase, following the
convention used in enums.

Queries
~~~~~~~

The current state of the object can be retrieved by calling the state attribute or
reading its ``value`` attribute::

    post = MyPost(_state=MY_STATE.DRAFT)
    post.state() == MY_STATE.DRAFT
    post.state.value == MY_STATE.DRAFT

The label associated with the state value can be accessed from the ``label`` attribute::

    post.state.label == "Draft"          # This is the string label from MY_STATE.DRAFT
    post.submit()                        # Change state from DRAFT to PENDING
    post.state.label.name == 'pending'   # Is the NameTitle tuple from MY_STATE.PENDING
    post.state.label.title == "Pending"  # The title part of NameTitle

States can be tested by direct reference using the names they were originally defined
with in the :class:`~coaster.utils.classes.LabeledEnum`::

    post.state.DRAFT        # True
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

This works because :class`ManagedState` implements SQLAlchemy's interfaces for casting
into a SQL expression. When accessed via an instance, the managed state is wrapped in
:class:`ManagedStateInstance`. This object can be cast into a boolean and evaluates to
``True`` if the state is active, ``False`` otherwise. It also provides pass-through
access to all attributes of the managed state.

States can be changed via transitions, defined as methods with the
:meth:`~StateManager.transition` decorator. They add more power and safeguards over
direct state value changes:

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
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Generic,
    NoReturn,
    Optional,
    Union,
    cast,
    overload,
)
from typing_extensions import Concatenate, ParamSpec, Self, TypeVar

import sqlalchemy as sa
from werkzeug.exceptions import BadRequest

from ..signals import coaster_signals
from ..utils import LabeledEnum, NameTitle, is_collection
from .roles import RoleAccessProxy, RoleMixin

__all__ = [
    'StateManager',
    'ManagedState',
    'ManagedStateGroup',
    'StateTransition',
    'StateManagerInstance',
    'ManagedStateInstance',
    'StateTransitionWrapper',
    'StateTransitionError',
    'AbortTransition',
    'transition_error',
    'transition_before',
    'transition_after',
    'transition_exception',
]

# --- Internal types -------------------------------------------------------------------

_SG = TypeVar('_SG', default=Any)  # The declared type hosting StateManager
_T = TypeVar('_T')  # The type from which StateManager was accessed in __get__
_SM = TypeVar('_SM', bound='StateManager')
_P = ParamSpec('_P')  # ParamSpec for wrapped functions
_R = TypeVar('_R')  # Return type for wrapped functions


@dataclass
class _TransitionPerStateManager:
    """Internal data on how a transition involves each of multiple StateManagers."""

    from_: Optional[dict[Any, ManagedState]]
    to: Optional[ManagedState]


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


class AbortTransition(BaseException):
    """
    Transitions may raise :exc:`AbortTransition` to return without changing state.

    The parameter to this exception is returned as the transition's result.

    This exception is a signal to :class:`StateTransition` and will not be raised to
    the transition's caller.

    :param result: Value to return to the transition's caller
    """

    def __init__(self, result: Any = None) -> None:
        super().__init__()
        self.result = result


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
        value: Any,
        label: Optional[Any] = None,  # TODO: Make this `str` (drop NameTitle)
        validator: Optional[Callable[[Any], bool]] = None,
        class_validator: Optional[Callable[[type[Any]], sa.ColumnElement[bool]]] = None,
    ) -> None:
        self.name = name
        self.statemanager = statemanager
        self.value = value
        self.label = label
        self.validator = validator
        self.class_validator = class_validator

    def __repr__(self) -> str:
        return f'<ManagedState {self.statemanager.name}.{self.name}>'

    @property
    def is_conditional(self) -> bool:
        """Test for a conditional state."""
        return self.validator is not None

    @property
    def is_scalar(self) -> bool:
        """
        Test for a scalar state.

        A scalar state is not a group of states, and may or may not have a condition.
        """
        return not is_collection(self.value)

    @property
    def is_static(self) -> bool:
        """
        Test for a direct state.

        A direct state is a scalar state without a condition.
        """
        return self.validator is None and not is_collection(self.value)

    def is_current_in(self, obj: Any) -> bool:
        """Test if the given object is currently in this state."""
        # pylint: disable=protected-access
        if is_collection(self.value):
            valuematch = self.statemanager._get_state_value(obj) in self.value
        else:
            valuematch = self.statemanager._get_state_value(obj) == self.value
        if self.validator is not None:
            return valuematch and self.validator(obj)
        return valuematch

    def __clause_element__(
        self, cls: Optional[type[Any]] = None
    ) -> sa.ColumnElement[bool]:
        """Return a SQL expression for testing if this state is current."""
        if cls is None:
            cls = self.statemanager.cls
        if cls is None:
            raise RuntimeError("This state is not affiliated with a host class")
        # pylint: disable=protected-access
        if is_collection(self.value):
            valuematch = self.statemanager._get_state_value(None).in_(self.value)
        else:
            valuematch = self.statemanager._get_state_value(None) == self.value

        cv = self.class_validator
        if cv is None:
            cv = cast(
                Optional[Callable[[type[Any]], sa.ColumnElement[bool]]],
                self.validator,
            )
        if cv is not None:
            return sa.and_(valuematch, cv(cls))
        return valuematch

    def __invert__(self) -> sa.ColumnElement[bool]:
        return ~self.__clause_element__()  # pylint: disable=invalid-unary-operand-type


class ManagedStateGroup:
    """
    Represents a group of managed states in a :class:`StateManager`.

    Do not use this class directly. Use :meth:`~StateManager.add_state_group` instead.
    """

    def __init__(
        self,
        name: str,
        statemanager: StateManager,
        states: Iterable[Union[ManagedState, ManagedStateGroup]],
    ) -> None:
        self.name = name
        self.statemanager = statemanager
        self.states: list[ManagedState] = []

        # First, ensure all provided states are StateManager instances and associated
        # with the state manager
        for state in states:
            if (
                not isinstance(state, ManagedState)
                or state.statemanager != statemanager
            ):
                raise ValueError(f"Invalid state {state!r} for state group {self!r}")

        if TYPE_CHECKING:
            # Tell Mypy that we only have ManagedState in the list now
            states = cast(Iterable[ManagedState], states)

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

    def __repr__(self) -> str:
        return f'<ManagedStateGroup {self.statemanager.name}.{self.name}>'

    def is_current_in(self, obj: Any) -> bool:
        """Test if the given object is currently in any of this group of states."""
        return any(s.is_current_in(obj) for s in self.states)

    def __clause_element__(
        self, cls: Optional[type[Any]] = None
    ) -> sa.ColumnElement[bool]:
        """Return a SQL expression for testing if this state is current."""
        return sa.or_(*(s.__clause_element__(cls) for s in self.states))

    def __invert__(self) -> sa.ColumnElement[bool]:
        return ~self.__clause_element__()  # pylint: disable=invalid-unary-operand-type


class ManagedStateInstance(Generic[_T]):
    """
    Provides runtime access to a managed state or group in the instance.

    This class is automatically constructed by :class:`StateManager` when a state is
    accessed from an instance.
    """

    def __init__(
        self,
        mstate: Union[ManagedState, ManagedStateGroup],
        obj: _T,
    ) -> None:
        if not isinstance(mstate, (ManagedState, ManagedStateGroup)):
            raise TypeError(f"Parameter is not a managed state: {mstate!r}")
        self._mstate = mstate
        self._obj = obj
        self.cls = type(obj)

    def __repr__(self) -> str:
        return repr(self._mstate)

    def __getattr__(self, attr: str) -> Any:
        return getattr(self._mstate, attr)

    def __eq__(self, other: Any) -> bool:
        return (
            isinstance(other, ManagedStateInstance)
            and self._mstate == other._mstate
            and self._obj == other._obj
        )

    def __bool__(self) -> bool:
        return self._mstate.is_current_in(self._obj)


class StateTransition(Generic[_P, _R]):
    """
    Defines a transition from one state to another.

    Do not use this class directly. Use the :meth:`StateManager.transition` decorator
    instead. It creates an instance of this class to replace.
    """

    transitions: dict[StateManager, _TransitionPerStateManager]
    data: dict[str, Any]

    def __init__(
        self,
        func: Callable[Concatenate[Any, _P], _R],
        statemanager: StateManager,
        from_: Optional[Union[ManagedState, ManagedStateGroup]],
        to: Optional[Union[ManagedState, ManagedStateGroup]],
        data: Optional[dict[str, Any]] = None,
    ) -> None:
        self.func = func
        functools.update_wrapper(self, func)
        self.name = func.__name__

        # Repeated use of @StateManager.transition will add to this dictionary
        # by calling add_transition directly
        self.transitions = {}
        # Repeated use of @StateManager.transition will update this dictionary
        # instead of replacing it
        self.data = {'name': self.name}
        self.add_transition(statemanager, from_, to, data)

    def add_transition(
        self,
        statemanager: StateManager,
        from_: Optional[Union[ManagedState, ManagedStateGroup]],
        to: Optional[Union[ManagedState, ManagedStateGroup]],
        data: Optional[dict[str, Any]] = None,
    ) -> None:
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
            if not to.is_static:
                raise StateTransitionError(f"To state must be a direct state: {to!r}")
        if data:
            if 'name' in data:
                raise TypeError("Invalid transition data parameter 'name'")
            self.data.update(data)

        if from_ is None:
            state_values: Optional[dict[Any, ManagedState]] = None
        else:
            # Unroll grouped values so we can do a quick IN test when performing the
            # transition
            state_values = {}  # Value: ManagedState
            # Step 1: Convert ManagedStateGroup into a list of ManagedState items
            if isinstance(from_, ManagedStateGroup):
                from_all = from_.states
            else:  # ManagedState
                from_all = [from_]
            # Step 2: Unroll grouped values from the original LabeledEnum
            for mstate in from_all:
                if is_collection(mstate.value):
                    for value in mstate.value:
                        state_values[value] = mstate
                else:
                    state_values[mstate.value] = mstate

        self.transitions[statemanager] = _TransitionPerStateManager(
            from_=state_values,  # Dict of static_value: ManagedState
            to=to,  # ManagedState (is_static) of new state
        )

    def __set_name__(self, _owner: type[Any], name: str) -> None:  # pragma: no cover
        self.name = name
        self.data['name'] = name

    @overload
    def __get__(self, obj: None, cls: Optional[type[Any]] = None) -> Self: ...

    @overload
    def __get__(
        self, obj: _T, cls: Optional[type[_T]] = None
    ) -> StateTransitionWrapper[_P, _R, _T]: ...

    def __get__(
        self, obj: Optional[_T], cls: Optional[type[_T]] = None
    ) -> Union[Self, StateTransitionWrapper[_P, _R, _T]]:
        if obj is None:
            return self
        return StateTransitionWrapper(self, obj)

    def __call__(self, obj: Any, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        """Call transition directly from the class with an instance parameter."""
        return StateTransitionWrapper(self, obj)(*args, **kwargs)


class StateTransitionWrapper(Generic[_P, _R, _T]):
    """
    Wraps :class:`StateTransition` with the context of the object it is accessed from.

    Automatically constructed by :class:`StateTransition`.
    """

    def __init__(self, statetransition: StateTransition[_P, _R], obj: _T) -> None:
        self.statetransition = statetransition
        self.obj = obj

    @property
    def data(self) -> dict[str, Any]:
        """Return data as provided to the :meth:`~StateManager.transition` decorator."""
        return self.statetransition.data

    def _validate_available(
        self,
    ) -> Optional[tuple[StateManager, Any, Any]]:  # TODO: make label `str`
        """
        If the state is invalid for the transition, return details on what didn't match.

        :return: Tuple of (state manager, current state, label for current state)
        """
        for statemanager, conditions in self.statetransition.transitions.items():
            # pylint: disable=protected-access
            current_state_value = statemanager._get_state_value(self.obj)
            if conditions.from_ is None:
                state_valid = True
            else:
                mstate = conditions.from_.get(current_state_value)
                state_valid = mstate is not None and mstate.is_current_in(self.obj)
            if not state_valid:
                return (
                    statemanager,
                    current_state_value,
                    statemanager.lenum.get(current_state_value),
                )
        # No problem found, so state is not invalid
        return None

    @property
    def is_available(self) -> bool:
        """Property that indicates whether this transition is currently available."""
        return not self._validate_available()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.statetransition, name)

    def __call__(self, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        """Perform the state transition."""
        # Validate that each of the state managers is in the correct state
        state_invalid = self._validate_available()
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
            return e.result
        except Exception as e:  # noqa: B902
            transition_exception.send(
                self.obj, transition=self.statetransition, exception=e
            )
            raise

        # Change the state for each of the state managers
        for statemanager, conditions in self.statetransition.transitions.items():
            if conditions.to is not None:  # Allow to=None for the @requires decorator
                statemanager._set_state_value(
                    self.obj, conditions.to.value
                )  # Change state
        # Send a transition-after signal
        transition_after.send(self.obj, transition=self.statetransition)
        return result


class StateManager(Generic[_SG]):
    """
    Provides state management around a database column or property.

    Wraps a property with a :class:`~coaster.utils.classes.LabeledEnum` to
    facilitate state inspection and control state changes.

    This is the main export of this module.

    :param propname: Name of the property that is to be wrapped
    :param lenum: The labeled enum containing valid values
    :param str doc: Optional docstring
    """

    #: Host class for the state manager
    cls: type
    #: All possible states by name
    states: dict[str, Union[ManagedState, ManagedStateGroup]]
    #: All static states, back-referenced by value (group and conditional excluded)
    states_by_value: dict[Any, ManagedState]
    #: All states, static, group or conditional, back-referenced by value
    all_states_by_value: dict[Any, list[Union[ManagedState, ManagedStateGroup]]]
    #: Names of transitions linked to this state manager
    transitions: list[str]

    def __init__(
        self, propname: str, lenum: type[LabeledEnum], doc: Optional[str] = None
    ) -> None:
        self.cls = object  # Depend on __set_name__ to update
        self.propname = propname
        self.name = ''  # Currently unknown name, will only be known in __set_name__
        self.lenum = lenum
        self.__doc__ = doc
        self.states = {}
        self.states_by_value = {}
        self.all_states_by_value = {}
        self.transitions = []

        # Make a copy of all states in the lenum within the state manager as a
        # ManagedState. We do NOT convert grouped states into a ManagedStateGroup
        # instance, as ManagedState is more efficient at testing whether a value is in
        # a group: it uses the `in` operator while ManagedStateGroup does
        # `any(s.is_current_in(obj) for s in states)`.
        for state_name, value in lenum.__names__.items():
            self._add_state_internal(
                state_name,
                value,
                # Grouped states are represented as sets and can't have labels, so be
                # careful about those
                label=lenum[value] if not isinstance(value, (list, set)) else None,
            )

    def __set_name__(self, owner: type[Any], name: str) -> None:
        if self.cls is not object:
            raise TypeError("This StateManager is already affiliated with a host class")
        self.cls = owner
        self.name = name

    def __repr__(self) -> str:
        if self.cls is not None:
            return f'<StateManager {self.cls.__name__}.{self.name}>'
        return f'<StateManager {self.name}>'  # type: ignore[unreachable]

    @overload
    def __get__(self: _SM, obj: None, cls: Optional[type[Any]] = None) -> _SM: ...

    @overload
    def __get__(
        self: _SM, obj: _T, cls: Optional[type[_T]] = None
    ) -> StateManagerInstance[_SM, _T]: ...

    def __get__(
        self: _SM, obj: Optional[_T], cls: Optional[type[_T]] = None
    ) -> Union[_SM, StateManagerInstance[_SM, _T]]:
        if obj is None:
            return self
        # Cache for subsequent accesses to avoid re-constructing the wrapper
        if self.name in obj.__dict__:
            return obj.__dict__[self.name]
        wrapper = StateManagerInstance(self, obj, cls if cls is not None else type(obj))
        obj.__dict__[self.name] = wrapper
        return wrapper

    def __set__(self, obj: Any, value: Any) -> NoReturn:
        raise AttributeError("StateManager cannot be set directly")

    def _set_state_value(self, obj: Any, value: Any) -> None:
        """Set state; internal method called by meth:`StateTransition.__call__`."""
        if value not in self.lenum:
            raise ValueError(f"Not a valid value: {value!r}")

        setattr(obj, self.propname, value)

    def _get_state_value(self, obj: Optional[Any]) -> Any:
        """Get current state value given an instance, or state column in the class."""
        if obj is not None:
            return getattr(obj, self.propname)
        return getattr(self.cls, self.propname)

    def current(self) -> NoReturn:  # skipcq: PYL-R6301
        """Get current state (not available without an instance)."""
        raise TypeError("Current state requires an instance")

    def _add_state_internal(
        self,
        name: str,
        value: Union[int, set[int]],
        label: Optional[Any] = None,  # TODO: Make label `str`
        validator: Optional[Callable[[_SG], bool]] = None,
        class_validator: Optional[Callable[[type[_SG]], sa.ColumnElement[bool]]] = None,
    ) -> None:
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
        )
        # XXX: Since `mstate.statemanager == self`, the following assignments setup
        # looping references and could cause a memory leak if the state manager is ever
        # deleted. We depend on it being permanent for the lifetime of the process in
        # typical use (or for advanced memory management that can detect loops).
        self.states[name] = mstate
        if mstate.is_static:
            self.states_by_value[value] = mstate
        if mstate.is_scalar:
            self.all_states_by_value.setdefault(value, []).insert(0, mstate)
        # Make the ManagedState available as `statemanager.STATE` (assuming original was
        # uppercased)
        setattr(self, name, mstate)

    def add_state_group(
        self, name: str, *states: Union[ManagedState, ManagedStateGroup]
    ) -> None:
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

    def add_conditional_state(
        self,
        name: str,
        state: Union[ManagedState, ManagedStateGroup],
        validator: Callable[[_SG], bool],
        class_validator: Optional[Callable[[type[_SG]], sa.ColumnElement[bool]]] = None,
        label: Optional[Any] = None,  # TODO: Make label `str`
    ) -> None:
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
        :param label: Label for this state (string or 2-tuple)
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
        )

    def transition(
        self,
        from_: Optional[Union[ManagedState, ManagedStateGroup]],
        to: Optional[Union[ManagedState, ManagedStateGroup]],
        **data: Any,
    ) -> Callable[
        [Callable[Concatenate[Any, _P], _R]],
        StateTransition[_P, _R],
    ]:
        """
        Decorate a method to transition from one state to another.

        The decorated method can accept any necessary parameters and perform additional
        processing, or raise an exception to abort the transition. If it returns without
        an error, the state value is updated automatically. Transitions may also abort
        without raising an exception using :exc:`AbortTransition`.

        :param from_: Required state to allow this transition (can be a state group)
        :param to: The state of the object after this transition (automatically set if
            no exception is raised)
        :param data: Additional metadata, stored on the `StateTransition` object as a
            :attr:`data` attribute
        """

        def decorator(
            f: Union[StateTransition, Callable[Concatenate[Any, _P], _R]]
        ) -> StateTransition[_P, _R]:
            if isinstance(f, StateTransition):
                f.add_transition(self, from_, to, data)
                st = f
            else:
                st = StateTransition(f, self, from_, to, data)
            self.transitions.append(st.name)
            return st

        return decorator

    def requires(
        self,
        from_: Union[ManagedState, ManagedStateGroup],
        **data: Any,
    ) -> Callable[[Callable[Concatenate[Any, _P], _R]], StateTransition[_P, _R]]:
        """
        Decorate a method to only be callable when the given state is currently active.

        Registers a transition internally, but does not change the state.

        :param from_: Required state to allow this call (can be a state group)
        :param data: Additional metadata, stored on the `StateTransition` object as a
            :attr:`data` attribute
        """
        return self.transition(from_, None, **data)

    def group(
        self, items: Iterable[_T], keep_empty: bool = False
    ) -> dict[ManagedState, list[_T]]:
        """
        Given an iterable of instances, groups them by state.

        Uses :class:`ManagedState` instances as dictionary keys. Returns a dict that
        preserves the order of states from the source enum.

        :param keep_empty: If ``True``, empty state groups are included in the result
        """
        groups: dict[ManagedState, list[_T]] = {}
        for mstate in self.states_by_value.values():
            # Ensure we sort groups using the order of states in the source LabeledEnum.
            # We'll discard the unused states later.
            groups[mstate] = []
        # Now process the items by state
        for item in items:
            # Use isinstance instead of `type(item) != cls` to account for subclasses
            if not isinstance(item, self.cls):
                raise TypeError(
                    f"Item {item!r} is not an instance of type {self.cls!r}"
                )
            statevalue = self._get_state_value(item)
            mstate = self.states_by_value[statevalue]
            groups[mstate].append(item)  # type: ignore[arg-type]  # Something odd here
        if not keep_empty:
            for key, value in list(groups.items()):
                if not value:
                    del groups[key]
        return groups

    @staticmethod
    def check_constraint(
        column: str,
        enum: Union[type[Enum], type[LabeledEnum]],
        type_: Optional[Union[type[sa.types.TypeEngine], sa.types.TypeEngine]] = None,
        **kwargs: Any,
    ) -> sa.CheckConstraint:
        """
        Construct a SQL CHECK constraint.

        Requires a column name and an :class:`~enum.Enum` or
        :class:`~coaster.utils.classes.LabeledEnum` containing valid values. Usage::

            class MyModel(Model):
                _state: Mapped[int] = sa.orm.mapped_column(
                    'state',
                    sa.Integer,
                    StateManager.check_constraint('state', MY_ENUM, sa.Integer),
                    default=MY_ENUM.DEFAULT
                )
                state = StateManager(_state, MY_ENUM)

        If Alembic does not detect the CHECK constraint when auto-generating migrations,
        you can extract the SQL string using a Python shell::

            from coaster.sqlalchemy import StateManager
            from your_app.models import YOUR_ENUM

            print(
                str(
                    StateManager.check_constraint(
                        'your_column', YOUR_ENUM, sa.Integer  # Or specific column type
                    ).sqltext.compile(compile_kwargs={'literal_binds': True})
                )
            )

        :param column: Column name
        :param enum: :class:`~enum.Enum` or :class:`~coaster.utils.classes.LabeledEnum`
            to retrieve valid values from
        :param type: SQLAlchemy column type to cast values to (required if the values
            are not plain strings or integers)
        :param kwargs: Additional options passed to CheckConstraint
        """
        if issubclass(enum, LabeledEnum):
            values = enum.keys()
        else:
            values = [_member.value for _member in enum]
        return sa.CheckConstraint(sa.Column(column, type_).in_(values))

    if TYPE_CHECKING:
        # Stub for mypy to recognise names added by _add_state_internal. There is a
        # pending proposal for proxy typing: https://github.com/python/typing/issues/802
        def __getattr__(self, name: str) -> Union[ManagedState, ManagedStateGroup]:
            raise AttributeError(name)


class StateManagerInstance(Generic[_SM, _T]):
    """Wraps :class:`StateManager` when accessed from an instance."""

    def __init__(self, statemanager: _SM, obj: _T, cls: type[_T]) -> None:
        self.statemanager = statemanager
        self.obj = obj
        self.cls = cls

    def __repr__(self) -> str:
        return f'<StateManagerInstance {self.cls.__name__}.{self.statemanager.name})>'

    @property
    def value(self) -> Any:
        """Return current state's value from the host object."""
        return getattr(self.obj, self.statemanager.propname)

    @property
    def label(self) -> Any:  # TODO: Make label `str`
        """Label for the current state's value (using :meth:`bestmatch`)."""
        return self.bestmatch().label

    def bestmatch(self) -> ManagedStateInstance:
        """
        Return best matching current scalar state (direct or conditional).

        Only applicable when accessed via an instance.
        """
        for mstate in self.statemanager.all_states_by_value[self.value]:
            msw = ManagedStateInstance(mstate, self.obj)
            if msw:  # If the wrapper evaluates to True, it's our best match
                return msw
        raise RuntimeError("Unknown state value")

    def current(self) -> dict[str, ManagedStateInstance]:
        """Return all states and state groups that are currently active."""
        return {
            name: ManagedStateInstance(mstate, self.obj)
            for name, mstate in self.statemanager.states.items()
            if mstate.is_current_in(self.obj)
        }

    def transitions(self, current: bool = True) -> dict[str, StateTransitionWrapper]:
        """
        Return available transitions for the current state.

        :param bool current: Limit to transitions available in ``obj.``
           :meth:`~coaster.sqlalchemy.mixins.RoleMixin.current_access`
        """
        proxy: Union[dict, RoleAccessProxy]
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
        self,
        roles: Optional[set[str]] = None,
        actor: Optional[Any] = None,
        anchors: Sequence[Any] = (),
    ) -> dict[str, StateTransitionWrapper]:
        """
        Return currently available transitions for the given actor or roles.

        This requires the host object to be derived from
        :class:`~coaster.sqlalchemy.mixins.RoleMixin`.
        """
        # Mypy complains because it can't infer that self.obj is RoleMixin instance.
        if isinstance(self.obj, RoleMixin):
            proxy = self.obj.access_for(roles=roles, actor=actor, anchors=anchors)
            return {
                name: transition
                for name, transition in self.transitions(current=False).items()
                if name in proxy
            }
        raise TypeError("Object is not an instance of RoleMixin")

    def __getattr__(self, name: str) -> ManagedStateInstance[_T]:
        """Retrieve a state."""
        attr = getattr(self.statemanager, name)
        if isinstance(attr, (ManagedState, ManagedStateGroup)):
            return ManagedStateInstance(attr, self.obj)
        return attr

    if TYPE_CHECKING:

        def transition(
            self,
            from_: Optional[Union[ManagedState, ManagedStateGroup]],
            to: Optional[Union[ManagedState, ManagedStateGroup]],
            **data: Any,
        ) -> Callable[
            [Callable[Concatenate[Any, _P], _R]],
            StateTransition[_P, _R],
        ]: ...
