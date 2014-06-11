# -*- coding: utf-8 -*-

from __future__ import absolute_import
from datetime import datetime
import simplejson
from sqlalchemy import Column, Integer, DateTime, Unicode, UnicodeText
from sqlalchemy.sql import select, func
from sqlalchemy.types import UserDefinedType, TypeDecorator, TEXT
from sqlalchemy.orm import composite
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.ext.mutable import Mutable, MutableComposite
from flask import Markup
from flask.ext.sqlalchemy import BaseQuery
from .utils import make_name
from .gfm import markdown


__all_mixins = ['IdMixin', 'TimestampMixin', 'PermissionMixin', 'UrlForMixin',
    'BaseMixin', 'BaseNameMixin', 'BaseScopedNameMixin', 'BaseIdNameMixin',
    'BaseScopedIdMixin', 'BaseScopedIdNameMixin']


class Query(BaseQuery):
    """
    Extends flask.ext.sqlalchemy.BaseQuery to add additional helper methods.
    """

    def one_or_none(self):
        """
        Like :meth:`one` but returns None if no results are found. Raises an exception
        if multiple results are found.
        """
        try:
            return self.one()
        except NoResultFound:
            return None


class IdMixin(object):
    """
    Provides the :attr:`id` primary key column
    """
    #: Database identity for this model, used for foreign key
    #: references from other models
    id = Column(Integer, primary_key=True)


timestamp_columns = (
    Column('created_at', DateTime, default=datetime.utcnow, nullable=False),
    Column('updated_at', DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False),
    )


class TimestampMixin(object):
    """
    Provides the :attr:`created_at` and :attr:`updated_at` audit timestamps
    """
    #: Timestamp for when this instance was created, in UTC
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    #: Timestamp for when this instance was last updated (via the app), in UTC
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PermissionMixin(object):
    """
    Provides the :meth:`permissions` method used by BaseMixin and derived classes
    """
    def permissions(self, user, inherited=None):
        """
        Return permissions available to the given user on this object
        """
        if inherited is not None:
            return set(inherited)
        else:
            return set()


class UrlForMixin(object):
    """
    Provides a placeholder :meth:`url_for` method used by BaseMixin-derived classes
    """
    def url_for(self, action='view', **kwargs):
        """
        Return public URL to this instance for a given action (default 'view')
        """
        return None


class BaseMixin(IdMixin, TimestampMixin, PermissionMixin, UrlForMixin):
    """
    Base mixin class for all tables that adds id and timestamp columns and includes
    stub :meth:`permissions` and :meth:`url_for` methods
    """
    query_class = Query


class BaseNameMixin(BaseMixin):
    """
    Base mixin class for named objects
    """
    @declared_attr
    def name(cls):
        """The URL name of this object, unique across all instances of this model"""
        return Column(Unicode(250), nullable=False, unique=True)

    @declared_attr
    def title(cls):
        """The title of this object"""
        return Column(Unicode(250), nullable=False)

    def __init__(self, *args, **kw):
        super(BaseNameMixin, self).__init__(*args, **kw)
        if not self.name:
            self.make_name()

    def make_name(self, reserved=[]):
        """
        Autogenerates a :attr:`name` from the :attr:`title`. If the auto-generated name is already
        in use in this model, :meth:`make_name` tries again by suffixing numbers starting with 2
        until an available name is found.

        :param reserved: List or set of reserved names unavailable for use
        """
        if self.title:
            if self.id:
                checkused = lambda c: bool(c in reserved or
                    self.__class__.query.filter(self.__class__.id != self.id).filter_by(name=c).count())
            else:
                checkused = lambda c: bool(c in reserved or self.__class__.query.filter_by(name=c).count())
            self.name = unicode(make_name(self.title, maxlength=250, checkused=checkused))


