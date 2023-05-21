"""
Utility classes
---------------
"""

from __future__ import annotations

from collections import namedtuple
import typing as t
import warnings

import typing_extensions as te

__all__ = ['NameTitle', 'LabeledEnum', 'InspectableSet', 'classmethodproperty']

NameTitle = namedtuple('NameTitle', ['name', 'title'])


class _LabeledEnumMeta(type):
    """Construct labeled enumeration."""

    def __new__(
        cls: t.Type,
        name: str,
        bases: t.Tuple[t.Type, ...],
        attrs: t.Dict[str, t.Any],
        **kwargs: t.Any,
    ) -> t.Type[LabeledEnum]:
        labels: t.Dict[str, t.Any] = {}
        names: t.Dict[str, t.Any] = {}

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
                    raise AttributeError(f"Unprocessed attribute {key}")
            elif key != '__order__' and isinstance(value, set):
                # value = set of other unprocessed values
                attrs[key] = names[key] = {
                    v[0] if isinstance(v, tuple) else v for v in value
                }

        if '__order__' in attrs:
            warnings.warn(
                "LabeledEnum.__order__ is obsolete in Python >= 3.6", stacklevel=2
            )

        attrs['__labels__'] = labels
        attrs['__names__'] = names
        return type.__new__(cls, name, bases, attrs)

    def __getitem__(cls, key: t.Union[str, tuple]) -> t.Any:
        return cls.__labels__[key]  # type: ignore[attr-defined]

    def __contains__(cls, key: t.Union[str, tuple]) -> bool:
        return key in cls.__labels__  # type: ignore[attr-defined]


class LabeledEnum(metaclass=_LabeledEnumMeta):
    """
    Labeled enumerations.

    Declarate an enumeration with values and labels (for use in UI)::

        >>> class MY_ENUM(LabeledEnum):
        ...     FIRST = (1, "First")
        ...     THIRD = (3, "Third")
        ...     SECOND = (2, "Second")

    :class:`LabeledEnum` will convert any attribute that is a 2-tuple into a value and
    label pair. Access values as direct attributes of the enumeration::

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
    preserved::

        >>> MY_ENUM.items()
        [(1, 'First'), (3, 'Third'), (2, 'Second')]
        >>> MY_ENUM.keys()
        [1, 3, 2]
        >>> MY_ENUM.values()
        ['First', 'Third', 'Second']

    Three value tuples are assumed to be (value, name, title) and the name and title are
    converted into NameTitle(name, title)::

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

    To make it easier to use with forms and to hide the actual values, a list of (name,
    title) pairs is available::

        >>> [tuple(x) for x in NAME_ENUM.nametitles()]
        [('first', 'First'), ('third', 'Third'), ('second', 'Second')]

    Given a name, the value can be looked up::

        >>> NAME_ENUM.value_for('first')
        1
        >>> NAME_ENUM.value_for('second')
        2

    Values can be grouped together using a set, for performing "in" operations. These do
    not have labels and cannot be accessed via dictionary access::

        >>> class RSVP_EXTRA(LabeledEnum):
        ...     RSVP_Y = ('Y', "Yes")
        ...     RSVP_N = ('N', "No")
        ...     RSVP_M = ('M', "Maybe")
        ...     RSVP_U = ('U', "Unknown")
        ...     RSVP_A = ('A', "Awaiting")
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

    Labels are stored internally in a dictionary named ``__labels__``, mapping the value
    to the label. Symbol names are stored in ``__names__``, mapping name to the value.
    The label dictionary will only contain values processed using the tuple syntax,
    which excludes grouped values, while the names dictionary will contain both, but
    will exclude anything else found in the class that could not be processed (use
    ``__dict__`` for everything)::

        >>> list(RSVP_EXTRA.__labels__.keys())
        ['Y', 'N', 'M', 'U', 'A']
        >>> list(RSVP_EXTRA.__names__.keys())
        ['RSVP_Y', 'RSVP_N', 'RSVP_M', 'RSVP_U', 'RSVP_A', 'UNCERTAIN']
    """

    __labels__: t.ClassVar[t.Dict[t.Any, t.Any]]
    __names__: t.ClassVar[t.Dict[str, t.Any]]

    @classmethod
    def get(cls, key: str, default: t.Optional[t.Any] = None) -> t.Any:
        """Get the label for an enum value."""
        return cls.__labels__.get(key, default)

    @classmethod
    def keys(cls) -> t.List[t.Any]:
        """Get all enum values."""
        return list(cls.__labels__.keys())

    @classmethod
    def values(cls) -> t.List[t.Union[str, NameTitle]]:
        """Get all enum labels."""
        return list(cls.__labels__.values())

    @classmethod
    def items(cls) -> t.List[t.Tuple[t.Any, t.Union[str, NameTitle]]]:
        """Get all enum values and associated labels."""
        return list(cls.__labels__.items())

    @classmethod
    def value_for(cls, name: str) -> t.Any:
        """Get enum value given a label name."""
        for key, value in list(cls.__labels__.items()):
            if isinstance(value, NameTitle) and value.name == name:
                return key

    @classmethod
    def nametitles(cls) -> t.List[NameTitle]:
        """Get names and titles of labels."""
        return [label for label in cls.values() if isinstance(label, tuple)]


