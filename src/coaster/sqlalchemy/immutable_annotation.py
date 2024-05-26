"""Immutable annotation."""

from __future__ import annotations

from typing import Any, Optional

import sqlalchemy as sa
import sqlalchemy.orm as sa_orm
from sqlalchemy.orm.attributes import NEVER_SET, NO_VALUE

from .annotations import annotation_wrapper, annotations_configured

__all__ = ['immutable', 'cached', 'ImmutableColumnError']


immutable = annotation_wrapper(
    'immutable',
    "Marks a column as immutable once set. "
    "Only blocks direct changes; columns may still be updated via relationships or SQL",
)
cached = annotation_wrapper(
    'cached', "Marks the column's contents as a cached value from another source"
)


class ImmutableColumnError(AttributeError):
    """Exception raised when an immutable column is set."""

    def __init__(
        self,
        class_name: str,
        column_name: str,
        old_value: Any,
        new_value: Any,
        message: Optional[str] = None,
    ) -> None:
        """Create exception."""
        if message is None:
            message = (
                f"Cannot update column {class_name}.{column_name} from {old_value!r} to"
                f" {new_value!r}: column is immutable."
            )
        super().__init__(message)
        self.class_name = class_name
        self.column_name = column_name
        self.old_value = old_value
        self.new_value = new_value


@annotations_configured.connect
def _make_immutable(cls: type[Any]) -> None:
    def add_immutable_event(attr: str, col: Any) -> None:
        @sa.event.listens_for(col, 'set', raw=True)
        def immutable_column_set_listener(  # skipcq: PTC-W0065
            target: sa_orm.InstanceState,
            value: Any,
            old_value: Any,
            _initiator: Any,
        ) -> None:
            # About old_value:
            # * Symbol NO_VALUE is for columns that have no value (either never set, or
            #   not loaded).
            # * Symbol NEVER_SET became an alias for NO_VALUE in SQLAlchemy >= 1.4 but
            #   previously indicated an unset value.
            # * When mapped as a dataclass, columns may have a default value of None.
            # Because of this ambiguity, we pair them with a test for persistence.
            if not (
                old_value == value
                or (
                    old_value in (NEVER_SET, NO_VALUE, None)
                    and target.persistent is False
                )
            ):
                raise ImmutableColumnError(cls.__name__, attr, old_value, value)

    if (
        hasattr(cls, '__column_annotations__')
        and immutable.__name__ in cls.__column_annotations__
    ):
        for attr in cls.__column_annotations__[immutable.__name__]:
            add_immutable_event(attr, getattr(cls, attr))
