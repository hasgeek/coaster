"""
Flask-SQLAlchemy-compatible model base class
--------------------------------------------

Flask-SQLAlchemy's ``db.Model`` is not compatible with PEP 484 type hinting. Coaster
provides a replacement :class:`ModelBase` base class. To use, combine it with
SQLAlchemy's :class:`~sqlalchemy.orm.DeclarativeBase`. Given Flask-SQLAlchemy models
defined like this::

    from flask_sqlalchemy import SQLAlchemy

    db = SQLAlchemy()

    class MyModel(db.Model):
        others = db.relationship('Other', lazy='dynamic')

    class MyBindModel(db.Model):
        __bind_key__ = 'my_bind'

    class Other(db.Model):
        ...

Replace with::

    from typing import List
    from sqlalchemy.orm import DeclarativeBase, DynamicMapped
    from flask_sqlalchemy import SQLAlchemy
    from coaster.sqlalchemy import ModelBase, DeclarativeBase, relationship

    class Model(ModelBase, DeclarativeBase):  # ModelBase must be first
        pass

    class BindModel(ModelBase, DeclarativeBase):
        __bind_key__ = 'my_bind'

    class MyModel(Model):
        # __tablename__ is not autogenerated with ModelBase and must be specified
        __tablename__ = 'my_model'

        # Coaster's relationship supplies a default query_class matching
        # Flask-SQLAlchemy's, with methods like first_or_404 and one_or_404
        others: DynamicMapped[Other] = relationship('Other', lazy='dynamic')

    class MyBindModel(BindModel):
        __tablename__ = 'my_bind_model'

    class Other(Model):
        ...

    db = SQLAlchemy(metadata=Model.metadata)  # Use the base model's metadata
    Model.init_flask_sqlalchemy(db)
    BindModel.init_flask_sqlalchemy(db)

Flask-SQLAlchemy requires `db` to be initialized before models are defined. Coaster's
ModelBase removes that limitation, allowing class definition before instances are
created.
"""

from __future__ import annotations

from functools import wraps
from typing import cast
import datetime
import typing as t
import uuid
import warnings

from flask import abort
from flask_sqlalchemy import SQLAlchemy
from flask_sqlalchemy.pagination import Pagination, QueryPagination
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Query as QueryBase
from sqlalchemy.orm import backref as backref_base
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship as relationship_base
from sqlalchemy.orm.dynamic import AppenderMixin
import sqlalchemy as sa
import typing_extensions as te

_T = t.TypeVar('_T', bound=t.Any)

__all__ = [
    'ModelWarning',
    'bigint',
    'smallint',
    'int_pkey',
    'uuid4_pkey',
    'timestamp',
    'timestamp_now',
    'jsonb',
    'Query',
    'QueryProperty',
    'AppenderQuery',
    'ModelBase',
    'DeclarativeBase',
    'relationship',
    'backref',
]


class ModelWarning(UserWarning):
    """Warning for problematic use of ModelBase and relationship."""


bigint: te.TypeAlias = te.Annotated[int, mapped_column(sa.BigInteger())]
smallint: te.TypeAlias = te.Annotated[int, mapped_column(sa.SmallInteger())]
int_pkey: te.TypeAlias = te.Annotated[int, mapped_column(primary_key=True, init=False)]
uuid4_pkey: te.TypeAlias = te.Annotated[
    uuid.UUID, mapped_column(primary_key=True, default=uuid.uuid4, init=False)
]
timestamp: te.TypeAlias = te.Annotated[
    datetime.datetime, mapped_column(sa.TIMESTAMP(timezone=True))
]
timestamp_now: te.TypeAlias = te.Annotated[
    datetime.datetime,
    mapped_column(
        sa.TIMESTAMP(timezone=True),
        server_default=sa.func.CURRENT_TIMESTAMP(),
        nullable=False,
    ),
]
jsonb: te.TypeAlias = te.Annotated[
    dict, mapped_column(sa.JSON().with_variant(postgresql.JSONB, 'postgresql'))
]


class Query(QueryBase[_T]):  # pylint: disable=abstract-method
    """Extends SQLAlchemy's :class:`~sqlalchemy.orm.Query` with additional methods."""

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


# AppenderMixin and Query have different definitions for ``session``, so we have to ask
# Mypy to ignore it. Pylint and SQLAlchemy disagree on what abstract methods are for:
# Pylint thinks they should be implemented, but SQLAlchemy doesn't seem to want them
class AppenderQuery(  # type: ignore[misc]  # pylint: disable=abstract-method
    AppenderMixin[_T], Query[_T]
):
    """
    AppenderQuery, used by :func:`relationship` as the default query class.

    SQLAlchemy's :func:`~sqlalchemy.orm.relationship` will accept ``query_class=Query``
    directly, but will construct a new class mixing
    :func:`~sqlalchemy.orm.dynamic.AppenderMixin` and ``query_class`` if
    ``AppenderMixin`` is not in the existing base classes.
    """

    # AppenderMixin does not specify a type for query_class
    query_class = Query  # type: ignore[assignment]


class QueryProperty:
    """A class property that creates a query object for a model."""

    def __get__(self, _obj: t.Optional[_T], cls: t.Type[_T]) -> Query[_T]:
        return cls.query_class(cls, session=cls.__fsa__.session())


