"""
Utility classes
---------------
"""

from __future__ import annotations

import dataclasses
import typing as t
import typing_extensions as te
import warnings
from reprlib import recursive_repr
from typing import NamedTuple

__all__ = [
    'DataclassFromType',
    'NameTitle',
    'LabeledEnum',
    'InspectableSet',
    'classproperty',
    'classmethodproperty',
]

_T = t.TypeVar('_T')
_R = t.TypeVar('_R')


class SelfProperty:
    """Provides :attr:`DataclassFromType.self` (singleton instance)."""

    @t.overload
    def __get__(self, obj: None, _cls: t.Type) -> t.NoReturn:
        ...

    @t.overload
    def __get__(self, obj: _T, _cls: t.Type[_T]) -> _T:
        ...

    def __get__(self, obj: t.Optional[_T], _cls: t.Type[_T]) -> _T:
        if obj is None:
            raise AttributeError("Flag for @dataclass to recognise no default value")

        return obj

    # The value parameter must be typed `Any` because we cannot make assumptions about
    # the acceptable parameters to the base data type's constructor. For example, `str`
    # will accept almost anything, not just another string. The type defined here will
    # flow down to the eventual dataclass's `self` field's type.
    def __set__(self, _obj: t.Any, _value: t.Any) -> None:
        # Do nothing. This method will get exactly one call from the dataclass-generated
        # __init__. Future attempts to set the attr will be blocked in a frozen
        # dataclass. __set__ must exist despite being a no-op to follow Python's data
        # descriptor protocol. If not present, a variable named `self` will be inserted
        # into the object's instance __dict__, making it a dupe of the data.
        return


