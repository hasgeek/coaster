# -*- coding: utf-8 -*-

"""
States and transitions
----------------------

:class:`StateManager` wraps a SQLAlchemy column (or any property) with a
:class:`~coaster.utils.classes.LabeledEnum` to facilitate state inspection, and
control state change via transitions. Sample usage::

    class MY_STATE(LabeledEnum):
        DRAFT = (0, "Draft")
        PENDING = (1, 'pending', "Pending")
        PUBLISHED = (2, "Published")

        UNPUBLISHED = {DRAFT, PENDING}


    class MyPost(BaseMixin, db.Model):
        #: The underlying state value column
        _state = db.Column('state', db.Integer, StateManager.check_constraint('state', MY_STATE),
            default=MY_STATE.DRAFT, nullable=False)
        #: The state manager
        state = StateManager('_state', MY_STATE, doc="The post's state")
        #: Datetime for the additional states and transitions
        datetime = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

        #: Additional states:

        #: RECENT = PUBLISHED + in the last one hour
        state.add_conditional_state('RECENT', state.PUBLISHED,
            lambda post: post.datetime > datetime.utcnow() - timedelta(hours=1))
        #: REDRAFTABLE = DRAFT or PENDING or RECENT
        state.add_state_group('REDRAFTABLE', state.DRAFT, state.PENDING, state.RECENT)

        #: Transitions to change from one state to another:

        @state.transition(state.DRAFT, state.PENDING)
        def submit(self):
            pass

        @state.transition(state.UNPUBLISHED, state.PUBLISHED)
        def publish(self):
            self.datetime = datetime.utcnow()

        @state.transition(state.RECENT, state.PENDING)
        def undo(self):
            pass

        @state.transition(state.REDRAFTABLE, state.DRAFT)
        def redraft(self):
            pass


Defining states and transitions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Adding a :class:`StateManager` to the class links the underlying column
(specified as a string) to the :class:`~coaster.utils.classes.LabeledEnum`
(specified as an object). The StateManager is read-only unless it receives
``readonly=False`` as a parameter. The LabeledEnum is not required after
this point. All symbol names in it are available as attributes on the state
manager henceforth (as instances of :class:`ManagedState`).

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

Transitions connect one managed state or group to another state (but not
group). Transitions are defined as methods and decorated with
:meth:`~StateManager.transition`, which transforms them into instances of
:class:`StateTransition`, a callable class. If the transition raises an
exception, the state change is aborted. Transitions have two additional
attributes, :attr:`~_StateTransitionWrapper.is_available`, a boolean property
which indicates if the transition is currently available, and
:attr:`~StateTransition.data`, a dictionary that contains all additional
parameters passed to the @transition decorator.


Queries
~~~~~~~

The current state of the object can be retrieved by calling the state
attribute or reading its ``value`` attribute::

    post = MyPost(state=MY_STATE.DRAFT)
    post.state() == MY_STATE.DRAFT
    post.state.value == MY_STATE.DRAFT

The label associated with the state value can be accessed from the ``label`` attribute::

    post.state.label == "Draft"          # This is the string label from MY_STATE.DRAFT
    post.submit()                        # Change state from DRAFT to PENDING
    post.state.label.name == 'pending'   # Ths is the NameTitle tuple from MY_STATE.PENDING
    post.state.label.title == "Pending"  # The title part of NameTitle

States can be tested by direct reference using their names from the
LabeledEnum::

    post.state.DRAFT        # True
    post.state.is_draft     # True (is_* attrs are uppercased before retrieval from the LabeledEnum)
    post.state.PENDING      # False (since it's a draft)
    post.state.UNPUBLISHED  # True (grouped state values work as expected)
    post.publish()          # Change state from DRAFT to PUBLISHED
    post.state.RECENT       # True (this one calls the validator if the base state matches)

States can also be used for database queries when accessed from the class::

    # Generates MyPost._state == MY_STATE.DRAFT
    MyPost.query.filter(MyPost.state.DRAFT)

    # Generates MyPost._state.in_(MY_STATE.UNPUBLISHED)
    MyPost.query.filter(MyPost.state.UNPUBLISHED)

    # Generates and_(MyPost._state == MY_STATE.PUBLISHED, MyPost.datetime > datetime.utcnow() - timedelta(hours=1))
    MyPost.query.filter(MyPost.state.RECENT)

This works because :class:`StateManager` and :class:`ManagedState`
behave in three different ways, depending on context:

1. During class definition, the state manager returns the managed state. All
   methods on the state manager recognise these managed states and handle them
   appropriately.

2. After class definition, the state manager returns the result of calling the
   managed state instance. If accessed via the class, the managed state returns
   a SQLAlchemy filter condition.

3. If accessed via an instance, the managed state tests if it is
   currently active and returns a boolean result.

States can be set by directly changing the attribute, but only if declared
with ``readonly=False``::

    post.state = MY_STATE.PENDING
    post.state = 'some_invalid_value'  # This will raise a StateChangeError

State change via the :meth:`~StateManager.transition` decorator
adds more power:

1. Original and final states can be specified, prohibiting arbitrary state
   changes.
2. The transition method can do additional validation and housekeeping.
3. Combined with the :func:`~coaster.sqlalchemy.roles.with_roles` decorator
   and :class:`~coaster.sqlalchemy.roles.RoleMixin`, it provides
   access control for state changes.

A mechanism by which StateManager and RoleMixin can be combined to determine
currently available transitions is pending.
"""

