"""
Immutable annotation
--------------------
"""

from sqlalchemy.orm.attributes import NEVER_SET, NO_VALUE
import sqlalchemy as sa

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

    def __init__(self, class_name, column_name, old_value, new_value, message=None):
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
def _make_immutable(cls):
    def add_immutable_event(attr, col):
        @sa.event.listens_for(col, 'set')
        def immutable_column_set_listener(target, value, old_value, initiator):
            # Note:
            # NEVER_SET is for columns getting a default value during a commit, but in
            # SQLAlchemy 1.4 it appears to also be used in place of NO_VALUE.
            # NO_VALUE is for columns that have no value (either never set, or not
            # loaded). Because of this ambiguity, we pair it with a
            # has_identity test.
            if old_value == value:
                pass
            elif (old_value is NEVER_SET or old_value is NO_VALUE) and sa.inspect(
                target
            ).has_identity is False:
                pass
            else:
                raise ImmutableColumnError(cls.__name__, attr, old_value, value)

    if (
        hasattr(cls, '__column_annotations__')
        and immutable.name in cls.__column_annotations__
    ):
        for attr in cls.__column_annotations__[immutable.name]:
            add_immutable_event(attr, getattr(cls, attr))