# DataclassFromType must be a dataclass itself to ensure the `self` property is
# identified as a field. Unfortunately, we also need to be opinionated about `frozen` as
# `@dataclass` requires consistency across the hierarchy. Our opinion is that
# dataclasses based on immutable types should by immutable.
@dataclasses.dataclass(init=False, repr=False, eq=False, frozen=True)
class DataclassFromType:
    """
    Base class for constructing dataclasses that annotate an existing type.

    For use when the context requires a basic datatype like `int` or `str`, but
    additional descriptive fields are desired. Example::

        >>> @dataclasses.dataclass(eq=False, frozen=True)
        ... class DescribedString(DataclassFromType, str):
        ...     description: str

        >>> all = DescribedString("all", "All users")
        >>> more = DescribedString(description="Reordered kwargs", self="more")
        >>> all
        DescribedString('all', description='All users')

        >>> assert all == "all"
        >>> assert "all" == all
        >>> assert all.self == "all"
        >>> assert all.description == "All users"
        >>> assert more == "more"
        >>> assert more.description == "Reordered kwargs"

    :class:`DataclassFromType` provides a dataclass field named ``self`` as the first
    field. This is a read-only property that returns ``self``. The value provided to
    this field when instantiating the dataclass is passed to the data type's
    constructor. Additional arguments to the data type are not supported. If you need
    them, use the data type directly and pass the constructed object to the dataclass::

        >>> DescribedString(str(b'byte-value', 'ascii'), "Description here")
        DescribedString('byte-value', description='Description here')

    The data type must be immutable and the dataclass must be frozen. The data type's
    ``__eq__`` and ``__hash__`` methods will be copied to each subclass to ensure it
    remains interchangeable with the data type and to prevent the dataclass decorator
    from inserting its own definitions. This has the side effect that equality will be
    solely on the basis of the data type's value, even if other fields differ::

        >>> assert DescribedString("a", "One") == DescribedString("a", "Two")

    If this is not desired and interchangeability with the base data type can be
    foregone, the subclass may define its own ``__eq__`` and ``__hash__`` methods, but
    beware that this can break in subtle ways as Python has multiple pathways to test
    for equality.

    :class:`DataclassFromType` also provides a ``__repr__`` that renders the base data
    type correctly. The repr provided by :func:`~dataclasses.dataclass` will attempt to
    recurse :attr:`self` and will render it as ``...``, hiding the actual value.

    Note that all methods and attributes of the base data type will also be available
    via the dataclass, so you should avoid clashing field names. For instance,
    :meth:`str.title` is an existing method, so a field named ``title`` will be flagged
    by static type checkers and if ignored can cause unexpected grief downstream when
    some code attempts to call ``.title()``.

    Dataclasses can be used in an enumeration, making enum members compatible with the
    base data type::

        >>> from enum import Enum

        >>> # In Python 3.11+, use `ReprEnum` instead of `Enum`
        >>> class StringCollection(DescribedString, Enum):
        ...     FIRST = 'first', "First item"
        ...     SECOND = 'second', "Second item"

        >>> # Enum provides the `name` and `value` properties
        >>> assert StringCollection.FIRST.value == 'first'
        >>> assert StringCollection.FIRST.name == 'FIRST'
        >>> assert StringCollection.FIRST.description == "First item"
        >>> # The enum itself is a string and directly comparable with one
        >>> assert StringCollection.FIRST == 'first'
        >>> assert 'first' == StringCollection.FIRST
        >>> assert StringCollection('first') is StringCollection.FIRST

    :class:`~enum.Enum` adds ``__str__`` and ``__format__`` methods that block access to
    the actual value and behave inconsistently between Python versions. This is fixed
    with :class:`~enum.ReprEnum` in Python 3.11. For older Python versions, the
    additional methods have to be removed after defining the enum. There is currently no
    convenient way to do this::

        >>> assert str(StringCollection.FIRST) == 'StringCollection.FIRST'
        >>> del StringCollection.__str__
        >>> del StringCollection.__format__
        >>> assert str(StringCollection.FIRST) == 'first'
        >>> assert format(StringCollection.FIRST) == 'first'

    Enum usage may make more sense with int-derived dataclasses, with the same caveat
    that ``str(enum) != str(int(enum))`` unless :class:`~enum.ReprEnum` is used::

        >>> from typing import Optional

        >>> @dataclasses.dataclass(frozen=True, eq=False)
        ... class StatusCode(DataclassFromType, int):
        ...     title: str  # title is not an existing attr of int, unlike str.title
        ...     comment: Optional[str] = None

        >>> # In Python 3.11+, use `ReprEnum` instead of `Enum`
        >>> class HttpStatus(StatusCode, Enum):
        ...     OK = 200, "OK"
        ...     CREATED = 201, "Created"
        ...     UNAUTHORIZED = 401, "Unauthorized", "This means login is required"
        ...     FORBIDDEN = 403, "Forbidden", "This means you don't have the rights"

        >>> assert HttpStatus(200) is HttpStatus.OK
        >>> assert HttpStatus.OK == 200
        >>> assert 200 == HttpStatus.OK
        >>> assert HttpStatus.CREATED.comment is None
        >>> assert HttpStatus.UNAUTHORIZED.comment.endswith("login is required")

    It is possible to skip the dataclass approach and customize an Enum's constructor
    directly. This approach is opaque to type checkers, causes incorrect type
    inferences, and is apparently hard for them to fix. Relevant tickets:

    * Infer attributes from ``__new__``: https://github.com/python/mypy/issues/1021
    * Ignore type of custom enum's value: https://github.com/python/mypy/issues/10000
    * Enum value type inference fix: https://github.com/python/mypy/pull/16320
    * Type error when calling Enum: https://github.com/python/mypy/issues/10573
    * Similar error with Pyright: https://github.com/microsoft/pyright/issues/1751

    ::

        >>> from enum import IntEnum

        >>> class HttpIntEnum(IntEnum):
        ...     def __new__(cls, code: int, title: str, comment: Optional[str] = None):
        ...         obj = int.__new__(cls, code)
        ...         obj._value_ = code
        ...         obj.title = title
        ...         obj.comment = comment
        ...         return obj
        ...     OK = 200, "OK"
        ...     CREATED = 201, "Created"
        ...     UNAUTHORIZED = 401, "Unauthorized", "This means login is required"
        ...     FORBIDDEN = 403, "Forbidden", "This means you don't have the rights"

        >>> assert HttpIntEnum(200) is HttpIntEnum.OK
        >>> assert HttpIntEnum.OK == 200
        >>> assert 200 == HttpIntEnum.OK

    The end result is similar: the enum is a subclass of the data type with additional
    attributes on it, but the dataclass approach is more compatible with type checkers.
    The `Enum Properties <https://enum-properties.readthedocs.io/>`_ project provides a
    much more elegant syntax not requiring dataclasses, but is similarly not compatible
    with type hinting.
    """

    __dataclass_params__: t.ClassVar[t.Any]

    # Allow subclasses to use `@dataclass(slots=True)` (Python 3.10+). Slots must be
    # empty as non-empty slots are incompatible with other base classes that also have
    # non-empty slots, and with variable length immutable data types like int, bytes and
    # tuple: https://docs.python.org/3/reference/datamodel.html#datamodel-note-slots
    __slots__ = ()

    if t.TYPE_CHECKING:
        # Mypy bugs: descriptor-based fields without a default value are understood by
        # @dataclass, but not by Mypy. Therefore pretend to not be a descriptor.
        # Unfortunately, we don't know the data type and have to declare it as Any, but
        # we also exploit (buggy) behaviour in Mypy where declaring the descriptor type
        # here will replace it with the descriptor's __get__ return type in subclasses,
        # but only if both are frozen. Descriptor fields cannot be marked as InitVar
        # because mypy thinks they do not exist as attributes on the class. Bug report
        # for both: https://github.com/python/mypy/issues/16538
        self: t.Union[SelfProperty, t.Any]
    else:
        # For runtime, make `self` a dataclass descriptor field with no default value
        self: SelfProperty = SelfProperty()
        """
        Read-only property that returns self and appears as the first field in the
        dataclass.
        """

    # Note: self cannot be specified as ``field(init=False)`` because of the way Python
    # object construction flows: ``__new__(cls, *a, **kw).__init__(*a, **kw)``.
    # Both calls get identical parameters, so `__init__` _must_ receive the parameter
    # in the first position and _must_ name it `self`. The autogenerated init function
    # will get the signature ``def __init__(__dataclass_self__, self, ...)``

    # Note: self cannot be marked `InitVar` because that excludes it from the dataclass
    # autogenerated hash and compare features: ``@dataclass(eq=True, hash=True,
    # compare=True)``. We can't specify it using `field` because that can't be used with
    # a descriptor. ``self: InitVar[SelfProperty] = field(hash=True, compare=True)``
    # doesn't work. Without a descriptor, we'll be keeping two copies of the value, with
    # the risk that the copy can be mutated to differ from the self value.

    def __new__(cls, self: t.Any, *_args: t.Any, **_kwargs: t.Any) -> te.Self:
        """Construct a new instance using only the first arg for the base data type."""
        if cls is DataclassFromType:
            raise TypeError("DataclassFromType cannot be directly instantiated")
        return super().__new__(cls, self)  # type: ignore[call-arg]

    def __init_subclass__(cls) -> None:
        """Audit and configure subclasses."""
        if cls.__bases__ == (DataclassFromType,):
            raise TypeError(
                "Subclasses must specify the data type as the second base class"
            )
        if DataclassFromType in cls.__bases__ and cls.__bases__[0] != DataclassFromType:
            raise TypeError("DataclassFromType must be the first base class")
        if cls.__bases__[0] is DataclassFromType and super().__hash__ in (
            None,  # Base class defined `__eq__` and Python inserted `__hash__ = None`
            object.__hash__,  # This returns `id(obj)` and is not a content hash
        ):
            # Treat content-based hashability as a proxy for immutability
            raise TypeError("The data type must be immutable")
        super().__init_subclass__()

        # Required to prevent `@dataclass` from overriding these methods. Allowing
        # dataclass to produce `__eq__` will break it, causing a recursion error
        if '__eq__' not in cls.__dict__:
            cls.__eq__ = super().__eq__  # type: ignore[method-assign]
            # Try to insert `__hash__` only if the class had no custom `__eq__`
            if '__hash__' not in cls.__dict__:
                cls.__hash__ = super().__hash__  # type: ignore[method-assign]

        if '__repr__' not in cls.__dict__:
            cls.__repr__ = (  # type: ignore[method-assign]
                DataclassFromType.__dataclass_repr__
            )

    @recursive_repr()
    def __dataclass_repr__(self) -> str:
        """Provide a dataclass-like repr that doesn't recurse into self."""
        self_repr = super().__repr__()  # Invoke __repr__ on the data type
        if not self.__dataclass_params__.repr:
            # Since this dataclass was configured with repr=False,
            # return super().__repr__()
            return self_repr
        fields_repr = ', '.join(
            [
                f'{field.name}={getattr(self, field.name)!r}'
                for field in dataclasses.fields(self)[1:]
                if field.repr
            ]
        )
        return f'{self.__class__.__qualname__}({self_repr}, {fields_repr})'