__all__ = ['StateManager', 'StateTransitionError', 'StateChangeError', 'StateReadonlyError',
    'transition_error', 'transition_before', 'transition_after', 'transition_exception']

import functools
from sqlalchemy import and_, or_, column as column_constructor, CheckConstraint
from ..signals import coaster_signals

_marker = ()  # Used by __getattr__
iterables = (set, frozenset, list, tuple)  # Used for various isinstance checks


# --- Signals -----------------------------------------------------------------

transition_error = coaster_signals.signal('transition-error',
    doc="Signal raised when a transition fails validation")

transition_before = coaster_signals.signal('transition-before',
    doc="Signal raised before a transition (after validation)")

transition_after = coaster_signals.signal('transition-after',
    doc="Signal raised after a successful transition")

transition_exception = coaster_signals.signal('transition-exception',
    doc="Signal raised when a transition raises an exception")


# --- Exceptions --------------------------------------------------------------

class StateTransitionError(TypeError):
    """Raised if a transition is attempted from a non-matching state"""
    pass


class StateChangeError(ValueError):
    """Raised if the state is changed to a value not present in the LabeledEnum"""
    pass


class StateReadonlyError(AttributeError):
    """Raised if the StateManager is read-only and a direct state value change was attempted"""
    pass


# --- Classes -----------------------------------------------------------------

class ManagedState(object):
    """
    Represents a state managed by a StateManager.
    """
    def __init__(self, name, statemanager, value, label=None,
            validator=None, class_validator=None, cache_for=None):
        self.name = name
        self.statemanager = statemanager
        self.value = value
        self.label = label
        self.validator = validator
        self.class_validator = class_validator
        self.cache_for = cache_for

    def __repr__(self):
        return "%s.%s" % (self.statemanager.name, self.name)

    def __call__(self, obj, cls=None):
        if obj is not None:  # We're being called with an instance
            if isinstance(self.value, iterables):
                valuematch = self.statemanager(obj, cls) in self.value
            else:
                valuematch = self.statemanager(obj, cls) == self.value
            if self.validator is not None:
                return valuematch and self.validator(obj)
            else:
                return valuematch
        else:  # We have a class, so return a filter condition, for use as cls.query.filter(result)
            if isinstance(self.value, iterables):
                valuematch = self.statemanager(obj, cls).in_(self.value)
            else:
                valuematch = self.statemanager(obj, cls) == self.value
            cv = self.class_validator
            if cv is None:
                cv = self.validator
            if cv is not None:
                return and_(valuematch, cv(cls))
            else:
                return valuematch


