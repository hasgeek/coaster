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
        _state = db.Column('state', db.Integer, default=MY_STATE.DRAFT, nullable=False)
        #: The state property
        state = StateManager('_state', MY_STATE, doc="The post's state")
        #: Datetime for the additional states and transitions
        datetime = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

        #: Additional states:

        #: RECENT = PUBLISHED + in the last one hour
        state.add_state('RECENT', MY_STATE.PUBLISHED,
            lambda post: post.datetime > datetime.utcnow() - timedelta(hours=1))

        #: Transitions to change from one state to another:

        submit = state.add_transition('submit', MY_STATE.DRAFT, MY_STATE.PENDING)

        @state.transition(MY_STATE.UNPUBLISHED, MY_STATE.PUBLISHED)
        def publish(self):
            self.datetime = datetime.utcnow()

        undo = state.add_transition('undo', state.added.RECENT, MY_STATE.PENDING)

        redraft = state.add_transition('redraft',
            [MY_STATE.DRAFT, MY_STATE.PENDING, state.added.RECENT],
            MY_STATE.DRAFT)


Defining states and transitions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Adding a :class:`StateManager` to the class links the underlying column
(specified as a string) to the :class:`~coaster.utils.classes.LabeledEnum`
(specified as an object). The StateManager is read-only unless it receives
``readonly=False`` as a parameter.

Additional states can be defined with :meth:`~StateManager.add_state` as a
combination of an existing state value and a validator that receives the object
(the instance of the class the StateManager is present on). This can be used
to evaluate for additional conditions to confirm the added state. For example,
to distinguish between a static "published" state and a dynamic "recently
published" state. Added states are available during the class definition
process as attributes of the ``added`` attribute, as in the ``undo`` transition
in the example above. :meth:`~StateManager.add_state` also takes an optional
``class_validator`` parameter that is used for queries against the class (see
below for query examples).

Transitions connect one or more states to another. Transitions are methods
on the instance that must be called for the state to change. Transitions
can be defined by using the :meth:`~StateManager.transition` decorator on an
existing method, or with :meth:`~StateManager.add_transition` if no additional
processing is required. If the transition method raises an exception, the state
change is aborted. Transitions can be defined from added states as in the
``undo`` and ``redraft`` examples above.


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

States can be tested by direct reference using their names from the LabeledEnum::

    post.state.DRAFT        # True
    post.state.is_draft     # True (is_* attrs are uppercased before retrieval from the LabeledEnum)
    post.state.PENDING      # False (since it's a draft)
    post.state.UNPUBLISHED  # True (grouped state values work as expected)
    post.publish()          # Change state from DRAFT to PUBLISHED
    post.state.RECENT       # True (this one calls the validator if the base state matches)

States can also be used for database queries when accessed from the class::

    # Generates MyPost._state == MY_STATE.DRAFT
    MyPost.query.filter(*MyPost.state.DRAFT)

    # Generates MyPost._state.in_(MY_STATE.UNPUBLISHED)
    MyPost.query.filter(*MyPost.state.UNPUBLISHED)

    # Generates MyPost._state == MY_STATE.PUBLISHED, MyPost.datetime > datetime.utcnow() - timedelta(hours=1))
    MyPost.query.filter(*MyPost.state.RECENT)

Since added states with a validator have more than one condition that must match,
the class-level property returns a tuple of filter conditions.

States can be set by directly changing the attribute, but only if declared
with ``readonly=False``::

    post.state = MY_STATE.PENDING
    post.state = 'some_invalid_value'  # This will raise a StateChangeError

State change via :meth:`~StateManager.transition` or
:meth:`~StateManager.add_transition` adds more power:

1. Original and final states can be specified, prohibiting arbitrary state
   changes.
2. The transition method can do additional validation and housekeeping.
3. Combined with the :func:`~coaster.sqlalchemy.roles.with_roles` decorator
   and :class:`~coaster.sqlalchemy.roles.RoleMixin`, it provides
   access control for state changes.

