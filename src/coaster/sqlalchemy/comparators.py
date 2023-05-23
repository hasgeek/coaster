"""
Enhanced query and custom comparators
-------------------------------------
"""

from __future__ import annotations

from typing import overload
from uuid import UUID
import typing as t

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


_T = t.TypeVar('_T', bound=t.Any)


class Query(QueryBase[_T]):  # pylint: disable=abstract-method
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
        # Pylint doesn't know abort is NoReturn
        return None  # type: ignore[unreachable]

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


class SplitIndexComparator(sa.ext.hybrid.Comparator):  # pylint: disable=abstract-method
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

    def _decode(self, other: str) -> t.Any:
        raise NotImplementedError

    def __eq__(self, other: t.Any) -> sa.ColumnElement[bool]:  # type: ignore[override]
        try:
            other = self._decode(other)
        except (ValueError, TypeError):
            # If other could not be decoded, we do not match.
            return sa.sql.expression.false()
        return self.__clause_element__() == other

    is_ = __eq__  # type: ignore[assignment]

    def __ne__(self, other: t.Any) -> sa.ColumnElement[bool]:  # type: ignore[override]
        try:
            other = self._decode(other)
        except (ValueError, TypeError):
            # If other could not be decoded, we are not equal.
            return sa.sql.expression.true()
        return self.__clause_element__() != other

    isnot = __ne__  # type: ignore[assignment]
    is_not = __ne__  # type: ignore[assignment]

    def in_(self, other: t.Any) -> sa.ColumnElement[bool]:  # type: ignore[override]
        """Check if self is present in the other."""

        def errordecode(otherlist: t.Any) -> t.Iterator[str]:
            for val in otherlist:
                try:
                    yield self._decode(val)
                except (ValueError, TypeError):
                    pass

        valid_values = list(errordecode(other))
        if not valid_values:
            # If none of the elements could be decoded, return false
            return sa.sql.expression.false()

        return self.__clause_element__().in_(valid_values)  # type: ignore[attr-defined]


class SqlSplitIdComparator(SplitIndexComparator):  # pylint: disable=abstract-method
    """
    Given an ``id-text`` string, split out the integer id and allows comparison on it.

    Also supports ``text-id``, ``text-text-id`` or other specific locations for the id
    if specified as a `splitindex` parameter to the constructor.

    This comparator will not attempt to decode non-string values, and will attempt to
    support all operators, accepting SQL expressions for :attr:`other`.
    """

    def _decode(self, other: t.Any) -> t.Union[int, t.Any]:
        if isinstance(other, str):
            if self.splitindex is not None:
                return int(other.split(self.separator)[self.splitindex])
            return int(other)
        return other

    # FIXME: The type of `op` is not known as the sample code is not type-annotated in
    # https://docs.sqlalchemy.org/en/20/orm/extensions/hybrid.html
    # #building-custom-comparators
    def operate(self, op: t.Any, *other: t.Any, **kwargs) -> sa.ColumnElement[t.Any]:
        """Perform SQL operation on decoded value for other."""
        # If `other` cannot be decoded, this operation will raise a Python exception
        return op(
            self.__clause_element__(), *(self._decode(o) for o in other), **kwargs
        )


class SqlUuidHexComparator(SplitIndexComparator):  # pylint: disable=abstract-method
    """
    Given an ``uuid-text`` string, split out the UUID and allow comparisons on it.

    The UUID must be in hex format.

    Also supports ``text-uuid``, ``text-text-uuid`` or other specific locations for the
    UUID value if specified as a `splitindex` parameter to the constructor.
    """

    def _decode(self, other: t.Optional[t.Union[str, UUID]]) -> t.Optional[UUID]:
        if other is None:
            return None
        if not isinstance(other, UUID):
            if self.splitindex is not None:
                other = other.split(self.separator)[self.splitindex]
            return UUID(other)
        return other


class SqlUuidB64Comparator(SplitIndexComparator):  # pylint: disable=abstract-method
    """
    Given an ``uuid-text`` string, split out the UUID and allow comparisons on it.

    The UUID must be in URL-safe Base64 format.

    Also supports ``text-uuid``, ``text-text-uuid`` or other specific locations for the
    UUID value if specified as a `splitindex` parameter to the constructor.

    Note that the default separator from the base class is ``-``, which is also a
    valid character in URL-safe Base64, so a custom separator must be specified when
    using this comparator.
    """

    def _decode(self, other: t.Optional[t.Union[str, UUID]]) -> t.Optional[UUID]:
        if other is None:
            return None
        if not isinstance(other, UUID):
            if self.splitindex is not None:
                other = other.split(self.separator)[self.splitindex]
            return uuid_from_base64(other)
        return other


class SqlUuidB58Comparator(SplitIndexComparator):  # pylint: disable=abstract-method
    """
    Given an ``uuid-text`` string, split out the UUID and allow comparisons on it.

    The UUID must be in Base58 format.

    Also supports ``text-uuid``, ``text-text-uuid`` or other specific locations for the
    UUID value if specified as a `splitindex` parameter to the constructor.
    """

    def _decode(self, other: t.Optional[t.Union[str, UUID]]) -> t.Optional[UUID]:
        if other is None:
            return None
        if not isinstance(other, UUID):
            if self.splitindex is not None:
                other = other.split('-')[self.splitindex]
            return uuid_from_base58(other)
        return other
