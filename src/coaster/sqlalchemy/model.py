"""
Flask-SQLAlchemy-compatible model base class.

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


    class Other(db.Model): ...

Replace with::

    from flask_sqlalchemy import SQLAlchemy
    from sqlalchemy.orm import DeclarativeBase
    from coaster.sqlalchemy import DynamicMapped, ModelBase, Query, relationship


    # Declare your base model. `ModelBase` must be before `DeclarativeBase` in bases:
    class Model(ModelBase, DeclarativeBase):
        pass


    # Declare additional base models for distinct bind keys as necessary:
    class BindModel(ModelBase, DeclarativeBase):
        __bind_key__ = 'my_bind'


    # Inherit from your base model:
    class MyModel(Model):
        # `__tablename__` is not autogenerated with ModelBase and must be specified
        __tablename__ = 'my_model'

        # Coaster's relationship supplies a default query_class matching
        # Flask-SQLAlchemy's for dynamic relationships, with methods like `first_or_404`
        # and `one_or_404`. To get the correct type hints, `DynamicMapped` (and
        # `backref` if required) must also be imported from Coaster.
        others: DynamicMapped['Other'] = relationship(lazy='dynamic')


    # Models using a different bind key must inherit from the bind-specific base model
    # and should not specify `__bind_key__` directly:
    class MyBindModel(BindModel):
        __tablename__ = 'my_bind_model'


    class Other(Model): ...


    # Finally create the Flask-SQLAlchemy object and link it to the model base(s):
    db = SQLAlchemy(
        metadata=Model.metadata,  # Use the base model's metadata
        query_class=Query,  # Use Coaster's query class (may need a type-ignore)
    )
    Model.init_flask_sqlalchemy(db)
    BindModel.init_flask_sqlalchemy(db)

Flask-SQLAlchemy requires `db` to be initialized before models are defined. Coaster's
ModelBase removes that limitation, allowing class definition before instances are
created.
"""

from __future__ import annotations

import datetime
import uuid
import warnings
from typing import TYPE_CHECKING, Annotated, ClassVar, Optional, cast
from typing_extensions import TypeAlias

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, mapped_column

from .query import Query, QueryProperty

if TYPE_CHECKING:
    from flask_sqlalchemy import SQLAlchemy as FlaskSQLAlchemy

__all__ = [
    'bigint',
    'smallint',
    'int_pkey',
    'uuid4_pkey',
    'timestamp',
    'timestamp_now',
    'jsonb',
    'ModelBase',
    'DeclarativeBase',  # From SQLAlchemy, re-exported for convenience
]

# --- SQLAlchemy type aliases ----------------------------------------------------------

bigint: TypeAlias = Annotated[int, mapped_column(sa.BigInteger())]  # noqa: PYI042
smallint: TypeAlias = Annotated[int, mapped_column(sa.SmallInteger())]  # noqa: PYI042
int_pkey: TypeAlias = Annotated[int, mapped_column(primary_key=True)]  # noqa: PYI042
uuid4_pkey: TypeAlias = Annotated[  # noqa: PYI042
    uuid.UUID,
    mapped_column(primary_key=True, insert_default=uuid.uuid4),
]
timestamp: TypeAlias = Annotated[  # noqa: PYI042
    datetime.datetime, mapped_column(sa.TIMESTAMP(timezone=True))
]
timestamp_now: TypeAlias = Annotated[  # noqa: PYI042
    datetime.datetime,
    mapped_column(
        sa.TIMESTAMP(timezone=True),
        server_default=sa.func.CURRENT_TIMESTAMP(),
        nullable=False,
    ),
]
jsonb: TypeAlias = Annotated[  # noqa: PYI042
    dict, mapped_column(sa.JSON().with_variant(postgresql.JSONB, 'postgresql'))
]

# --- Model base for Flask-SQLAlchemy compatibility ------------------------------------


class ModelBase:
    """Flask-SQLAlchemy compatible base class that supports PEP 484 type hinting."""

    __fsa__: ClassVar[FlaskSQLAlchemy]
    __bind_key__: ClassVar[Optional[str]]
    metadata: ClassVar[sa.MetaData]
    query_class: ClassVar[type[Query]] = Query
    query: ClassVar[QueryProperty] = QueryProperty()
    # Added by Coaster annotations
    __column_annotations__: ClassVar[dict[str, list[str]]]
    __column_annotations_by_attr__: ClassVar[dict[str, list[str]]]

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
        for base in cls.__mro__:
            if ModelBase in base.__bases__:
                # We've found the direct subclass of ModelBase...
                base = cast(type[ModelBase], base)  # ...but Mypy doesn't know yet
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
    def init_flask_sqlalchemy(cls, fsa: FlaskSQLAlchemy) -> None:
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
        if state is None:
            return super().__repr__()
        if state.transient:
            pk = f"(transient {id(self)})"
        elif state.pending:
            pk = f"(pending {id(self)})"
        else:
            pk = ", ".join(map(str, state.identity))

        return f'<{type(self).__qualname__} {pk}>'
