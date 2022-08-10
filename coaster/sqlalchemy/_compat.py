"""Compatibility with SQLAlchemy typing between two mypy plugins."""

import typing as t

__all__ = ['Mapped', 'declarative_mixin', 'declared_attr', 'hybrid_property']

if not t.TYPE_CHECKING:
    from sqlalchemy.ext.hybrid import hybrid_property
    from sqlalchemy.orm import declarative_mixin, declared_attr
else:
    from sqlalchemy.ext.declarative import declared_attr

    hybrid_property = property
    try:
        # sqlalchemy-stubs (by Dropbox) can't find declarative_mixin, but
        # sqlalchemy2-stubs (by SQLAlchemy) requires it
        from sqlalchemy.orm import declarative_mixin  # type: ignore[attr-defined]
    except ImportError:
        # pylint: disable=function-redefined
        T = t.TypeVar('T')

        def declarative_mixin(cls: T) -> T:
            """Decorate a mixin class as a declarative mixin for SQLAlchemy models."""
            return cls


try:
    from sqlalchemy.orm import Mapped  # type: ignore[attr-defined]
except ImportError:
    # sqlalchemy-stubs (by Dropbox) doesn't define Mapped
    # sqlalchemy2-stubs (by SQLAlchemy) does. Redefine if not known here:
    from sqlalchemy.orm.attributes import QueryableAttribute

    # pylint: disable=too-many-ancestors
    class Mapped(QueryableAttribute, t.Generic[T]):  # type: ignore[no-redef]
        """Replacement for sqlalchemy's Mapped type, for when not using the plugin."""

        def __get__(self, instance, owner):
            raise NotImplementedError()

        def __set__(self, instance, value):
            raise NotImplementedError()

        def __delete__(self, instance):
            raise NotImplementedError()
