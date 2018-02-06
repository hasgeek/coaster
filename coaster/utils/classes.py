# -*- coding: utf-8 -*-

"""
Classes
-------
"""

from __future__ import absolute_import
import six
from collections import namedtuple, OrderedDict, Set

__all__ = ['NameTitle', 'LabeledEnum', 'InspectableSet']


NameTitle = namedtuple('NameTitle', ['name', 'title'])


class _LabeledEnumMeta(type):
    """Construct labeled enumeration"""
    @classmethod
    def __prepare__(metacls, name, bases, **kwargs):  # pragma: no cover
        return OrderedDict()

    def __new__(cls, name, bases, attrs, **kwargs):
        labels = OrderedDict()
        names = OrderedDict()

        def pop_name_by_value(value):
            for k, v in list(names.items()):
                if v == value:
                    names.pop(k)
                    return k

        for key, value in tuple(attrs.items()):
            if key != '__order__' and isinstance(value, tuple):
                # value = tuple of actual value (0), label/name (1), optional title (2)
                if len(value) == 2:
                    labels[value[0]] = value[1]
                    attrs[key] = names[key] = value[0]
                elif len(value) == 3:
                    labels[value[0]] = NameTitle(value[1], value[2])
                    attrs[key] = names[key] = value[0]
                else:  # pragma: no cover
                    raise AttributeError("Unprocessed attribute %s" % key)
            elif key != '__order__' and isinstance(value, set):
                # value = set of other unprocessed values
                attrs[key] = names[key] = {v[0] if isinstance(v, tuple) else v for v in value}

        if '__order__' in attrs:
            ordered_labels = OrderedDict()
            ordered_names = OrderedDict()
            for value in attrs['__order__']:
                ordered_labels[value[0]] = labels.pop(value[0])
                attr_name = pop_name_by_value(value[0])
                if attr_name is not None:
                    ordered_names[attr_name] = value[0]
            for key, value in labels.items():  # Left over items after processing the list in __order__
                ordered_labels[key] = value
                attr_name = pop_name_by_value(value)
                if attr_name is not None:
                    ordered_names[attr_name] = value
            ordered_names.update(names)  # Left over names that don't have a label
        else:  # This enum doesn't care about ordering, or is using Py3 with __prepare__
            ordered_labels = labels
            ordered_names = names
        attrs['__labels__'] = ordered_labels
        attrs['__names__'] = ordered_names
        return type.__new__(cls, name, bases, attrs)

    def __getitem__(cls, key):
        return cls.__labels__[key]

    def __contains__(cls, key):
        return key in cls.__labels__


