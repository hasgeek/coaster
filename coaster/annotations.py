# -*- coding: utf-8 -*-

"""
SQLAlchemy column annotations
=============================
"""

from __future__ import absolute_import
import collections
from copy import deepcopy
from blinker import Namespace
from sqlalchemy import event
from sqlalchemy.orm import mapper
from sqlalchemy.orm.attributes import QueryableAttribute
from sqlalchemy.util.langhelpers import symbol

__all__ = [
    'annotations_configured', 'AnnotationMixin',
    'annotation_wrapper', 'immutable', 'cached',
    'ImmutableColumnError'
    ]

# Global dictionary for temporary storage of annotations until the mapper_configured events
__cache__ = {}

# --- Signals -----------------------------------------------------------------

annotation_signals = Namespace()
annotations_configured = annotation_signals.signal('annotations-configured',
    doc="Signal raised after all annotations on a class are configured")


# --- Base class --------------------------------------------------------------

class AnnotationMixin(object):
    """
    Base class for models that allow annotations on columns.
    """

    __annotations_by_attr__ = {}
    __annotations__ = {}


# --- SQLAlchemy signals for base class ---------------------------------------

@event.listens_for(AnnotationMixin, 'mapper_configured', propagate=True)
def __configure_annotations(mapper, cls):
    """
    Run through attributes of the class looking for annotations from
    :func:`annotation_wrapper` and add them to :attr:`cls.__annotations__`
    and :attr:`cls.__annotations_by_attr__`
    """
    # Don't mutate dictionaries in the base class.
    # The subclass must have its own.
    # If the following lines are confusing, it's because reading an
    # attribute on an object invokes the Method Resolution Order (MRO)
    # mechanism to find it on base classes, while writing always writes
    # to the current object.
    if '__annotations__' not in cls.__dict__:
        cls.__annotations__ = deepcopy(cls.__annotations__)
    if '__annotations_by_attr__' not in cls.__dict__:
        cls.__annotations_by_attr__ = deepcopy(cls.__annotations_by_attr__)

    # An attribute may be defined more than once in base classes. Only handle the first
    processed = set()

    # Loop through all attributes in the class and its base classes, looking for annotations
    for base in cls.__mro__:
        for name, attr in base.__dict__.items():
            if name in processed or name.startswith('__'):
                continue

            # 'data' is a list of string annotations
            if isinstance(attr, collections.Hashable) and attr in __cache__:
                data = __cache__[attr]
                del __cache__[attr]
            elif isinstance(attr, QueryableAttribute) and attr.property in __cache__:
                data = __cache__[attr.property]
                del __cache__[attr.property]
            elif hasattr(attr, '_coaster_annotations'):
                data = attr._coaster_annotations
            else:
                data = None
            if data is not None:
                cls.__annotations_by_attr__.setdefault(name, []).extend(data)
                for a in data:
                    cls.__annotations__.setdefault(a, []).append(name)
                processed.add(name)

    annotations_configured.send(cls)


@event.listens_for(mapper, 'after_configured')
def __clear_cache():
    for key in tuple(__cache__):
        del __cache__[key]


# --- Helpers -----------------------------------------------------------------

def annotation_wrapper(annotation, doc=None):
    """
    Defines an annotation, which can be applied to attributes in a class
    derived from :class:`AnnotationMixin`.
    """
    def decorator(attr):
        __cache__.setdefault(attr, []).append(annotation)
        # Also mark the annotation on the object itself. This will
        # fail if the object has a restrictive __slots__, but it's
        # required for some objects like Column because SQLAlchemy copies
        # them in subclasses, changing their hash and making them
        # undiscoverable via the cache.
        try:
            if not hasattr(attr, '_coaster_annotations'):
                setattr(attr, '_coaster_annotations', [])
            attr._coaster_annotations.append(annotation)
        except AttributeError:
            pass
        return attr

    decorator.__name__ = decorator.name = annotation
    decorator.__doc__ = doc
    return decorator


# --- Annotations -------------------------------------------------------------

immutable = annotation_wrapper('immutable', "Makes a column immutable once set")
cached = annotation_wrapper('cached', "Marks the column's contents as a cached value from another source")


# This code borrowed from https://stackoverflow.com/a/35352471/78903
class ImmutableColumnError(AttributeError):
    def __init__(self, class_name, column_name, old_value, new_value, message=None):
        self.class_name = class_name
        self.column_name = column_name
        self.old_value = old_value
        self.new_value = new_value

        if message is None:
            self.message = (
                u"Cannot update column {column_name} on model {class_name} from {old_value} to {new_value}: "
                u"column is immutable.".format(
                    column_name=column_name, class_name=class_name, old_value=old_value, new_value=new_value))


@annotations_configured.connect
def __make_immutable(cls):
    for attr in cls.__annotations__.get(immutable.name, []):
        col = getattr(cls, attr)

        @event.listens_for(col, 'set')
        def immutable_column_set_listener(target, value, old_value, initiator):
            if old_value != symbol('NEVER_SET') and old_value != symbol('NO_VALUE') and old_value != value:
                raise ImmutableColumnError(cls.__name__, col.name, old_value, value)