class NameTitle(NamedTuple):
    name: str
    title: str


class LabeledEnumWarning(UserWarning):
    """Warning for labeled enumerations using deprecated syntax."""


class _LabeledEnumMeta(type):
    """Construct labeled enumeration."""

    def __new__(
        mcs: t.Type,  # noqa: N804
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
                    warnings.warn(
                        "The (value, name, title) syntax to construct NameTitle objects"
                        " is deprecated; pass your own object instead",
                        LabeledEnumWarning,
                        stacklevel=2,
                    )
                    labels[value[0]] = NameTitle(value[1], value[2])
                    attrs[key] = names[key] = value[0]
                else:  # pragma: no cover
                    raise AttributeError(f"Unprocessed attribute {key}")
            elif key != '__order__' and isinstance(value, set):
                # value = set of other unprocessed values
                attrs[key] = names[key] = {
                    v[0] if isinstance(v, tuple) else v for v in value
                }

        if '__order__' in attrs:  # pragma: no cover
            warnings.warn(
                "LabeledEnum.__order__ is not required since Python 3.6 and is ignored",
                LabeledEnumWarning,
                stacklevel=2,
            )

        attrs['__labels__'] = labels
        attrs['__names__'] = names
        return type.__new__(mcs, name, bases, attrs)

    def __getitem__(cls, key: t.Any) -> t.Any:
        return cls.__labels__[key]  # type: ignore[attr-defined]

    def __contains__(cls, key: t.Any) -> bool:
        return key in cls.__labels__  # type: ignore[attr-defined]


class LabeledEnum(metaclass=_LabeledEnumMeta):
    """
    Labeled enumerations.

    .. deprecated:: 0.7.0
        LabeledEnum is not compatible with static type checking as metaclasses that
        modify class attributes are not supported as of late 2023, with no proposal for
        adding this support. Use regular Python enums instead, using a
        :class:`DataclassFromType`-based :func:`~dataclasses.dataclass` to hold the
        label.

    Declare an enumeration with values and labels (for use in UI)::

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
    def get(cls, key: t.Any, default: t.Optional[t.Any] = None) -> t.Any:
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
        return None

    @classmethod
    def nametitles(cls) -> t.List[NameTitle]:
        """Get names and titles of labels."""
        return [label for label in cls.values() if isinstance(label, tuple)]


_C = t.TypeVar('_C', bound=t.Collection)


class InspectableSet(t.Generic[_C]):
    """
    InspectableSet provides an ``elem in set`` test via attribute or dictionary access.

    For example, if ``iset`` is an :class:`InspectableSet` wrapping a regular
    :class:`set`, a test for an element in the set can be rewritten from ``if 'elem' in
    iset`` to ``if iset.elem``. The concise form improves readability for visual
    inspection where code linters cannot help, such as in Jinja2 templates.

    InspectableSet provides a view to the wrapped data source. The mutation operators
    ``+=``, ``-=``, ``&=``, ``|=`` and ``^=`` will be proxied to the underlying data
    source, if supported, while the copy operators ``+``, ``-``, ``&``, ``|`` and ``^``
    will be proxied and the result re-wrapped with InspectableSet.

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

    __slots__ = ('_members',)
    _members: _C

    def __init__(self, members: t.Union[_C, InspectableSet[_C], None] = None) -> None:
        if isinstance(members, InspectableSet):
            members = members._members
        object.__setattr__(self, '_members', members if members is not None else set())

    def __repr__(self) -> str:
        return f'self.__class__.__qualname__({self._members!r})'

    def __hash__(self) -> int:
        return hash(self._members)

    def __contains__(self, key: t.Any) -> bool:
        return key in self._members

    def __iter__(self) -> t.Iterator:
        yield from self._members

    def __len__(self) -> int:
        return len(self._members)

    def __bool__(self) -> bool:
        return bool(self._members)

    def __getitem__(self, key: t.Any) -> bool:
        return key in self._members  # Return True if present, False otherwise

    def __setattr__(self, attr: str, _value: t.Any) -> t.NoReturn:
        """Prevent accidental attempts to set a value."""
        raise AttributeError(attr)

    def __getattr__(self, attr: str) -> bool:
        return attr in self._members  # Return True if present, False otherwise

    def _op_bool(self, op: str, other: t.Any) -> bool:
        """Return result of a boolean operation."""
        if hasattr(self._members, op):
            if isinstance(other, InspectableSet):
                other = other._members  # pylint: disable=protected-access
            return getattr(self._members, op)(other)
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
        if hasattr(self._members, op):
            if isinstance(other, InspectableSet):
                other = other._members  # pylint: disable=protected-access
            retval = getattr(self._members, op)(other)
            if retval is not NotImplemented:
                return self.__class__(retval)
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
        if hasattr(self._members, op):
            if isinstance(other, InspectableSet):
                other = other._members  # pylint: disable=protected-access
            result = getattr(self._members, op)(other)
            if result is NotImplemented:
                return NotImplemented
            if result is not self._members:
                # Did this operation return a new instance? Then we must too.
                return self.__class__(result)
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


class classproperty(t.Generic[_T, _R]):  # noqa: N801
    """
    Decorator to make class methods behave like read-only properties.

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

    def __init__(self, func: t.Callable[[t.Type[_T]], _R]) -> None:
        if isinstance(func, classmethod):
            func = func.__func__  # type: ignore[unreachable]
        # For using `help(...)` on instances in Python >= 3.9.
        self.__doc__ = func.__doc__
        self.__module__ = func.__module__
        self.__name__ = func.__name__
        self.__qualname__ = func.__qualname__

        self.__wrapped__ = func

    def __set_name__(self, owner: t.Type[_T], name: str) -> None:
        self.__module__ = owner.__module__
        self.__name__ = name
        self.__qualname__ = f'{owner.__qualname__}.{name}'

    def __get__(self, obj: t.Optional[_T], cls: t.Optional[t.Type[_T]] = None) -> _R:
        if cls is None:
            cls = type(t.cast(_T, obj))
        return self.__wrapped__(cls)

    def __set__(self, _obj: t.Any, _value: t.Any) -> t.NoReturn:
        raise AttributeError(f"{self.__wrapped__.__name__} is read-only")

    def __delete__(self, _obj: t.Any) -> t.NoReturn:
        raise AttributeError(f"{self.__wrapped__.__name__} is read-only")


# Legacy name
classmethodproperty = classproperty
