"""
Enhanced query and custom comparators
-------------------------------------
"""

from __future__ import annotations

from typing import overload
import typing as t
import uuid as uuid_

from flask import abort
from flask_sqlalchemy.pagination import Pagination, QueryPagination
from sqlalchemy.orm.query import Query as QueryBase
import sqlalchemy as sa

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


_T = t.TypeVar('_T', bound=t.Any)


class Query(QueryBase[_T]):  # skipcq: PYL-W0223
    """Extends SQLAlchemy's Query to add additional helper methods."""

    def get_or_404(self, ident: t.Any, description: t.Optional[str] = None) -> _T:
        """
        Like :meth:`~sqlalchemy.orm.Query.get` but aborts with 404 if no result.

        :param ident: The primary key to query
        :param description: A custom message to show on the error page
        """
        rv = self.get(ident)

        if rv is None:
            abort(404, description=description)

        return rv

    def first_or_404(self, description: t.Optional[str] = None) -> _T:
        """
        Like :meth:`~sqlalchemy.orm.Query.first` but aborts with 404 if no result.

        :param description: A custom message to show on the error page
        """
        rv = self.first()

        if rv is None:
            abort(404, description=description)

        return rv

    def one_or_404(self, description: t.Optional[str] = None) -> _T:
        """
        Like :meth:`~sqlalchemy.orm.Query.one` but aborts with 404 instead of erroring.

        :param description: A custom message to show on the error page.
        """
        try:
            return self.one()
        except (sa.exc.NoResultFound, sa.exc.MultipleResultsFound):
            abort(404, description=description)

    def notempty(self) -> bool:
        """
        Return `True` if the query has non-zero results.

        Does the equivalent of ``bool(query.count())`` but using an efficient
        SQL EXISTS function, so the database stops counting after the first result
        is found.
        """
        return self.session.query(self.exists()).scalar()

    def isempty(self) -> bool:
        """
        Return `True` if the query has zero results.

        Does the equivalent of ``not bool(query.count())`` but using an efficient
        SQL EXISTS function, so the database stops counting after the first result
        is found.
        """
        return not self.session.query(self.exists()).scalar()

    # TODO: Pagination may not preserve model type information, affecting downstream
    # type validation
    def paginate(
        self,
        *,
        page: int | None = None,
        per_page: int | None = None,
        max_per_page: int | None = None,
        error_out: bool = True,
        count: bool = True,
    ) -> Pagination:
        """
        Apply an offset and limit to the query, returning a Pagination object.

        :param page: The current page, used to calculate the offset. Defaults to the
            ``page`` query arg during a request, or 1 otherwise
        :param per_page: The maximum number of items on a page, used to calculate the
            offset and limit. Defaults to the ``per_page`` query arg during a request,
            or 20 otherwise
        :param max_per_page: The maximum allowed value for ``per_page``, to limit a
            user-provided value. Use ``None`` for no limit. Defaults to 100
        :param error_out: Abort with a ``404 Not Found`` error if no items are returned
            and ``page`` is not 1, or if ``page`` or ``per_page`` is less than 1, or if
            either are not ints
        :param count: Calculate the total number of values by issuing an extra count
            query. For very complex queries this may be inaccurate or slow, so it can be
            disabled and set manually if necessary
        """
        return QueryPagination(
            query=self,
            page=page,
            per_page=per_page,
            max_per_page=max_per_page,
            error_out=error_out,
            count=count,
        )


class QueryProperty(t.Generic[_T]):
    """A class property that creates a query object for a model."""

    @overload
    def __get__(self, obj: None, cls: t.Type[_T]) -> Query[_T]:
        ...

    @overload
    def __get__(self, obj: _T, cls: t.Type[_T]) -> Query[_T]:
        ...

    def __get__(self, obj: t.Optional[_T], cls: t.Type[_T]) -> Query[_T]:
        return cls.query_class(cls, session=cls.__fsa__.session())


class SplitIndexComparator(sa.ext.hybrid.Comparator):
    """Base class for comparators that split a string and compare with one part."""

    def __init__(
        self,
        expression: t.Any,
        splitindex: t.Optional[int] = None,
        separator: str = '-',
    ) -> None:
        super().__init__(expression)
        self.splitindex = splitindex
        self.separator = separator

    def _decode(self, other):
        raise NotImplementedError

    def __eq__(self, other: t.Any) -> sa.ColumnElement[bool]:  # type: ignore[override]
        try:
            other = self._decode(other)
        except (ValueError, TypeError):
            # If other could not be decoded, we do not match.
            return sa.sql.expression.false()
        return self.__clause_element__() == other

    def __ne__(self, other: t.Any) -> sa.ColumnElement[bool]:  # type: ignore[override]
        try:
            other = self._decode(other)
        except (ValueError, TypeError):
            # If other could not be decoded, we are not equal.
            return sa.sql.expression.true()
        return self.__clause_element__() != other

    def in_(self, other: t.Any) -> sa.BinaryExpression[bool]:
        """Check if self is present in the other."""

        def errordecode(val):
            try:
                return self._decode(val)
            except (ValueError, TypeError):
                # If value could not be decoded, return a special marker object
                return _marker

        # Make list of comparison values, removing undecipherable values (marker object)
        otherlist = (v for v in (errordecode(val) for val in other) if v is not _marker)
        return self.__clause_element__().in_(otherlist)  # type: ignore[attr-defined]


class SqlSplitIdComparator(SplitIndexComparator):
    """
    Given an ``id-text`` string, split out the integer id and allows comparison on it.

    Also supports ``text-id``, ``text-text-id`` or other specific locations for the id
    if specified as a `splitindex` parameter to the constructor.
    """

    def _decode(self, other: t.Optional[str]) -> t.Optional[int]:
        if other is None:
            return None
        if self.splitindex is not None and isinstance(other, str):
            return int(other.split(self.separator)[self.splitindex])
        return int(other)


class SqlUuidHexComparator(SplitIndexComparator):
    """
    Given an ``uuid-text`` string, split out the UUID and allow comparisons on it.

    The UUID must be in hex format.

    Also supports ``text-uuid``, ``text-text-uuid`` or other specific locations for the
    UUID value if specified as a `splitindex` parameter to the constructor.
    """

    def _decode(
        self, other: t.Optional[t.Union[str, uuid_.UUID]]
    ) -> t.Optional[uuid_.UUID]:
        if other is None:
            return None
        if not isinstance(other, uuid_.UUID):
            if self.splitindex is not None:
                other = other.split(self.separator)[self.splitindex]
            return uuid_.UUID(other)
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

    def _decode(
        self, other: t.Optional[t.Union[str, uuid_.UUID]]
    ) -> t.Optional[uuid_.UUID]:
        if other is None:
            return None
        if not isinstance(other, uuid_.UUID):
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

    def _decode(
        self, other: t.Optional[t.Union[str, uuid_.UUID]]
    ) -> t.Optional[uuid_.UUID]:
        if other is None:
            return None
        if not isinstance(other, uuid_.UUID):
            if self.splitindex is not None:
                other = other.split('-')[self.splitindex]
            return uuid_from_base58(other)
        return other