_C = t.TypeVar('_C', bound=t.Collection)


class InspectableSet(t.Generic[_C]):
    """
    InspectableSet provides an ``elem in set`` test via attribute or dictionary access.

    For example, if ``permissions`` is an InspectableSet wrapping a regular `set`, a
    test for an element in the set can be rewritten from ``if 'view' in permissions`` to
    ``if permissions.view``. The concise form improves readability for visual inspection
    where code linters cannot help, such as in Jinja2 templates.

    InspectableSet provides a read-only view to the wrapped data source. The mutation
    operators ``+=``, ``-=``, ``&=``, ``|=`` and ``^=`` will be proxied to the
    underlying data source, if supported, while the copy operators ``+``, ``-``, ``&``,
    ``|`` and ``^`` will be proxied and the result re-wrapped with InspectableSet.

    If no data source is supplied to InspectableSet, an empty set is used.

    ::

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
        >>> joinset = myset | {'added'}
        >>> isinstance(joinset, InspectableSet)
        True
        >>> joinset = joinset | InspectableSet({'inspectable'})
        >>> isinstance(joinset, InspectableSet)
        True
        >>> 'member' in joinset
        True
        >>> 'other' in joinset
        True
        >>> 'added' in joinset
        True
        >>> 'inspectable' in joinset
        True
        >>> emptyset = InspectableSet()
        >>> len(emptyset)
        0
    """

    __slots__ = ('__members__',)
    __members__: _C

    def __init__(self, members: t.Union[_C, InspectableSet[_C], None] = None) -> None:
        if isinstance(members, InspectableSet):
            members = members.__members__
        object.__setattr__(
            self, '__members__', members if members is not None else set()
        )

    def __repr__(self) -> str:
        return f'InspectableSet({self.__members__!r})'

    def __hash__(self) -> int:
        return hash(self.__members__)

    def __contains__(self, key: t.Any) -> bool:
        return key in self.__members__

    def __iter__(self) -> t.Iterator:
        yield from self.__members__

    def __len__(self) -> int:
        return len(self.__members__)

    def __bool__(self) -> bool:
        return bool(self.__members__)

    def __getitem__(self, key: t.Any) -> bool:
        return key in self.__members__  # Return True if present, False otherwise

    def __setattr__(self, attr: str, _value: t.Any) -> t.NoReturn:
        """Prevent accidental attempts to set a value."""
        raise AttributeError(attr)

    def __getattr__(self, attr: str) -> bool:
        return attr in self.__members__  # Return True if present, False otherwise

    def _op_bool(self, op: str, other: t.Any) -> bool:
        """Return result of a boolean operation."""
        if hasattr(self.__members__, op):
            if isinstance(other, InspectableSet):
                other = other.__members__
            return getattr(self.__members__, op)(other)
        return NotImplemented

    def __le__(self, other: t.Any) -> bool:
        """Return self <= other."""
        return self._op_bool('__le__', other)

    def __lt__(self, other: t.Any) -> bool:
        """Return self < other."""
        return self._op_bool('__lt__', other)

    def __eq__(self, other: t.Any) -> bool:
        """Return self == other."""
        return self._op_bool('__eq__', other)

    def __ne__(self, other: t.Any) -> bool:
        """Return self != other."""
        return self._op_bool('__ne__', other)

    def __gt__(self, other: t.Any) -> bool:
        """Return self > other."""
        return self._op_bool('__gt__', other)

    def __ge__(self, other: t.Any) -> bool:
        """Return self >= other."""
        return self._op_bool('__ge__', other)

    def _op_copy(self, op: str, other: t.Any) -> InspectableSet[_C]:
        """Return result of a copy operation."""
        if hasattr(self.__members__, op):
            if isinstance(other, InspectableSet):
                other = other.__members__
            retval = getattr(self.__members__, op)(other)
            if retval is not NotImplemented:
                return InspectableSet(retval)
        return NotImplemented

    def __add__(self, other: t.Any) -> InspectableSet[_C]:
        """Return self + other (add)."""
        return self._op_copy('__add__', other)

    def __radd__(self, other: t.Any) -> InspectableSet[_C]:
        """Return other + self (reverse add)."""
        return self._op_copy('__radd__', other)

    def __sub__(self, other: t.Any) -> InspectableSet[_C]:
        """Return self - other (subset)."""
        return self._op_copy('__sub__', other)

    def __rsub__(self, other: t.Any) -> InspectableSet[_C]:
        """Return other - self (reverse subset)."""
        return self._op_copy('__rsub__', other)

    def __and__(self, other: t.Any) -> InspectableSet[_C]:
        """Return self & other (intersection)."""
        return self._op_copy('__and__', other)

    def __rand__(self, other: t.Any) -> InspectableSet[_C]:
        """Return other & self (intersection)."""
        return self._op_copy('__rand__', other)

    def __or__(self, other: t.Any) -> InspectableSet[_C]:
        """Return self | other (union)."""
        return self._op_copy('__or__', other)

    def __ror__(self, other: t.Any) -> InspectableSet[_C]:
        """Return other | self (union)."""
        return self._op_copy('__ror__', other)

    def __xor__(self, other: t.Any) -> InspectableSet[_C]:
        """Return self ^ other (non-intersecting)."""
        return self._op_copy('__xor__', other)

    def __rxor__(self, other: t.Any) -> InspectableSet[_C]:
        """Return other ^ self (non-intersecting)."""
        return self._op_copy('__rxor__', other)

    def _op_inplace(self, op: str, other: t.Any) -> te.Self:
        """Return self after an inplace operation."""
        if hasattr(self.__members__, op):
            if isinstance(other, InspectableSet):
                other = other.__members__
            if getattr(self.__members__, op)(other) is NotImplemented:
                return NotImplemented
            return self
        return NotImplemented

    def __iadd__(self, other: t.Any) -> te.Self:
        """Operate self += other (list/tuple add)."""
        return self._op_inplace('__iadd__', other)

    def __isub__(self, other: t.Any) -> te.Self:
        """Operate self -= other (set.difference_update)."""
        return self._op_inplace('__isub__', other)

    def __iand__(self, other: t.Any) -> te.Self:
        """Operate self &= other (set.intersection_update)."""
        return self._op_inplace('__iand__', other)

    def __ior__(self, other: t.Any) -> te.Self:
        """Operate self |= other (set.update)."""
        return self._op_inplace('__ior__', other)

    def __ixor__(self, other: t.Any) -> te.Self:
        """Operate self ^= other (set.symmetric_difference_update)."""
        return self._op_inplace('__isub__', other)