class ManagedStateGroup(object):
    def __init__(self, name, statemanager, states):
        self.name = name
        self.statemanager = statemanager
        self.states = []
        values = []
        for state in states:
            if not isinstance(state, ManagedState) or state.statemanager != statemanager:
                raise ValueError("Invalid state %s for state group %s" (repr(state), repr(self)))
            # Prevent grouping of conditional states with their original states
            if state.value in values:
                raise ValueError("The value for state %s is already in this state group" % repr(state))
            self.states.append(state)
            values.append(state.value)

    def __repr__(self):
        return "%s.%s" % (self.statemanager.name, self.name)

    def __call__(self, obj, cls=None):
        if obj is not None:  # We're being called with an instance
            return any(s(obj, cls) for s in self.states)
        else:
            return or_(*[s(obj, cls) for s in self.states])


class StateTransition(object):
    """
    Helper for transitions from one state to another. Do not use this class
    directly. Use the :meth:`StateManager.transition` decorator instead, which
    creates instances of this class.

    To access the decorated function with ``help()``, use ``help(obj.func)``.
    """
    def __init__(self, func, statemanager, from_, to, if_=None, data=None):
        self.func = func
        functools.update_wrapper(self, func)
        self.name = func.__name__

        # Repeated use of @StateManager.transition will add to this dictionary
        # by calling add_transition directly
        self.transitions = {}
        # Repeated use of @StateManager.transition will update this dictionary
        self.data = {}
        self.add_transition(statemanager, from_, to, if_, data)

    def add_transition(self, statemanager, from_, to, if_=None, data=None):
        if statemanager in self.transitions:
            raise StateTransitionError("Duplicate transition decorator")
        if from_ is not None and not isinstance(from_, (ManagedState, ManagedStateGroup)):
            raise StateTransitionError("From state is not a managed state: %s" % repr(from_))
        if not isinstance(to, ManagedState):
            raise StateTransitionError("To state is not a managed state: %s" % repr(to))
        elif to.value not in statemanager.lenum:
            raise StateTransitionError("To state is not a valid state value: %s" % repr(to))
        if data:
            self.data.update(data)

        if if_ is None:
            if_ = []
        elif callable(if_):
            if_ = [if_]

        if from_ is None:
            state_values = None
        else:
            # Unroll grouped values so we can do a quick IN test when performing the transition
            state_values = {}  # Value: ManagedState
            # Step 1: Convert ManagedStateGroup into a list of ManagedState items
            if isinstance(from_, ManagedStateGroup):
                from_ = from_.states
            else:  # ManagedState
                from_ = [from_]
            # Step 2: Unroll grouped values from the original LabeledEnum
            for mstate in from_:
                if isinstance(mstate.value, iterables):
                    for value in mstate.value:
                        state_values[value] = mstate
                else:
                    state_values[mstate.value] = mstate

        self.transitions[statemanager] = {
            'from': state_values,  # Just the valuesScalar values (no validation functions)
            'to': to,              # Scalar value of new state
            'if': if_,             # Additional conditions that must ALL pass
            }

    # Make the transition a non-data descriptor
    def __get__(self, obj, cls=None):
        if obj is None:
            return self
        else:
            return _StateTransitionWrapper(self, obj)


class _StateTransitionWrapper(object):
    def __init__(self, st, obj):
        self.st = st
        self.obj = obj

    @property
    def data(self):
        """
        Transition descriptive data
        """
        return self.st.data

    def _state_invalid(self):
        """
        If the state is invalid for the transition, return details on what didn't match

        :return: Tuple of (state manager, current state, label for current state)
        """
        for statemanager, conditions in self.st.transitions.items():
            current_state = getattr(self.obj, statemanager.propname)
            if conditions['from'] is None:
                state_valid = True
            else:
                mstate = conditions['from'].get(current_state)
                state_valid = mstate and mstate(self.obj)
            if state_valid and conditions['if']:
                state_valid = all(v(self.obj) for v in conditions['if'])
            if not state_valid:
                return statemanager, current_state, statemanager.lenum.get(current_state)

    @property
    def is_available(self):
        """
        Indicates whether this transition is currently available.
        """
        return not self._state_invalid()

    def __call__(self, *args, **kwargs):
        """Call the transition"""
        # Validate that each of the state managers is in the correct state
        state_invalid = self._state_invalid()
        if state_invalid:
            transition_error.send(self.obj, transition=self.st, statemanager=state_invalid[0])
            raise StateTransitionError(
                u"Invalid state for transition {transition}: {state} = {value} ({label})".format(
                    transition=self.st.name,
                    state=repr(state_invalid[0]),
                    value=repr(state_invalid[1]),
                    label=repr(state_invalid[2])
                    ))

        # Raise a transition-before signal
        transition_before.send(self.obj, transition=self.st)
        # Call the transition function
        try:
            result = self.st.func(self.obj, *args, **kwargs)
        except Exception as e:
            transition_exception.send(self.obj, transition=self.st, exception=e)
            raise
        # Change the state for each of the state managers
        for statemanager, conditions in self.st.transitions.items():
            statemanager._set(self.obj, conditions['to'].value, force=True)  # Change state
        # Raise a transition-after signal
        transition_after.send(self.obj, transition=self.st)
        return result


