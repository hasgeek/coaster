"""Tests for dataclass extensions of base types."""
# pylint: disable=redefined-outer-name,unused-variable

import typing as t
from dataclasses import dataclass
from enum import Enum

import pytest

from coaster.utils import DataclassFromType


@dataclass(frozen=True)
class StringMetadata(DataclassFromType, str):
    description: str
    extra: t.Optional[str] = None


class MetadataEnum(StringMetadata, Enum):
    FIRST = "first", "First string"
    SECOND = "second", "Second string", "Optional extra"


@pytest.fixture()
def a() -> StringMetadata:
    return StringMetadata('a', "A string")


@pytest.fixture()
def b() -> StringMetadata:
    return StringMetadata('b', "B string")


@pytest.fixture()
def b2() -> StringMetadata:
    return StringMetadata('b', "Also B string", "Extra metadata")


def test_required_base_type() -> None:
    with pytest.raises(
        TypeError,
        match="Subclasses must specify the data type as the second base class",
    ):

        class MissingDataType(DataclassFromType):
            pass

    class GivenDataType(DataclassFromType, int):
        pass

    assert GivenDataType('0') == 0  # Same as int('0') == 0


def test_annotated_str(
    a: StringMetadata, b: StringMetadata, b2: StringMetadata
) -> None:
    """Test AnnotatedStr-based dataclasses for string equivalency."""
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
    """Confirm dataclass fields have been set."""
    assert a.self_ == 'a'
    assert a.description == "A string"
    assert a.extra is None
    assert b.self_ == 'b'
    assert b.description == "B string"
    assert b.extra is None
    assert b2.self_ == 'b'
    assert b2.description == "Also B string"
    assert b2.extra == "Extra metadata"


def test_dict_keys(a: StringMetadata, b: StringMetadata, b2: StringMetadata):
    """Check if AnnotatedStr-based dataclasses can be used as dict keys."""
    d: t.Dict[t.Any, t.Any] = {a: a.description, b: b.description}
    assert d['a'] == a.description
    assert set(d) == {a, b}
    assert set(d) == {'a', 'b'}
    for key in d:
        assert isinstance(key, StringMetadata)


def test_metadata_enum() -> None:
    assert isinstance(MetadataEnum.FIRST, str)
    assert MetadataEnum.FIRST.self_ == "first"
    assert MetadataEnum.FIRST == "first"
    assert MetadataEnum.SECOND == "second"  # type: ignore[unreachable]
    assert MetadataEnum['FIRST'] is MetadataEnum.FIRST
    assert MetadataEnum('first') is MetadataEnum.FIRST