class classmethodproperty:  # noqa: N801
    """
    Class method decorator to make class methods behave like properties.

    Usage::

        >>> class Foo:
        ...     @classmethodproperty
        ...     def test(cls):
        ...         return repr(cls)
        ...

    Works on classes::

        >>> Foo.test
        "<class 'coaster.utils.classes.Foo'>"

    Works on class instances::

        >>> Foo().test
        "<class 'coaster.utils.classes.Foo'>"

    Works on subclasses too::

        >>> class Bar(Foo):
        ...     pass
        ...
        >>> Bar.test
        "<class 'coaster.utils.classes.Bar'>"
        >>> Bar().test
        "<class 'coaster.utils.classes.Bar'>"

    Due to limitations in Python's descriptor API, :class:`classmethodproperty` can
    block write and delete access on an instance...

    ::

        >>> Foo().test = 'bar'
        Traceback (most recent call last):
        AttributeError: test is read-only
        >>> del Foo().test
        Traceback (most recent call last):
        AttributeError: test is read-only

    ...but not on the class itself::

        >>> Foo.test = 'bar'
        >>> Foo.test
        'bar'
    """

    def __init__(self, func: t.Callable) -> None:
        self.func = func

    def __get__(self, _obj: t.Any, cls: t.Type) -> t.Any:
        return self.func(cls)

    def __set__(self, _obj: t.Any, _value: t.Any) -> t.NoReturn:
        raise AttributeError(f"{self.func.__name__} is read-only")

    def __delete__(self, _obj: t.Any) -> t.NoReturn:
        raise AttributeError(f"{self.func.__name__} is read-only")