class StateManager(object):
    """
    Wraps a property with a :class:`~coaster.utils.classes.LabeledEnum` to
    facilitate state inspection and control state changes.

    :param str propname: Name of the property that is to be wrapped
    :param LabeledEnum lenum: The LabeledEnum containing valid values
    :param bool readonly: If False, allows write access to the state (default True)
    :param str doc: Optional docstring
    """
    def __init__(self, propname, lenum, readonly=True, doc=None):
        self.propname = propname
        self.name = propname  # Incorrect, so we depend on __set_name__ to correct this
        self.lenum = lenum
        self.readonly = readonly
        self.__doc__ = doc
        self.states = {}  # name: ManagedState
        self.transitions = []  # names of transitions linked to this state manager

        # Make a copy of all states in the lenum within the state manager as a ManagedState.
        for state_name, value in lenum.__names__.items():
            self._add_state_internal(state_name, value,
                # Grouped states are represented as sets and can't have labels, so be careful about those
                label=lenum[value] if not isinstance(value, (list, set)) else None)

    def __set_name__(self, owner, name):  # Python 3.6+
        self.name = name

    def __get__(self, obj, cls=None):
        return _StateManagerWrapper(self, obj, cls)

    def __set__(self, obj, value):
        self._set(obj, value)

    # Since __get__ never returns self, the following methods will only be available
    # within the owning class's namespace. It will not be possible to call them outside
    # the class to add conditional states or transitions. If a use case arises,
    # add wrapper methods to _StateManagerWrapper.

    def _set(self, obj, value, force=False):
        """Internal method to set state, called by :meth:`__set__` and meth:`StateTransition.__call__`"""
        if value not in self.lenum:
            raise StateChangeError("Not a valid value: %s" % value)

        if self.readonly and not force:
            raise StateReadonlyError("This state is read-only")

        type(obj).__dict__[self.propname].__set__(obj, value)

    def _add_state_internal(self, name, value, label=None,
            validator=None, class_validator=None, cache_for=None):
        # Also see `add_state_group` for similar code
        if hasattr(self, name):  # Don't clobber self with a state name
            raise AttributeError(
                "State name %s conflicts with existing attribute in the state manager" % name)
        mstate = ManagedState(name=name, statemanager=self, value=value, label=label,
            validator=validator, class_validator=class_validator, cache_for=cache_for)
        # XXX: Since mstate.statemanager == self, the following assignments setup looping
        # references and could cause a memory leak if the statemanager is ever deleted. We
        # depend on it being permanent for the lifetime of the process in typical use (or
        # for advanced memory management that can detect loops).
        self.states[name] = mstate
        # Make the ManagedState available as `statemanager.STATE` (assuming original was uppercased)
        setattr(self, name, mstate)
        setattr(self, 'is_' + name.lower(), mstate)  # Also make available as `statemanager.is_state`

    def add_state_group(self, name, *states):
        """
        Add a group of states (including conditional states)
        """
        # See `_add_state_internal` for explanation of the following
        if hasattr(self, name):
            raise AttributeError(
                "State group name %s conflicts with existing attribute in the state manager" % name)
        mstate = ManagedStateGroup(name, self, states)
        self.states[name] = mstate
        setattr(self, name, mstate)
        setattr(self, 'is_' + name.lower(), mstate)

    def add_conditional_state(self, name, state, validator, class_validator=None, cache_for=None):
        """
        Add a conditional state that combines an existing state with a validator
        that must also pass. The validator receives the object on which the property
        is present as a parameter.

        :param str name: Name of the new state
        :param ManagedState state: Existing state that this is based on
        :param validator: Function that will be called with the host object as a parameter
        :param class_validator: Function that will be called when the state is queried
            on the class instead of the instance. Falls back to ``validator`` if not specified
        :param cache_for: Integer or function that indicates the number of seconds for which
            ``validator``'s result can be cached (not applicable to ``class_validator``)
        """
        if name in self.lenum.__dict__ or name in self.states:
            raise AttributeError("State %s already exists" % name)
        if not isinstance(state, ManagedState):
            raise ValueError("Invalid state: %s" % repr(state))
        elif state.statemanager != self:
            raise ValueError("State %s is not associated with this state manager" % repr(state))
        self._add_state_internal(name, state.value,
            validator=validator, class_validator=class_validator, cache_for=cache_for)

    def transition(self, from_, to, if_=None, **data):
        """
        Decorates a function to transition from one state to another. The
        decorated function can accept any necessary parameters and perform
        additional processing, or raise an exception to abort the transition.
        If it returns without an error, the state value is updated
        automatically.

        :param from_: Required original state to allow this transition (can be a group of states)
        :param to: The state of the object after this transition (automatically set if no exception is raised)
        :param if_: Validator(s) that, given the object, must all return True for the transition to proceed
        :param metadata: Additional metadata, stored on the StateTransition object
        """
        def decorator(f):
            if isinstance(f, StateTransition):
                f.add_transition(self, from_, to, if_, data)
                return f
            else:
                st = StateTransition(f, self, from_, to, if_, data)
                self.transitions.append(st.name)
                return st

        return decorator

    def __call__(self, obj, cls=None):
        """The state value (called from the wrapper)"""
        if obj is not None:
            return getattr(obj, self.propname)
        else:
            return getattr(cls, self.propname)

    @staticmethod
    def check_constraint(column, lenum, **kwargs):
        """
        Returns a SQL CHECK constraint string given a column name and a LabeledEnum

        :param str column: Column name
        :param LabeledEnum lenum: LabeledEnum to retrieve valid values from
        :param kwargs: Additional options passed to CheckConstraint
        """
        return CheckConstraint(
            str(column_constructor(column).in_(lenum.keys()).compile(compile_kwargs={"literal_binds": True})),
            **kwargs)


