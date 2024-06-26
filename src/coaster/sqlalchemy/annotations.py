"""
SQLAlchemy attribute annotations.

Annotations are strings attached to attributes that serve as a programmer
reference on how those attributes are meant to be used. They can be used to
indicate that a column's value should be :attr:`immutable` and should never
change, or that it's a :attr:`cached` copy of a value from another source
that can be safely discarded in case of a conflict.

This module's exports may be imported via :mod:`coaster.sqlalchemy`.

Sample usage::

    import sqlalchemy as sa
    from sqlalchemy.orm import Mapped, mapped_column
    from coaster.sqlalchemy import annotation_wrapper, immutable
    from . import Model

    natural_key = annotation_wrapper('natural_key', "Natural key for this model")


    class MyModel(Model):
        __tablename__ = 'my_model'
        id: Mapped[int] = immutable(mapped_column(sa.Integer, primary_key=True))
        name: Mapped[str] = natural_key(mapped_column(sa.Unicode(250), unique=True))

        @classmethod
        def get(cls, **kwargs):
            for key in kwargs:
                if key in cls.__column_annotations__[natural_key.name]:
                    return cls.query.filter_by(**{key: kwargs[key]}).one_or_none()

Annotations are saved to the model's class as a ``__column_annotations__``
dictionary, mapping annotation names to a list of attribute names, and to a
reverse lookup ``__column_annotations_by_attr__`` of attribute names to annotations.

.. deprecated:: 0.7.0
    This module is due to be replaced with typing.Annotated
"""

from __future__ import annotations

from collections.abc import Hashable
from typing import Any, Callable, Optional, TypeVar

import sqlalchemy as sa
from sqlalchemy.orm import (
    ColumnProperty,
    MappedColumn,
    Mapper,
    MapperProperty,
    RelationshipProperty,
    SynonymProperty,
)
from sqlalchemy.orm.attributes import QueryableAttribute
from sqlalchemy.schema import SchemaItem

from ..signals import coaster_signals

__all__ = ['annotations_configured', 'annotation_wrapper']

# Global dictionary for temporary storage of annotations until the
# mapper_configured events
__cache__: dict[Any, list] = {}

# --- Constructor ----------------------------------------------------------------------


_A = TypeVar('_A', bound=Any)


def annotation_wrapper(
    annotation: str, doc: Optional[str] = None
) -> Callable[[_A], _A]:
    """Define an annotation, which can be applied to attributes in a database model."""

    def decorator(attr: _A) -> _A:
        __cache__.setdefault(attr, []).append(annotation)
        # Also mark the annotation on the object itself. This will
        # fail if the object has a restrictive __slots__, but it's
        # required for some objects like Column because SQLAlchemy copies
        # them in subclasses, changing their hash and making them
        # undiscoverable via the cache.
        if isinstance(attr, SynonymProperty):
            raise TypeError(
                "Synonyms cannot have annotations; set it on the referred attribute"
            )
        if isinstance(attr, MappedColumn):
            # pylint: disable=protected-access
            if not hasattr(attr.column, '_coaster_annotations'):
                attr.column._coaster_annotations = []  # type: ignore[attr-defined]
            attr.column._coaster_annotations.append(annotation)

        if isinstance(attr, (SchemaItem, ColumnProperty, MapperProperty)):
            attr.info.setdefault('_coaster_annotations', []).append(annotation)
        else:
            try:
                # pylint: disable=protected-access
                if not hasattr(attr, '_coaster_annotations'):
                    attr._coaster_annotations = []
                attr._coaster_annotations.append(annotation)
            except AttributeError:
                pass
        return attr

    decorator.__name__ = annotation
    decorator.__doc__ = doc
    return decorator


# --- Signals --------------------------------------------------------------------------

annotations_configured = coaster_signals.signal(
    'annotations-configured',
    doc="Signal raised after all annotations on a class are configured",
)


# --- Annotation processor -------------------------------------------------------------


@sa.event.listens_for(Mapper, 'mapper_configured')
def _configure_annotations(_mapper: Any, cls: type[Any]) -> None:
    """
    Extract annotations from attributes.

    Run through attributes of the class looking for annotations from
    :func:`annotation_wrapper` and add them to :attr:`cls.__column_annotations__`
    and :attr:`cls.__column_annotations_by_attr__`
    """
    annotations: dict[str, list[str]] = {}  # Annotation name: list of attrs
    annotations_by_attr: dict[str, list[str]] = {}  # Attr name: annotations

    # An attribute may be defined more than once in base classes. Only handle the first
    processed = set()

    # Loop through all attributes in the class and its base classes,
    # looking for annotations
    for base in cls.__mro__:
        for name, attr in base.__dict__.items():
            # pylint: disable=protected-access
            if name in processed or name.startswith('__'):
                continue

            if isinstance(attr, Hashable) and attr in __cache__:
                data = __cache__[attr]
            elif isinstance(attr, QueryableAttribute) and isinstance(
                getattr(attr, 'original_property', None), SynonymProperty
            ):
                # Skip synonyms
                data = None
            # 'data' is a list of string annotations
            elif isinstance(attr, MappedColumn) and hasattr(
                attr.column, '_coaster_annotations'
            ):
                data = attr.column._coaster_annotations
            elif hasattr(attr, '_coaster_annotations'):
                # pylint: disable=protected-access
                data = attr._coaster_annotations
            elif isinstance(
                attr, (QueryableAttribute, RelationshipProperty, MapperProperty)
            ):
                if attr.property in __cache__:
                    data = __cache__[attr.property]
                elif '_coaster_annotations' in attr.info:
                    data = attr.info['_coaster_annotations']
                elif hasattr(attr.property, '_coaster_annotations'):
                    # pylint: disable=protected-access
                    data = attr.property._coaster_annotations
                else:
                    data = None
            else:
                data = None
            if data is not None:
                annotations_by_attr.setdefault(name, []).extend(data)
                for a in data:
                    annotations.setdefault(a, []).append(name)
                processed.add(name)

    # Classes specifying ``__column_annotations__`` directly isn't supported,
    # so we don't bother preserving existing content, if any.
    if annotations:
        cls.__column_annotations__ = annotations
    if annotations_by_attr:
        cls.__column_annotations_by_attr__ = annotations_by_attr
    annotations_configured.send(cls)