A mechanism by which StateManager and RoleMixin can be combined to determine
currently available transitions is pending.
"""

__all__ = ['StateManager', 'StateTransitionError', 'StateChangeError', 'StateReadonlyError']

from functools import wraps
from collections import namedtuple
from ..utils import AttributeDict


class StateTransitionError(TypeError):
    """Raised if a transition is attempted from a non-matching state"""
    pass


class StateChangeError(ValueError):
    """Raised if the state is changed to a value not present in the LabeledEnum"""
    pass


class StateReadonlyError(AttributeError):
    """Raised if the StateManager is read-only and a direct state value change was attempted"""
    pass


AddedState = namedtuple('AddedState', ['value', 'validator', 'class_validator'])


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
        self.lenum = lenum
        self.readonly = readonly
        self.__doc__ = doc
        self.added = AttributeDict()  # name: AddedState
        self.transitions = {}  # name: (from_, to, func)

    def __get__(self, obj, cls=None):
        return _StateManagerWrapper(self, obj, cls)

    def __set(self, obj, value, force=False):
        """Internal method to set state, called by :meth:`__set__` and meth:`transition`"""
        if value not in self.lenum:
            raise StateChangeError("Not a valid value: %s" % value)

        if self.readonly and not force:
            raise StateReadonlyError("This state is read-only")

        type(obj).__dict__[self.propname].__set__(obj, value)

    def __set__(self, obj, value):
        self.__set(obj, value)

    # Since __get__ never returns self, the following methods will only be available
    # within the owning class's namespace. It will not be possible to call them outside
    # the class to add additional states or transitions. If a use case arises,
    # add wrapper methods to _StateManagerWrapper.

    def add_state(self, name, value, validator, class_validator=None):
        """
        Add an additional state that combines an existing state with a validator
        that must also pass. The validator receives the object on which the property
        is present as a parameter.

        :param str name: Name of the new state
        :param value: Value or group of values of an existing state
        :param validator: Function that will be called with the host object as a parameter
        :param class_validator: Function that will be called when the state is queried
            on the class instead of the instance. Falls back to ``validator`` if not specified
        """
        if name in self.lenum.__dict__:
            raise AttributeError("State %s already exists" % name)
        self.added[name] = AddedState(value, validator, class_validator)

    def transition(self, from_, to, name=None):
        """
        Decorates a function to transition from one state to another. The
        decorated function can accept any necessary parameters and perform
        additional processing, or raise an exception to abort the transition.
        If it returns without an error, the state value is updated
        automatically.

        :param from_: Required original state to allow this transition (can be a group of states)
        :param to: The state of the object after this transition (automatically set if no exception is raised)
        :param name: Name of this transition (automatically guessed from the wrapped function's name)
        """
        if to not in self.lenum:
            raise StateTransitionError("Invalid transition `to` state: %s" % to)

        # Evaluate `from_` and decide how to compare with it
        if isinstance(from_, AddedState):
            added_states = {from_.value: from_}
            regular_states = []
        elif isinstance(from_, (set, frozenset, list, tuple)):
            added_states = {stateval.value: stateval for stateval in from_ if isinstance(stateval, AddedState)}
            regular_states = [stateval for stateval in from_ if not isinstance(stateval, AddedState)]
        else:
            added_states = {}
            regular_states = [from_]

        def decorator(f):
            transition_name = name or f.__name__

            @wraps(f if f is not None else lambda: None)
            def inner(obj, *args, **kwargs):
                current_state = type(obj).__dict__[self.propname].__get__(obj, type(obj))
                state_valid = (current_state in regular_states) or (
                    current_state in added_states and added_states[current_state].validator(obj))
                if not state_valid:
                    raise StateTransitionError(
                        "Invalid state for transition %s: %s" % (transition_name, self.lenum[current_state]))
                result = f(obj, *args, **kwargs) if f is not None else None
                self.__set(obj, to, force=True)  # Change state
                return result
            self.transitions[transition_name] = (from_, to, inner)
            return inner
        return decorator

    def add_transition(self, name, from_, to):
        """
        Add a transition between states, with no wrapped function. See :meth:`transition` for details.
        """
        return self.transition(from_, to, name)(None)


class _StateManagerWrapper(object):
    """Wraps StateManager with the context of the containing object"""

    def __init__(self, stateprop, obj, cls):
        self.stateprop = stateprop  # StateManager
        self.obj = obj  # Instance we're being called on, None if called on the class instead
        self.cls = cls  # The class of the instance we're being called on

    def __call__(self):
        """The state value"""
        return self.cls.__dict__[self.stateprop.propname].__get__(self.obj, self.cls)

    value = property(__call__)

    @property
    def label(self):
        """Label for this state value"""
        return self.stateprop.lenum[self()]

    def __getattr__(self, attr):
        if attr.startswith('is_'):
            attr = attr[3:].upper()  # Support casting `is_draft` to `DRAFT`

        if attr in self.stateprop.added:
            value, validator, class_validator = self.stateprop.added[attr]
        else:
            value = getattr(self.stateprop.lenum, attr)  # Get value for this state attr from the LabeledEnum
            validator = class_validator = None

        if self.obj is not None:  # We're in an instance
            if isinstance(value, (set, frozenset, list, tuple)):
                valuematch = self() in value
            else:
                valuematch = self() == value
            if validator is not None:
                return valuematch and validator(self.obj)
            else:
                return valuematch
        else:  # We're in a class, so return a tuple of queries, for use as cls.query.filter(*result)
            if isinstance(value, (set, frozenset, list, tuple)):
                valuematch = self().in_(value)
            else:
                valuematch = self() == value
            if class_validator is None:
                class_validator = validator
            if class_validator is not None:
                return (valuematch, class_validator(self.cls))
            else:
                return (valuematch,)