class _StateManagerWrapper(object):
    """Wraps StateManager with the context of the containing object"""

    def __init__(self, statemanager, obj, cls):
        self.statemanager = statemanager  # StateManager
        self.obj = obj  # Instance we're being called on, None if called on the class instead
        self.cls = cls  # The class of the instance we're being called on

    def __call__(self):
        """The state value"""
        return self.statemanager(self.obj, self.cls)

    value = property(__call__)

    @property
    def label(self):
        """Label for this state value"""
        return self.statemanager.lenum[self()]

    @property
    def transitions(self):
        """
        Returns currently available transitions as a dictionary of name: StateTransition
        """
        # Retrieve transitions from the instance object to activate the descriptor.
        return {name: transition for name, transition in
            ((name, getattr(self.obj, name)) for name in self.statemanager.transitions)
            if transition.is_available}

    def __getattr__(self, attr, default=_marker):
        """
        Given the name of a state, returns:

        1. If called on an instance, a boolean indicating if the state is active
        2. If called on a class, a query filter

        Returns the default value or raises :exc:`AttributeError` on anything else.
        """
        if hasattr(self.statemanager, attr):
            mstate = getattr(self.statemanager, attr)
            if isinstance(mstate, (ManagedState, ManagedStateGroup)):
                return mstate(self.obj, self.cls)
        if default is not _marker:
            return default
        raise AttributeError("Not a state: %s" % attr)
