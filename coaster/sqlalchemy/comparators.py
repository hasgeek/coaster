"""
Enhanced query and custom comparators
-------------------------------------
"""

from __future__ import absolute_import

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


class Query(BaseQuery):
    """
    Extends flask_sqlalchemy.BaseQuery to add additional helper methods.
    """

    def notempty(self):
        """
        Returns the equivalent of ``bool(query.count())`` but using an efficient
        SQL EXISTS function, so the database stops counting after the first result
        is found.
        """
        return self.session.query(self.exists()).scalar()

    def isempty(self):
        """
        Returns the equivalent of ``not bool(query.count())`` but using an efficient
        SQL EXISTS function, so the database stops counting after the first result
        is found.
        """
        return not self.session.query(self.exists()).scalar()

    def one_or_404(self):
        """
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
    """
    Base class for comparators that support splitting a string and
    comparing with one of the split values.
    """

    def __init__(self, expression, splitindex=None):
        super(SplitIndexComparator, self).__init__(expression)
        self.splitindex = splitindex

    def _decode(self, other):
        raise NotImplementedError

    def __eq__(self, other):
        try:
            other = self._decode(other)
        except (ValueError, TypeError):
            return False
        return self.__clause_element__() == other

    def __ne__(self, other):
        try:
            other = self._decode(other)
        except (ValueError, TypeError):
            return True
        return self.__clause_element__() != other

    def in_(self, other):
        _marker = []

        def errordecode(val):
            try:
                return self._decode(val)
            except (ValueError, TypeError):
                return _marker

        otherlist = (v for v in (errordecode(val) for val in other) if v is not _marker)
        return self.__clause_element__().in_(otherlist)


class SqlSplitIdComparator(SplitIndexComparator):
    """
    Allows comparing an id value with a column, useful mostly because of
    the splitindex feature, which splits an incoming string along the ``-``
    character and picks one of the splits for comparison.
    """

    def _decode(self, other):
        if other is None:
            return
        if self.splitindex is not None and isinstance(other, str):
            other = int(other.split('-')[self.splitindex])
        return other


class SqlUuidHexComparator(SplitIndexComparator):
    """
    Allows comparing UUID fields with hex representations of the UUID
    """

    def _decode(self, other):
        if other is None:
            return
        if not isinstance(other, uuid_.UUID):
            if self.splitindex is not None:
                other = other.split('-')[self.splitindex]
            other = uuid_.UUID(other)
        return other


class SqlUuidB64Comparator(SplitIndexComparator):
    """
    Allows comparing UUID fields with URL-safe Base64 (BUID) representations
    of the UUID
    """

    def _decode(self, other):
        if other is None:
            return
        if not isinstance(other, uuid_.UUID):
            if self.splitindex is not None:
                other = other.split('-')[self.splitindex]
            other = uuid_from_base64(other)
        return other


class SqlUuidB58Comparator(SplitIndexComparator):
    """Allows comparing UUID fields with Base58 representations of the UUID"""

    def _decode(self, other):
        if other is None:
            return
        if not isinstance(other, uuid_.UUID):
            if self.splitindex is not None:
                other = other.split('-')[self.splitindex]
            other = uuid_from_base58(other)
        return other
