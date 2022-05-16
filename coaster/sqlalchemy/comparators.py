"""
Enhanced query and custom comparators
-------------------------------------
"""

from typing import Optional
import uuid as uuid_

from flask_sqlalchemy import BaseQuery
from sqlalchemy.ext.hybrid import Comparator

from flask import abort

from ..utils import uuid_from_base58, uuid_from_base64

__all__ = [
    'Query',
    'SplitIndexComparator',
    'SqlSplitIdComparator',
    'SqlUuidHexComparator',
    'SqlUuidB64Comparator',
    'SqlUuidB58Comparator',
]


_marker = object()


class Query(BaseQuery):
    """Extends flask_sqlalchemy.BaseQuery to add additional helper methods."""

    def notempty(self):
        """
        Return `True` if the query has non-zero results.

        Does the equivalent of ``bool(query.count())`` but using an efficient
        SQL EXISTS function, so the database stops counting after the first result
        is found.
        """
        return self.session.query(self.exists()).scalar()

    def isempty(self):
        """
        Return `True` if the query has zero results.

        Does the equivalent of ``not bool(query.count())`` but using an efficient
        SQL EXISTS function, so the database stops counting after the first result
        is found.
        """
        return not self.session.query(self.exists()).scalar()

    def one_or_404(self):
        """
        Return exactly one result, or abort with 404 if zero are found.

        Extends :meth:`~sqlalchemy.orm.query.Query.one_or_none` to raise a 404
        if no result is found. This method offers a safety net over
        :meth:`~flask_sqlalchemy.BaseQuery.first_or_404` as it helps identify
        poorly specified queries that could have returned more than one result.
        """
        result = self.one_or_none()
        if not result:
            abort(404)
        return result


class SplitIndexComparator(Comparator):
    """Base class for comparators that split a string and compare with one part."""

    def __init__(
        self, expression, splitindex: Optional[int] = None, separator: str = '-'
    ):
        super().__init__(expression)
        self.splitindex = splitindex
        self.separator = separator

    def _decode(self, other):
        raise NotImplementedError

    def __eq__(self, other):
        try:
            other = self._decode(other)
        except (ValueError, TypeError):
            # If other could not be decoded, we do not match.
            return False
        return self.__clause_element__() == other

    def __ne__(self, other):
        try:
            other = self._decode(other)
        except (ValueError, TypeError):
            # If other could not be decoded, we are not equal.
            return True
        return self.__clause_element__() != other

    def in_(self, other):
        """Check if self is present in the other."""

        def errordecode(val):
            try:
                return self._decode(val)
            except (ValueError, TypeError):
                # If value could not be decoded, return a special marker object
                return _marker

        # Make list of comparison values, removing undecipherable values (marker object)
        otherlist = (v for v in (errordecode(val) for val in other) if v is not _marker)
        return self.__clause_element__().in_(otherlist)


class SqlSplitIdComparator(SplitIndexComparator):
    """
    Given an ``id-text`` string, split out the integer id and allows comparison on it.

    Also supports ``text-id``, ``text-text-id`` or other specific locations for the id
    if specified as a `splitindex` parameter to the constructor.
    """

    def _decode(self, other):
        if other is None:
            return
        if self.splitindex is not None and isinstance(other, str):
            other = int(other.split(self.separator)[self.splitindex])
        return other


class SqlUuidHexComparator(SplitIndexComparator):
    """
    Given an ``uuid-text`` string, split out the UUID and allow comparisons on it.

    The UUID must be in hex format.

    Also supports ``text-uuid``, ``text-text-uuid`` or other specific locations for the
    UUID value if specified as a `splitindex` parameter to the constructor.
    """

    def _decode(self, other):
        if other is None:
            return
        if not isinstance(other, uuid_.UUID):
            if self.splitindex is not None:
                other = other.split(self.separator)[self.splitindex]
            other = uuid_.UUID(other)
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

    def _decode(self, other):
        if other is None:
            return
        if not isinstance(other, uuid_.UUID):
            if self.splitindex is not None:
                other = other.split(self.separator)[self.splitindex]
            other = uuid_from_base64(other)
        return other


class SqlUuidB58Comparator(SplitIndexComparator):
    """
    Given an ``uuid-text`` string, split out the UUID and allow comparisons on it.

    The UUID must be in Base58 format.

    Also supports ``text-uuid``, ``text-text-uuid`` or other specific locations for the
    UUID value if specified as a `splitindex` parameter to the constructor.
    """

    def _decode(self, other):
        if other is None:
            return
        if not isinstance(other, uuid_.UUID):
            if self.splitindex is not None:
                other = other.split('-')[self.splitindex]
            other = uuid_from_base58(other)
        return other