class BaseScopedNameMixin(BaseMixin):
    """
    Base mixin class for named objects within containers. When using this,
    you must provide an model-level attribute "parent" that is a synonym for
    the parent object. You must also create a unique constraint on 'name' in
    combination with the parent foreign key. Sample use case in Flask::

        class Event(BaseScopedNameMixin, db.Model):
            __tablename__ = 'event'
            organizer_id = db.Column(db.Integer, db.ForeignKey('organizer.id'))
            organizer = db.relationship(Organizer)
            parent = db.synonym('organizer')
            __table_args__ = (db.UniqueConstraint('organizer_id', 'name'),)
    """
    @declared_attr
    def name(cls):
        """The URL name of this object, unique within a parent container"""
        return Column(Unicode(250), nullable=False)

    @declared_attr
    def title(cls):
        """The title of this object"""
        return Column(Unicode(250), nullable=False)

    def __init__(self, *args, **kw):
        super(BaseScopedNameMixin, self).__init__(*args, **kw)
        if self.parent and not self.name:
            self.make_name()

    def make_name(self, reserved=[]):
        """
        Autogenerates a :attr:`name` from the :attr:`title`. If the auto-generated name is already
        in use in this model, :meth:`make_name` tries again by suffixing numbers starting with 2
        until an available name is found.
        """
        if self.title:
            if self.id:
                checkused = lambda c: bool(c in reserved or
                    self.__class__.query.filter(self.__class__.id != self.id).filter_by(
                    name=c, parent=self.parent).first())
            else:
                checkused = lambda c: bool(c in reserved or
                    self.__class__.query.filter_by(name=c, parent=self.parent).first())
            self.name = unicode(make_name(self.short_title(), maxlength=250, checkused=checkused))

    def short_title(self):
        """
        Generates an abbreviated title by subtracting the parent's title from this instance's title.
        """
        if self.title and self.parent is not None and hasattr(self.parent, 'title') and self.parent.title:
            if self.title.startswith(self.parent.title):
                return self.title[len(self.parent.title):].strip()
        return self.title

    def permissions(self, user, inherited=None):
        """
        Permissions for this model, plus permissions inherited from the parent.
        """
        if inherited is not None:
            return inherited | super(BaseScopedNameMixin, self).permissions(user)
        elif self.parent is not None and isinstance(self.parent, PermissionMixin):
            return self.parent.permissions(user) | super(BaseScopedNameMixin, self).permissions(user)
        else:
            return super(BaseScopedNameMixin, self).permissions(user)


class BaseIdNameMixin(BaseMixin):
    """
    Base mixin class for named objects with an id tag.
    """
    @declared_attr
    def name(cls):
        """The URL name of this object, non-unique"""
        return Column(Unicode(250), nullable=False)

    @declared_attr
    def title(cls):
        """The title of this object"""
        return Column(Unicode(250), nullable=False)

    #: The attribute containing id numbers used in the URL in id-name syntax, for external reference
    url_id_attr = 'id'

    def __init__(self, *args, **kw):
        super(BaseIdNameMixin, self).__init__(*args, **kw)
        if not self.name:
            self.make_name()

    def make_name(self):
        """Autogenerates a :attr:`name` from the :attr:`title`"""
        if self.title:
            self.name = unicode(make_name(self.title, maxlength=250))

    @property
    def url_id(self):
        """Return the URL id"""
        return self.id

    @property
    def url_name(self):
        """Returns a URL name combining :attr:`url_id` and :attr:`name` in id-name syntax"""
        return '%d-%s' % (self.url_id, self.name)


class BaseScopedIdMixin(BaseMixin):
    """
    Base mixin class for objects with an id that is unique within a parent.
    Implementations must provide a 'parent' attribute that is either a relationship
    or a synonym to a relationship referring to the parent object, and must
    declare a unique constraint between url_id and the parent. Sample use case in Flask::

        class Issue(BaseScopedIdMixin, db.Model):
            __tablename__ = 'issue'
            event_id = db.Column(Integer, db.ForeignKey('event.id'))
            event = db.relationship(Event)
            parent = db.synonym('event')
            __table_args__ = (db.UniqueConstraint('event_id', 'url_id'),)
    """
    @declared_attr
    def url_id(cls):
        """Contains an id number that is unique within the parent container"""
        return Column(Integer, nullable=False)

    #: The attribute containing the url id value, for external reference
    url_id_attr = 'url_id'

    def __init__(self, *args, **kw):
        super(BaseScopedIdMixin, self).__init__(*args, **kw)
        if self.parent:
            self.make_id()

    def make_id(self):
        """Create a new URL id that is unique to the parent container"""
        if self.url_id is None:  # Set id only if empty
            self.url_id = select([func.coalesce(func.max(self.__class__.url_id + 1), 1)],
                self.__class__.parent == self.parent)

    def permissions(self, user, inherited=None):
        """
        Permissions for this model, plus permissions inherited from the parent.
        """
        if inherited is not None:
            return inherited | super(BaseScopedIdMixin, self).permissions(user)
        else:
            return self.parent.permissions(user) | super(BaseScopedIdMixin, self).permissions(user)


