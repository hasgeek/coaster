"""Tests for dataclass extensions of base types."""

# pylint: disable=redefined-outer-name,unused-variable

import pickle  # nosec B403
import typing as t
from dataclasses import FrozenInstanceError, dataclass
from enum import Enum

import pytest

from coaster.utils import DataclassFromType


@dataclass(frozen=True, eq=False)
class StringMetadata(DataclassFromType, str):
    description: str
    extra: t.Optional[str] = None


@dataclass(frozen=True, eq=False)
class IntMetadata(DataclassFromType, int):
    title: str


class MetadataEnum(StringMetadata, Enum):
    FIRST = "first", "First string"
    SECOND = "second", "Second string", "Optional extra"


# Required until ReprEnum in Python 3.11:
del MetadataEnum.__str__
del MetadataEnum.__format__


@pytest.fixture()
def a() -> StringMetadata:
    return StringMetadata('a', "A string")


@pytest.fixture()
def b() -> StringMetadata:
    return StringMetadata('b', "B string")


@pytest.fixture()
def b2() -> StringMetadata:
    return StringMetadata('b', "Also B string", "Extra metadata")


def test_no_init() -> None:
    """DataclassFromType cannot be instantiated."""
    with pytest.raises(TypeError, match="cannot be directly instantiated"):
        DataclassFromType(0)


def test_first_base() -> None:
    """DataclassFromType must be the first base in a subclass."""
    with pytest.raises(TypeError, match="must be the first base"):

        class WrongSubclass(str, DataclassFromType):
            pass


def test_required_data_type() -> None:
    """Subclasses must have a second base class for the data type."""
    with pytest.raises(TypeError, match="second base class"):

        class MissingDataType(DataclassFromType):
            pass

    class GivenDataType(DataclassFromType, int):
        pass

    assert GivenDataType('0') == 0  # Same as int('0') == 0


def test_immutable_data_type() -> None:
    """The data type must be immutable."""

    class Immutable(DataclassFromType, tuple):  # skipcq: PTC-W0065
        pass

    with pytest.raises(TypeError, match="data type must be immutable"):

        class Mutable(DataclassFromType, list):
            pass


def test_annotated_str(
    a: StringMetadata, b: StringMetadata, b2: StringMetadata
) -> None:
    """DataclassFromType string dataclasses have string equivalency."""
    assert a == 'a'
    assert b == 'b'
    assert b2 == 'b'
    assert 'a' == a
    assert 'b' == b
    assert 'b' == b2
    assert a != b
    assert a != b2
    assert b != a
    assert b == b2
    assert b2 == b
    assert b2 != a
    assert a < b
    assert b > a

    # All derivative objects will regress to the base data type
    assert isinstance(a, StringMetadata)
    assert isinstance(b, StringMetadata)
    assert isinstance(a + b, str)
    assert isinstance(b + a, str)
    assert not isinstance(a + b, StringMetadata)
    assert not isinstance(b + a, StringMetadata)


def test_dataclass_fields_set(
    a: StringMetadata, b: StringMetadata, b2: StringMetadata
) -> None:
    """Dataclass fields are set correctly."""
    assert a.self == 'a'
    assert a.description == "A string"
    assert a.extra is None
    assert b.self == 'b'
    assert b.description == "B string"
    assert b.extra is None
    assert b2.self == 'b'
    assert b2.description == "Also B string"
    assert b2.extra == "Extra metadata"
    # Confirm self cannot be set
    with pytest.raises(FrozenInstanceError):
        a.self = 'b'  # type: ignore[misc]


def test_dict_keys(a: StringMetadata, b: StringMetadata, b2: StringMetadata) -> None:
    """DataclassFromType-based dataclasses can be used as dict keys."""
    d: t.Dict[t.Any, t.Any] = {a: a.description, b: b.description}
    assert d['a'] == a.description
    assert set(d) == {a, b}
    assert set(d) == {'a', 'b'}
    for key in d:
        assert isinstance(key, StringMetadata)


def test_dict_overlap(a: StringMetadata) -> None:
    """Dict key overlap retains the key and type but replaces the value."""
    d1 = {'a': "Primary", a: "Overlap"}
    d2 = {a: "Primary", 'a': "Overlap"}
    assert len(d2) == 1
    assert len(d1) == 1
    assert d1['a'] == "Overlap"
    assert d2['a'] == "Overlap"
    assert isinstance(list(d1.keys())[0], str)
    assert isinstance(list(d2.keys())[0], str)
    assert not isinstance(list(d1.keys())[0], StringMetadata)  # Retained str
    assert isinstance(list(d2.keys())[0], StringMetadata)  # Retained StringMetadata


def test_pickle(a: StringMetadata) -> None:
    """Pickle dump and load will reconstruct the full dataclass."""
    p = pickle.dumps(a)
    a2 = pickle.loads(p)  # nosec B301
    assert isinstance(a2, StringMetadata)
    assert a2 == a
    assert a2.self == 'a'
    assert a2.description == "A string"


def test_repr() -> None:
    """Dataclass-provided repr and original repr both work correctly."""

    @dataclass(frozen=True, repr=True)
    class WithRepr(DataclassFromType, str):
        second: str

    @dataclass(frozen=True, repr=False)
    class WithoutRepr(DataclassFromType, str):
        second: str

    a = WithRepr('a', "A")
    b = WithoutRepr('b', "B")
    # Dataclass-provided repr, but fixed to report `self`
    assert repr(a) == "test_repr.<locals>.WithRepr('a', second='A')"
    # Original repr from `str` data type
    assert repr(b) == "'b'"


def test_metadata_enum() -> None:
    """Enum members behave like strings."""
    assert isinstance(MetadataEnum.FIRST, str)
    assert MetadataEnum.FIRST.self == "first"
    assert MetadataEnum.FIRST == "first"
    assert MetadataEnum.SECOND == "second"  # type: ignore[unreachable]
    assert MetadataEnum['FIRST'] is MetadataEnum.FIRST
    assert MetadataEnum('first') is MetadataEnum.FIRST
    assert str(MetadataEnum.FIRST) == 'first'
    assert format(MetadataEnum.FIRST) == 'first'
    assert str(MetadataEnum.SECOND) == 'second'
    assert format(MetadataEnum.SECOND) == 'second'
    assert hash(MetadataEnum.FIRST) == hash('first')
    assert hash(MetadataEnum.SECOND) == hash('second')
    assert hash(MetadataEnum.FIRST) != MetadataEnum.SECOND