class ModelBase:
    """Flask-SQLAlchemy compatible base class that supports PEP 484 type hinting."""

    __fsa__: t.ClassVar[SQLAlchemy]
    __bind_key__: t.ClassVar[t.Optional[str]]
    metadata: t.ClassVar[sa.MetaData]
    query_class: t.ClassVar[type[Query]] = Query
    query: t.ClassVar[QueryProperty] = QueryProperty()
    # Added by Coaster annotations
    __column_annotations__: t.ClassVar[t.Dict[str, t.List[str]]]
    __column_annotations_by_attr__: t.ClassVar[t.Dict[str, t.List[str]]]

    def __init_subclass__(cls) -> None:
        """Configure a declarative base class."""
        if ModelBase in cls.__bases__:
            # If this is the base class (ModelBase is its immediate base class), set
            # cls.__bind_key__ to None
            if '__bind_key__' not in cls.__dict__:
                cls.__bind_key__ = None
            # Call super() to create a metadata (if not already specified in the class)
            super().__init_subclass__()
            # Replicate cls.__bind_key__ into the metadata's info dict, matching
            # Flask-SQLAlchemy's behaviour
            cls.metadata.info['bind_key'] = cls.__bind_key__
            return
        # This is a subclass. Get the effective __bind_key__, then find the top-level
        # base class that's the first descended from ModelBase and confirm it has the
        # same bind_key. There will be a mismatch if:
        #
        # 1. The subclass directly specifies __bind_key__ and it's different
        # 2. A mixin class introduced a different value for __bind_key__
        # 3. The value of __bind_key__ in an ancestor was changed after
        #    __init_subclass__ scanned it. We can't stop a programmer from shooting
        #   their own foot. At best, we can warn of an accidental error.
        bind_key = cls.__bind_key__
        for base in cls.mro():
            if ModelBase in base.__bases__:
                # We've found the direct subclass of ModelBase...
                base = cast(t.Type[ModelBase], base)  # ...but Mypy doesn't know yet
                if base.__bind_key__ == bind_key:
                    # There's a match. All good. Stop iterating through bases
                    break
                # The base class has a different bind key
                raise TypeError(
                    f"`{cls.__name__}.__bind_key__ = {bind_key!r}` does not match"
                    f" base class `{base.__name__}.__bind_key__ = "
                    f"{base.__bind_key__!r}`"
                )
        super().__init_subclass__()

    @classmethod
    def init_flask_sqlalchemy(cls, fsa: SQLAlchemy) -> None:
        """
        Link this Model base to Flask-SQLAlchemy.

        This classmethod must be called alongside db.init_app(app).
        """
        if ModelBase not in cls.__bases__:
            raise TypeError(
                "init_flask_sqlalchemy must be called on your base class only, not on"
                " ModelBase or a model"
            )
        if getattr(cls, '__fsa__', None) is not None:
            warnings.warn(
                f"{cls.__name__}.init_flask_sqlalchemy has already been called",
                RuntimeWarning,
                stacklevel=2,
            )
        cls.__fsa__ = fsa
        if (
            cls.__bind_key__ in fsa.metadatas
            and fsa.metadatas[cls.__bind_key__] is not cls.metadata
        ):
            if cls.__bind_key__ is None:
                raise TypeError(
                    f"Flask-SQLAlchemy has its own metadata. Use ``db = SQLAlchemy"
                    f"(metadata={cls.__name__}.metadata)`` to avoid this error"
                )
            raise TypeError(
                f"Flask-SQLAlchemy has different metadata from {cls.__name__} for"
                f" __bind_key__={cls.__bind_key__!r}. db.Model can only be used after"
                f" init_flask_sqlalchemy has been called"
            )
        if cls.__bind_key__ not in fsa.metadatas:
            fsa.metadatas[cls.__bind_key__] = cls.metadata

    def __repr__(self) -> str:
        """Provide a default repr string."""
        state = sa.inspect(self)
        if t.TYPE_CHECKING:
            assert state is not None  # nosec B101

        if state.transient:
            pk = f"(transient {id(self)})"
        elif state.pending:
            pk = f"(pending {id(self)})"
        else:
            pk = ", ".join(map(str, state.identity))

        return f'<{type(self).__name__} {pk}>'


_P = te.ParamSpec('_P')


# This wrapper exists solely for type hinting tools as @wraps itself does not
# provide type hints indicating that the function's type signature is unchanged
def _create_relationship_wrapper(f: t.Callable[_P, _T]) -> t.Callable[_P, _T]:
    """Create a wrapper for relationship."""

    @wraps(f)
    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        """Insert a default query_class when constructing a relationship."""
        if 'query_class' not in kwargs:
            kwargs['query_class'] = AppenderQuery
        if 'backref' in kwargs:
            warnings.warn(
                "backref is not compatible with type hinting. Use back_populates:"
                " https://docs.sqlalchemy.org/en/20/orm/backref.html",
                ModelWarning,
                stacklevel=2,
            )
        return f(*args, **kwargs)

    return wrapper


#: Wrap :func:`~sqlalchemy.orm.relationship` to insert :class:`Query` as the default
#: value for :attr:`query_class`
relationship = _create_relationship_wrapper(relationship_base)
#: Wrap :func:`~sqlalchemy.orm.backref` to insert :class:`Query` as the default
#: value for :attr:`query_class`
backref = _create_relationship_wrapper(backref_base)
