"""
Utility classes
---------------
"""

from __future__ import annotations

import dataclasses
import typing as t
import typing_extensions as te
import warnings
from typing import NamedTuple

__all__ = [
    'DataclassFromType',
    'NameTitle',
    'LabeledEnum',
    'InspectableSet',
    'classmethodproperty',
]

_T = t.TypeVar('_T')
_R = t.TypeVar('_R')

POST_INIT_FLAG: t.Final = '_post_init'


class DataclassFromTypeSelfProperty:
    """Provides :attr:`DataclassFromType.self` (singleton instance)."""

    # Note: This class cannot store any state within `self` as it is a singleton

    @t.overload
    def __get__(self, __obj: None, __cls: t.Type) -> t.NoReturn:
        ...

    @t.overload
    def __get__(self, __obj: _T, __cls: t.Type[_T]) -> _T:
        ...

    def __get__(self, __obj: t.Optional[_T], __cls: t.Type[_T]) -> _T:
        if __obj is None:
            raise AttributeError("Flag for @dataclass to recognise no default value")
        return __obj

    # The value parameter must be typed `Any` because we cannot make assumptions about
    # the acceptable parameters to the base data type's constructor. For example, `str`
    # will accept almost anything, not just another string. The type defined here will
    # flow down to the eventual dataclass's `self_` field's type.
    def __set__(self, __obj: t.Any, __value: t.Any) -> None:
        # Return without doing anything, even though setting `self` should be an error.
        # We will get one legitimate call during the dataclass-generated `__init__` that
        # we must ignore without erroring. However, we can't track subsequent calls by
        # storing state within self as only one instance of this class will exist across
        # the subclass hierarchy. If we store state within the dataclass instead, it
        # will be an unexpected side-effect, so we simply return without erroring for
        # now. Using InitVar to prevent this call has the unfortunate side-effect of
        # making the property disappear for static type checkers (a bug?).
        # Reported at https://github.com/python/mypy/issues/16538
        # if getattr(__obj, POST_INIT_FLAG, False):
        #     raise TypeError(f"{__obj.__class__.__qualname__}.self_ cannot be set")
        # try:
        #     object.__setattr__(__obj, POST_INIT_FLAG, True)
        # except AttributeError:
        #     # Class has __slots__ without POST_INIT_FLAG in it, can't do anything
        #     pass
        return


