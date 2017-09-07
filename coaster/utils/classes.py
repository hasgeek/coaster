# -*- coding: utf-8 -*-

"""
Classes
-------
"""

from __future__ import absolute_import
import six
from collections import namedtuple, OrderedDict

__all__ = ['NameTitle', 'LabeledEnum']


NameTitle = namedtuple('NameTitle', ['name', 'title'])


class _LabeledEnumMeta(type):
    """Construct labeled enumeration"""
    def __new__(cls, name, bases, attrs):
        labels = {}
        for key, value in tuple(attrs.items()):
            if key != '__order__' and isinstance(value, tuple):
                if len(value) == 2:
                    labels[value[0]] = value[1]
                    attrs[key] = value[0]
                elif len(value) == 3:
                    labels[value[0]] = NameTitle(value[1], value[2])
                    attrs[key] = value[0]

        if '__order__' in attrs:
            sorted_labels = OrderedDict()
            for value in attrs['__order__']:
                sorted_labels[value[0]] = labels.pop(value[0])
            for key, value in sorted(labels.items()):  # Left over items after processing the list in __order__
                sorted_labels[key] = value
        else:
            sorted_labels = OrderedDict(sorted(labels.items()))
        attrs['__labels__'] = sorted_labels
        return type.__new__(cls, name, bases, attrs)

    def __getitem__(cls, key):
        return cls.__labels__[key]

    def __setitem__(cls, key, value):
        raise TypeError('LabeledEnum is immutable')


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

    Retrieve a full list of values and labels with ``.items()``. Items are
    sorted by value regardless of the original definition order since Python
    doesn't provide a way to preserve that order::

        >>> MY_ENUM.items()
        [(1, 'First'), (2, 'Second'), (3, 'Third')]
        >>> MY_ENUM.keys()
        [1, 2, 3]
        >>> MY_ENUM.values()
        ['First', 'Second', 'Third']

    However, if you really want manual sorting, add an __order__ list. Anything not in it will
    be sorted by value as usual::

        >>> class RSVP(LabeledEnum):
        ...     RSVP_Y = ('Y', "Yes")
        ...     RSVP_N = ('N', "No")
        ...     RSVP_M = ('M', "Maybe")
        ...     RSVP_B = ('U', "Unknown")
        ...     RSVP_A = ('A', "Awaiting")
        ...     __order__ = (RSVP_Y, RSVP_N, RSVP_M)

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
