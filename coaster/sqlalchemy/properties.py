# -*- coding: utf-8 -*-

"""
SQLAlchemy properties
---------------------
"""

__all__ = ['StateProperty']

from functools import wraps


class StateProperty(object):
    """
    Wraps a property with a :class:`~coaster.utils.classes.LabeledEnum` to
    facilitate state inspection and control state changes. Sample usage::

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
                self.datetime = datetime.utcnow()

    The current state of the object can now be retrieved by calling the state attribute
    or reading its ``value`` attribute::

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
        post.state.publish()    # Change state from DRAFT to PUBLISHED
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

    States can be set by directly changing the attribute::

        post.state = MY_STATE.PENDING
        post.state = 'some_invalid_value'  # This will raise a ValueError

    However, state change via the @transition decorator adds more power:

    1. Original and final states can be specified, prohibiting a transition from any other state.
    2. The transition method can do additional validation and housekeeping.

    :param str propname: Name of the property that is to be wrapped
    :param LabeledEnum lenum: The LabeledEnum containing valid values
    :param str doc: Optional docstring
    """
    def __init__(self, propname, lenum, doc=None):
        self.propname = propname
        self.lenum = lenum
        self.__doc__ = doc
        self.states = {}

    def __get__(self, obj, cls=None):
        return _StatePropertyWrapper(self, obj, cls)

    def __set__(self, obj, value):
        if value not in self.lenum:
            raise ValueError("Not a valid value: %s" % value)

        type(obj).__dict__[self.propname].__set__(obj, value)

    # Since __get__ never returns self, the following methods will only be available
    # within the owning class's namespace. It will not be possible to call them outside
    # the class to add additional states or transitions. If you really must do that,
    # use cls.__dict__['state_property'].add_state, etc.

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
        self.states[name] = (value, validator, class_validator)

    def transition(self, from_, to):
        """
        Decorator to transition from one state to another.

        :param from_: Required original state to allow this transition (can be a group of states)
        :param to: The state of the object after this transition (automatically set if no exception is raised)
        """
        def decorator(f):
            @wraps(f)
            def inner(obj, *args, **kwargs):
                current_state = type(obj).__dict__[self.propname].__get__(obj, type(obj))
                if isinstance(from_, (set, frozenset, list, tuple)):
                    test = current_state in from_
                else:
                    test = current_state == from_
                if not test:
                    raise ValueError("Invalid state for transition %s: %s" % (f.__name__, self.lenum[current_state]))
                result = f(obj, *args, **kwargs)
                self.__set__(obj, to)  # Change state
                return result
            return inner
        return decorator


class _StatePropertyWrapper(object):
    def __init__(self, stateprop, obj, cls):
        self.stateprop = stateprop  # StateProperty
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

        if attr in self.stateprop.states:
            value, validator, class_validator = self.stateprop.states[attr]
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
