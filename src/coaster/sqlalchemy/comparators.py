"""Enhanced query and custom comparators."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any, Optional, Union
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.hybrid import Comparator

from ..utils import uuid_from_base58, uuid_from_base64

__all__ = [
    'SplitIndexComparator',
    'SqlSplitIdComparator',
    'SqlUuidHexComparator',
    'SqlUuidB64Comparator',
    'SqlUuidB58Comparator',
]


class SplitIndexComparator(Comparator):
    """Base class for comparators that split a string and compare with one part."""

    def __init__(
        self,
        expression: Any,
        splitindex: Optional[int] = None,
        separator: str = '-',
    ) -> None:
        super().__init__(expression)
        self.splitindex = splitindex
        self.separator = separator

    def _decode(self, other: str) -> Any:
        raise NotImplementedError

    def __eq__(self, other: object) -> sa.ColumnElement[bool]:  # type: ignore[override]
        try:
            other = self._decode(other)  # type: ignore[arg-type]
        except (ValueError, TypeError):
            # If other could not be decoded, we do not match.
            return sa.sql.expression.false()
        return self.__clause_element__() == other  # type: ignore[return-value]

    is_ = __eq__  # type: ignore[assignment]

    def __ne__(self, other: object) -> sa.ColumnElement[bool]:  # type: ignore[override]
        try:
            other = self._decode(other)  # type: ignore[arg-type]
        except (ValueError, TypeError):
            # If other could not be decoded, we are not equal.
            return sa.sql.expression.true()
        return self.__clause_element__() != other  # type: ignore[return-value]

    isnot = __ne__  # type: ignore[assignment]
    is_not = __ne__  # type: ignore[assignment]

    def in_(self, other: Any) -> sa.ColumnElement[bool]:  # type: ignore[override]
        """Check if self is present in the other."""

        def errordecode(otherlist: Any) -> Iterator[str]:
            for val in otherlist:
                with contextlib.suppress(ValueError, TypeError):
                    yield self._decode(val)

        valid_values = list(errordecode(other))
        if not valid_values:
            # If none of the elements could be decoded, return false
            return sa.sql.expression.false()

        return self.__clause_element__().in_(valid_values)  # type: ignore[attr-defined]


class SqlSplitIdComparator(SplitIndexComparator):
    """
    Given an ``id-text`` string, split out the integer id and allows comparison on it.

    Also supports ``text-id``, ``text-text-id`` or other specific locations for the id
    if specified as a `splitindex` parameter to the constructor.

    This comparator will not attempt to decode non-string values, and will attempt to
    support all operators, accepting SQL expressions for :attr:`other`.
    """

    def _decode(self, other: Any) -> Union[int, Any]:
        if isinstance(other, str):
            if self.splitindex is not None:
                return int(other.split(self.separator)[self.splitindex])
            return int(other)
        return other

    # FIXME: The type of `op` is not known as the sample code is not type-annotated in
    # https://docs.sqlalchemy.org/en/20/orm/extensions/hybrid.html
    # #building-custom-comparators
    def operate(self, op: Any, *other: Any, **kwargs) -> sa.ColumnElement[Any]:
        """Perform SQL operation on decoded value for other."""
        # If `other` cannot be decoded, this operation will raise a Python exception
        return op(
            self.__clause_element__(), *(self._decode(o) for o in other), **kwargs
        )


class SqlUuidHexComparator(SplitIndexComparator):
    """
    Given an ``uuid-text`` string, split out the UUID and allow comparisons on it.

    The UUID must be in hex format.

    Also supports ``text-uuid``, ``text-text-uuid`` or other specific locations for the
    UUID value if specified as a `splitindex` parameter to the constructor.
    """

    def _decode(self, other: Optional[Union[str, UUID]]) -> Optional[UUID]:
        if other is None:
            return None
        if not isinstance(other, UUID):
            if self.splitindex is not None:
                other = other.split(self.separator)[self.splitindex]
            return UUID(other)
        return other


class SqlUuidB64Comparator(SplitIndexComparator):
    """
    Given an ``uuid-text`` string, split out the UUID and allow comparisons on it.

    The UUID must be in URL-safe Base64 format.

    Also supports ``text-uuid``, ``text-text-uuid`` or other specific locations for the
    UUID value if specified as a `splitindex` parameter to the constructor.

    Note that the default separator from the base class is ``-``, which is also a
    valid character in URL-safe Base64, so a custom separator must be specified when
    using this comparator.
    """

    def _decode(self, other: Optional[Union[str, UUID]]) -> Optional[UUID]:
        if other is None:
            return None
        if not isinstance(other, UUID):
            if self.splitindex is not None:
                other = other.split(self.separator)[self.splitindex]
            return uuid_from_base64(other)
        return other


class SqlUuidB58Comparator(SplitIndexComparator):
    """
    Given an ``uuid-text`` string, split out the UUID and allow comparisons on it.

    The UUID must be in Base58 format.

    Also supports ``text-uuid``, ``text-text-uuid`` or other specific locations for the
    UUID value if specified as a `splitindex` parameter to the constructor.
    """

    def _decode(self, other: Optional[Union[str, UUID]]) -> Optional[UUID]:
        if other is None:
            return None
        if not isinstance(other, UUID):
            if self.splitindex is not None:
                other = other.split('-')[self.splitindex]
            return uuid_from_base58(other)
        return other