class LabeledEnum(six.with_metaclass(_LabeledEnumMeta)):
    """
    Labeled enumerations. Declarate an enumeration with values and labels
    (for use in UI)::

        >>> class MY_ENUM(LabeledEnum):
        ...     FIRST = (1, "First")
        ...     THIRD = (3, "Third")
        ...     SECOND = (2, "Second")

    :class:`LabeledEnum` will convert any attribute that is a 2-tuple into
    a value and label pair. Access values as direct attributes of the enumeration::

        >>> MY_ENUM.FIRST
        1
        >>> MY_ENUM.SECOND
        2
        >>> MY_ENUM.THIRD
        3

    Access labels via dictionary lookup on the enumeration::

        >>> MY_ENUM[MY_ENUM.FIRST]
        'First'
        >>> MY_ENUM[2]
        'Second'
        >>> MY_ENUM.get(3)
        'Third'
        >>> MY_ENUM.get(4) is None
        True

    Retrieve a full list of values and labels with ``.items()``. Definition order is
    preserved in Python 3.x, but not in 2.x::

        >>> sorted(MY_ENUM.items())
        [(1, 'First'), (2, 'Second'), (3, 'Third')]
        >>> sorted(MY_ENUM.keys())
        [1, 2, 3]
        >>> sorted(MY_ENUM.values())
        ['First', 'Second', 'Third']

    However, if you really want ordering in Python 2.x, add an __order__ list.
    Anything not in it will default to Python's ordering::

        >>> class RSVP(LabeledEnum):
        ...     RSVP_Y = ('Y', "Yes")
        ...     RSVP_N = ('N', "No")
        ...     RSVP_M = ('M', "Maybe")
        ...     RSVP_U = ('U', "Unknown")
        ...     RSVP_A = ('A', "Awaiting")
        ...     __order__ = (RSVP_Y, RSVP_N, RSVP_M, RSVP_A)

        >>> RSVP.items()
        [('Y', 'Yes'), ('N', 'No'), ('M', 'Maybe'), ('A', 'Awaiting'), ('U', 'Unknown')]

    Three value tuples are assumed to be (value, name, title) and the name and
    title are converted into NameTitle(name, title)::

        >>> class NAME_ENUM(LabeledEnum):
        ...     FIRST = (1, 'first', "First")
        ...     THIRD = (3, 'third', "Third")
        ...     SECOND = (2, 'second', "Second")

        >>> NAME_ENUM.FIRST
        1
        >>> NAME_ENUM[NAME_ENUM.FIRST]
        NameTitle(name='first', title='First')
        >>> NAME_ENUM[NAME_ENUM.SECOND].name
        'second'
        >>> NAME_ENUM[NAME_ENUM.THIRD].title
        'Third'

    Given a name, the value can be looked up::

        >>> NAME_ENUM.value_for('first')
        1
        >>> NAME_ENUM.value_for('second')
        2

    Values can be grouped together using a set, for performing "in" operations.
    These do not have labels and cannot be accessed via dictionary access::

        >>> class RSVP_EXTRA(LabeledEnum):
        ...     RSVP_Y = ('Y', "Yes")
        ...     RSVP_N = ('N', "No")
        ...     RSVP_M = ('M', "Maybe")
        ...     RSVP_U = ('U', "Unknown")
        ...     RSVP_A = ('A', "Awaiting")
        ...     __order__ = (RSVP_Y, RSVP_N, RSVP_M, RSVP_U, RSVP_A)
        ...     UNCERTAIN = {RSVP_M, RSVP_U, 'A'}

        >>> isinstance(RSVP_EXTRA.UNCERTAIN, set)
        True
        >>> sorted(RSVP_EXTRA.UNCERTAIN)
        ['A', 'M', 'U']
        >>> 'N' in RSVP_EXTRA.UNCERTAIN
        False
        >>> 'M' in RSVP_EXTRA.UNCERTAIN
        True
        >>> RSVP_EXTRA.RSVP_U in RSVP_EXTRA.UNCERTAIN
        True

    Labels are stored internally in a dictionary named ``__labels__``, mapping
    the value to the label. Symbol names are stored in ``__names__``, mapping
    name to the value. The label dictionary will only contain values processed
    using the tuple syntax, which excludes grouped values, while the names
    dictionary will contain both, but will exclude anything else found in the
    class that could not be processed (use ``__dict__`` for everything)::

        >>> list(RSVP_EXTRA.__labels__.keys())
        ['Y', 'N', 'M', 'U', 'A']
        >>> list(RSVP_EXTRA.__names__.keys())
        ['RSVP_Y', 'RSVP_N', 'RSVP_M', 'RSVP_U', 'RSVP_A', 'UNCERTAIN']
    """

    @classmethod
    def get(cls, key, default=None):
        return cls.__labels__.get(key, default)

    @classmethod
    def keys(cls):
        return list(cls.__labels__.keys())

    @classmethod
    def values(cls):
        return list(cls.__labels__.values())

    @classmethod
    def items(cls):
        return list(cls.__labels__.items())

    @classmethod
    def value_for(cls, name):
        for key, value in list(cls.__labels__.items()):
            if isinstance(value, NameTitle) and value.name == name:
                return key


class InspectableSet(Set):
    """
    Given a set, mimics a dictionary where the items are keys and have a value
    of ``True``, and any other key has a value of ``False``. Also supports
    attribute access. Useful in templates to simplify membership inspection::

        >>> myset = InspectableSet({'member', 'other'})
        >>> 'member' in myset
        True
        >>> 'random' in myset
        False
        >>> myset.member
        True
        >>> myset.random
        False
        >>> myset['member']
        True
        >>> myset['random']
        False
    """
    def __init__(self, members):
        if not isinstance(members, set):
            members = set(members)
        object.__setattr__(self, '_members', members)

    def __repr__(self):  # pragma: no cover
        return 'InspectableSet({members})'.format(members=repr(self._members))

    def __len__(self):
        return len(self._members)

    def __contains__(self, key):
        return key in self._members

    def __iter__(self):
        for key in self._members:
            yield key

    def __getitem__(self, key):
        return key in self._members  # Returns True if present, False otherwise

    def __getattr__(self, attr):
        return attr in self._members  # Returns True if present, False otherwise

    def __setattr__(self, attr, value):
        raise AttributeError(attr)
