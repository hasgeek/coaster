"""Legacy Query API with additional methods."""

from __future__ import annotations

import warnings
from collections.abc import Collection
from functools import wraps
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Optional,
    TypeVar,
    Union,
    cast,
    overload,
)
from typing_extensions import ParamSpec

from sqlalchemy import ColumnExpressionArgument
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import (
    DynamicMapped as DynamicMappedBase,
    InstrumentedAttribute,
    Query as QueryBase,
    Relationship as RelationshipBase,
    backref as backref_base,
    relationship as relationship_base,
)
from sqlalchemy.orm.dynamic import AppenderMixin

from ..compat import abort
from .pagination import QueryPagination

__all__ = [
    'BackrefWarning',
    'ModelWarning',
    'Query',
    'AppenderQuery',
    'QueryProperty',
    'DynamicMapped',
    'Relationship',
    'relationship',
    'backref',
]

_T = TypeVar('_T', bound=Any)
_T_co = TypeVar("_T_co", bound=Any, covariant=True)

# --- Warnings -------------------------------------------------------------------------


class BackrefWarning(UserWarning):
    """Warning for type-unfriendly use of ``backref`` in a :func:`relationship`."""


# Legacy name, do not use in new code
ModelWarning = BackrefWarning


# --- Query class and property ---------------------------------------------------------
# Change Query's Generic type to be covariant. This needed because:
# 1. When using SQLAlchemy polymorphism, a query on the base type may return a subtype.
# 2. For typing, a classmethod that returns Query[Self] will be deemed incompatible with
#    Query[HostModel] as Query[HostModel] != Query[Self@HostModel] because Self could be
#    a subclass.
class Query(QueryBase[_T_co]):  # type: ignore[type-var]
    """Extends SQLAlchemy's :class:`~sqlalchemy.orm.Query` with additional methods."""

    if TYPE_CHECKING:
        # The calls to super() here will never happen. They are to aid the programmer
        # using an editor's "Go to Definition" feature

        def get(self, ident: Any) -> Optional[_T_co]:
            """Provide type hint certifying that `get` returns `_T_co | None`."""
            return super().get(ident)

        def first(self) -> Optional[_T_co]:
            """Provide type hint certifying that `first` returns `_T_co | None`."""
            return super().first()

        def one(self) -> _T_co:
            """Provide type hint certifying that `one` returns `_T_co`."""
            return super().one()

        def add_columns(self, *column: ColumnExpressionArgument[Any]) -> Query[Any]:
            """Fix type hint to refer to :class:`Query`."""
            # pylint: disable=useless-parent-delegation
            return super().add_columns(*column)  # type: ignore[return-value]

        def with_transformation(
            self, fn: Callable[[QueryBase[Any]], QueryBase[Any]]
        ) -> Query[Any]:
            """Fix type hint to refer to :class:`Query`."""
            return super().with_transformation(fn)  # type: ignore[return-value]

    def get_or_404(self, ident: Any, description: Optional[str] = None) -> _T_co:
        """
        Like :meth:`~sqlalchemy.orm.Query.get` but aborts with 404 if no result.

        :param ident: The primary key to query
        :param description: A custom message to show on the error page
        """
        rv = self.get(ident)

        if rv is None:
            abort(404, description=description)

        return rv

    def first_or_404(self, description: Optional[str] = None) -> _T_co:
        """
        Like :meth:`~sqlalchemy.orm.Query.first` but aborts with 404 if no result.

        :param description: A custom message to show on the error page
        """
        rv = self.first()

        if rv is None:
            abort(404, description=description)

        return rv

    def one_or_404(self, description: Optional[str] = None) -> _T_co:
        """
        Like :meth:`~sqlalchemy.orm.Query.one`, but aborts with 404 for NoResultFound.

        Unlike Flask-SQLAlchemy's implementation,
        :exc:`~sqlalchemy.exc.MultipleResultsFound` is not recast as 404 and will cause
        a 500 error if not handled. The query may need additional filters to target a
        single result.

        :param description: A custom message to show on the error page
        """
        try:
            return self.one()
        except NoResultFound:
            abort(404, description=description)
        # Pylint doesn't know abort is NoReturn
        return None  # type: ignore[unreachable]

    def notempty(self) -> bool:
        """
        Return `True` if the query has non-zero results.

        Does the equivalent of ``bool(query.count())`` but using an efficient
        SQL EXISTS operator, so the database stops counting after the first result
        is found.
        """
        return self.session.query(self.exists()).scalar()

    def isempty(self) -> bool:
        """
        Return `True` if the query has zero results.

        Does the equivalent of ``not bool(query.count())`` but using an efficient
        SQL EXISTS operator, so the database stops counting after the first result
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
    ) -> QueryPagination[_T_co]:
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


# AppenderMixin and Query have different definitions for ``session``, so we have to ask
# Mypy to ignore it [misc]. SQLAlchemy defines the generic type as invariant but we
# change it to covariant, so we need an ignore that too [type-var].
class AppenderQuery(AppenderMixin[_T_co], Query[_T_co]):  # type: ignore[misc,type-var]
    """
    AppenderQuery, used by :func:`relationship` as the default query class.

    SQLAlchemy's :func:`~sqlalchemy.orm.relationship` will accept ``query_class=Query``
    directly, but will construct a new class mixing
    :func:`~sqlalchemy.orm.dynamic.AppenderMixin` and ``query_class`` if
    ``AppenderMixin`` is not in the existing base classes.
    """

    # AppenderMixin does not specify a type for query_class
    query_class: Optional[type[Query[_T_co]]] = Query


class QueryProperty:
    """A class property that creates a query object for a model."""

    def __get__(self, _obj: Optional[_T_co], cls: type[_T_co]) -> Query[_T_co]:
        return cls.query_class(cls, session=cls.__sqla__.session())


# --- `relationship` and `backref` wrappers for `lazy='dynamic'` -----------------------

# DynamicMapped and Relationship are redefined from the original in SQLAlchemy to offer
# a type hint to Coaster's AppenderQuery, which in turn wraps Coaster's Query with its
# additional methods

if TYPE_CHECKING:

    class DynamicMapped(DynamicMappedBase[_T_co]):
        """Represent the ORM mapped attribute type for a "dynamic" relationship."""

        __slots__ = ()

        @overload  # type: ignore[override]
        def __get__(
            self, instance: None, owner: Any
        ) -> InstrumentedAttribute[_T_co]: ...

        @overload
        def __get__(self, instance: object, owner: Any) -> AppenderQuery[_T_co]: ...

        def __get__(
            self, instance: Optional[object], owner: Any
        ) -> Union[InstrumentedAttribute[_T_co], AppenderQuery[_T_co]]: ...

        def __set__(self, instance: Any, value: Collection[_T_co]) -> None: ...

    class Relationship(RelationshipBase[_T], DynamicMapped[_T]):  # type: ignore[misc]
        """Wraps Relationship with the updated version of DynamicMapped."""

else:
    # Avoid the overhead of empty subclasses at runtime
    DynamicMapped = DynamicMappedBase
    Relationship = RelationshipBase


_P = ParamSpec('_P')


# This wrapper exists solely for type hinting tools as @wraps itself does not
# provide type hints indicating that the function's type signature is unchanged
def _create_relationship_wrapper(f: Callable[_P, Any]) -> Callable[_P, Relationship]:
    """Create a wrapper for relationship."""

    @wraps(f)
    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> Relationship:
        """Insert a default query_class when constructing a relationship."""
        if 'query_class' not in kwargs:
            kwargs['query_class'] = AppenderQuery
        if 'backref' in kwargs:
            warnings.warn(
                "`backref` is not compatible with type hinting. Use `back_populates`:"
                " https://docs.sqlalchemy.org/en/20/orm/backref.html",
                BackrefWarning,
                stacklevel=2,
            )
        return cast(Relationship, f(*args, **kwargs))

    return wrapper


# `backref` does not change return type, unlike `relationship`
def _create_backref_wrapper(f: Callable[_P, _T]) -> Callable[_P, _T]:
    """Create a wrapper for `backref`."""

    @wraps(f)
    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        """Insert a default query_class when constructing a `backref`."""
        if 'query_class' not in kwargs:
            kwargs['query_class'] = AppenderQuery
        return f(*args, **kwargs)

    return wrapper


#: Wrap :func:`~sqlalchemy.orm.relationship` to insert :class:`Query` as the default
#: value for :attr:`query_class`
relationship = _create_relationship_wrapper(relationship_base)
#: Wrap :func:`~sqlalchemy.orm.backref` to insert :class:`Query` as the default
#: value for :attr:`query_class`
backref = _create_backref_wrapper(backref_base)