# DataclassFromType must be a dataclass itself to ensure the `self_` property is
# identified as a field. Unfortunately, we also need to be opinionated about
# `frozen` being True or False as `@dataclass` requires consistency across the
# hierarchy. Our opinion is that the use case veers towards frozen instances.
@dataclasses.dataclass(init=False, repr=False, eq=False, frozen=True)
class DataclassFromType:
    """
    Base class for constructing dataclasses that annotate an existing type.

    For use when the context requires a basic datatype like `int` or `str`, but
    additional descriptive fields are desired. Example::

        >>> @dataclasses.dataclass(frozen=True)
        ... class DescribedString(DataclassFromType, str):
        ...     description: str

        >>> all = DescribedString("all", "All users")
        >>> more = DescribedString(description="Reordered kwargs", self_="more")

        >>> assert all == "all"
        >>> assert "all" == all
        >>> assert all.self_ == "all"
        >>> assert all.description == "All users"
        >>> assert more == "more"
        >>> assert more.description == "Reordered kwargs"

    :class:`DataclassFromType_` provides a field named `self_` as the first field in the
    dataclass. This is a property that returns `self` and ignores any attempts to set
    it. The value provided to this field when instantiating the dataclass is passed to
    the data type's constructor. Additional arguments to the data type are not
    supported. If you need them, use the data type directly and pass the constructed
    object to the dataclass::

        >>> b_str = DescribedString(str(b'byte-value', 'ascii'), "Description here")

    The data type must be immutable and the dataclass must be frozen.
    :class:`DataclassFromType` will insert the data type's `__eq__` and `__hash__`
    methods into all subclasses to prevent ``@dataclass`` from auto-generating them, to
    ensure the subclass remains interchangeable with the data type. This is the
    equivalent of using `@dataclass(eq=False)`. This has the side-effect that two
    instances with the same data type value but different field values will be
    considered equal to each other, even if they are instances of different dataclasses
    based on the same data type::

        >>> assert DescribedString("a", "One") == DescribedString("a", "Two")

    If this side effect is not desired, the dataclass must provide its own ``__eq__``
    and ``__hash__`` methods.

    Note that all methods and attributes of the base data type will also be available
    via the dataclass, so you should avoid clashing field names. For instance,
    :meth:`str.title` is an existing method, so a field named ``title`` can cause
    unexpected grief downstream when some code attempts to call ``.title()``. Since new
    methods are sometimes added with newer Python releases, you should audit your
    dataclasses against them.

    These dataclasses can be used in an enumeration, making enum members compatible with
    the base data type::

        >>> from enum import Enum, auto

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

    Enum usage may make more sense with int-derived dataclasses::

        >>> from typing import Optional

        >>> @dataclasses.dataclass(frozen=True)
        ... class StatusCode(DataclassFromType, int):
        ...     title: str  # `title` is not an existing attr of `int`, unlike `str`
        ...     comment: Optional[str] = None

        >>> # In Python 3.11+, use `ReprEnum` instead of `Enum` as the base class
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
    directly, but this approach is verbose and opaque to type checkers, causes incorrect
    type inferences, and is hard for them to fix or deemed not worth supporting.
    Relevant tickets:

    * Infer attributes from ``__new__``: https://github.com/python/mypy/issues/1021
    * Ignore type of custom enum's value: https://github.com/python/mypy/issues/10000
    * Enum value type inference fix: https://github.com/python/mypy/pull/16320
    * Type error when calling Enum: https://github.com/python/mypy/issues/10573
    * Similar error with Pyright: https://github.com/microsoft/pyright/issues/1751

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
    attributes on it, but the dataclass approach is fully compatible with type checkers.
    """

    # Allow subclasses to use `@dataclass(slots=True)` (Python 3.10+). Slots must be
    # empty as non-empty slots are incompatible with other base classes that also have
    # non-empty slots, and with variable length immutable data types like int, bytes and
    # tuple: https://docs.python.org/3/reference/datamodel.html#datamodel-note-slots
    __slots__ = ()

    def __new__(cls, self_: t.Any, *_args: t.Any, **_kwargs: t.Any) -> te.Self:
        if cls is DataclassFromType:
            raise TypeError("DataclassFromType cannot be directly instantiated")
        return super().__new__(cls, self_)  # type: ignore[call-arg]

    def __init_subclass__(cls) -> None:
        if cls.__bases__ == (DataclassFromType,):
            raise TypeError(
                "Subclasses must specify the data type as the second base class"
            )
        if DataclassFromType in cls.__bases__ and cls.__bases__[0] != DataclassFromType:
            raise TypeError("DataclassFromType must be the first base class")
        if cls.__bases__[0] is DataclassFromType:
            if super().__hash__ in (None, object.__hash__):
                raise TypeError("The data type must be immutable")
        super().__init_subclass__()
        # Required to prevent `@dataclass` from overriding these methods
        if '__eq__' not in cls.__dict__:
            cls.__eq__ = super().__eq__  # type: ignore[method-assign]
            # Try to insert `__hash__` only if the class had no `__eq__`
            if '__hash__' not in cls.__dict__:
                cls.__hash__ = super().__hash__  # type: ignore[method-assign]

    # This hack is required due to a mypy bug:
    # https://github.com/python/mypy/issues/16538
    if t.TYPE_CHECKING:
        self_: t.Union[DataclassFromTypeSelfProperty, t.Any]
    else:
        # Provide self as the first field in the dataclass. We call it `self_` just in
        # case the dataclass needs a post-init: `def __post_init__(self, self_, ...)`
        self_: DataclassFromTypeSelfProperty = DataclassFromTypeSelfProperty()


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

        if '__order__' in attrs:
            warnings.warn(
                "LabeledEnum.__order__ is not required since Python >= 3.6 and will not"
                " be honoured",
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

    For example, if ``iset`` is an :class:`InspectableSet` wrapping a regular `set`, a
    test for an element in the set can be rewritten from ``if 'elem' in iset`` to ``if
    iset.elem``. The concise form improves readability for visual inspection where code
    linters cannot help, such as in Jinja2 templates.

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


class classmethodproperty(t.Generic[_T, _R]):  # noqa: N801
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

    def __init__(
        self, func: t.Union[t.Callable[[t.Type[_T]], _R], classmethod]
    ) -> None:
        if isinstance(func, classmethod):
            func = func.__func__
        self.fget = func

    def __get__(self, _obj: t.Optional[_T], cls: t.Type[_T]) -> _R:
        return self.fget(cls)

    def __set__(self, _obj: t.Any, _value: t.Any) -> t.NoReturn:
        raise AttributeError(f"{self.fget.__name__} is read-only")

    def __delete__(self, _obj: t.Any) -> t.NoReturn:
        raise AttributeError(f"{self.fget.__name__} is read-only")