class BaseScopedIdNameMixin(BaseScopedIdMixin):
    """
    Base mixin class for named objects with an id tag that is unique within a
    parent. Implementations must provide a 'parent' attribute that is a
    synonym to the parent relationship, and must declare a unique constraint
    between url_id and the parent. Sample use case in Flask::

        class Event(BaseScopedIdNameMixin, db.Model):
            __tablename__ = 'event'
            organizer_id = db.Column(db.Integer, db.ForeignKey('organizer.id'))
            organizer = db.relationship(Organizer)
            parent = db.synonym('organizer')
            __table_args__ = (db.UniqueConstraint('organizer_id', 'url_id'),)
    """
    @declared_attr
    def name(cls):
        """The URL name of this instance, non-unique"""
        return Column(Unicode(250), nullable=False)

    @declared_attr
    def title(cls):
        """The title of this instance"""
        return Column(Unicode(250), nullable=False)

    def __init__(self, *args, **kw):
        super(BaseScopedIdNameMixin, self).__init__(*args, **kw)
        if self.parent:
            self.make_id()
        if not self.name:
            self.make_name()

    def make_name(self):
        """Autogenerates a title from the name"""
        if self.title:
            self.name = unicode(make_name(self.title, maxlength=250))

    @property
    def url_name(self):
        """Returns a URL name combining :attr:`url_id` and :attr:`name` in id-name syntax"""
        return '%d-%s' % (self.url_id, self.name)


# --- Column types ------------------------------------------------------------

__all_columns = ['JsonDict', 'MarkdownComposite', 'MarkdownColumn']


class JsonType(UserDefinedType):
    """The PostgreSQL JSON type."""

    def get_col_spec(self):
        return "JSON"


# Adapted from http://docs.sqlalchemy.org/en/rel_0_8/orm/extensions/mutable.html#establishing-mutability-on-scalar-column-values

class JsonDict(TypeDecorator):
    """
    Represents a JSON data structure. Usage::

        column = Column(JsonDict)
    """

    impl = TEXT

    def _has_json(self, dialect):
        if dialect.name == 'postgresql':
            version = dialect.server_version_info
            if (version[0] == 9 and version[1] >= 2) or version[0] > 9:
                return True
        return False

    def load_dialect_impl(self, dialect):
        if self._has_json(dialect):
            return dialect.type_descriptor(JsonType)
        return dialect.type_descriptor(self.impl)

    def process_bind_param(self, value, dialect):
        if value is not None:
            value = simplejson.dumps(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and isinstance(value, basestring):
            # Psycopg2 >= 2.5 will auto-decode JSON columns, so
            # we only attempt decoding if the value is a string.
            # Since this column stores dicts only, processed values
            # can never be strings.
            value = simplejson.loads(value, use_decimal=True)
        return value


class MutableDict(Mutable, dict):
    @classmethod
    def coerce(cls, key, value):
        "Convert plain dictionaries to MutableDict."

        if not isinstance(value, MutableDict):
            if isinstance(value, dict):
                return MutableDict(value)

            # this call will raise ValueError
            return Mutable.coerce(key, value)
        else:
            return value

    def __setitem__(self, key, value):
        "Detect dictionary set events and emit change events."

        dict.__setitem__(self, key, value)
        self.changed()

    def __delitem__(self, key):
        "Detect dictionary del events and emit change events."

        dict.__delitem__(self, key)
        self.changed()

MutableDict.associate_with(JsonDict)


class MarkdownComposite(MutableComposite):
    """
    Represents GitHub-flavoured Markdown text and rendered HTML as a composite column.
    """
    def __init__(self, text, html=None):
        if html is None:
            self.text = text  # This will regenerate HTML
        else:
            object.__setattr__(self, 'text', text)
            object.__setattr__(self, '_html', html)

    # If the text value is set, regenerate HTML, then notify parents of the change
    def __setattr__(self, key, value):
        if key == 'text':
            object.__setattr__(self, '_html', markdown(value))
        object.__setattr__(self, key, value)
        self.changed()

    # Return column values for SQLAlchemy to insert into the database
    def __composite_values__(self):
        return (self.text, self._html)

    # Return a string representation of the text
    def __str__(self):
        return str(self.text)

    # Return a unicode representation of the text
    def __unicode__(self):
        return unicode(self.text)

    # Return a HTML representation of the text
    def __html__(self):
        return self._html or u''

    # Return a Markup string of the HTML
    @property
    def html(self):
        return Markup(self._html or u'')

    # Compare text value
    def __eq__(self, other):
        return (self.text == other.text) if isinstance(other, MarkdownComposite) else (self.text == other)

    def __ne__(self, other):
        return not self.__eq__(other)

    # Return state for pickling
    def __getstate__(self):
        return (self.text, self._html)

    # Set state from pickle
    def __setstate__(self, state):
        object.__setattr__(self, 'text', state[0])
        object.__setattr__(self, '_html', state[1])
        self.changed()

    def __nonzero__(self):
        return bool(self.text)

    __bool__ = __nonzero__

    # Allow a composite column to be assigned a string value
    @classmethod
    def coerce(cls, key, value):
        return cls(value)


def MarkdownColumn(name, deferred=False, group=None, **kwargs):
    return composite(MarkdownComposite,
        Column(name + '_text', UnicodeText, **kwargs),
        Column(name + '_html', UnicodeText, **kwargs),
        deferred=deferred, group=group or name
        )


__all__ = __all_mixins + __all_columns
