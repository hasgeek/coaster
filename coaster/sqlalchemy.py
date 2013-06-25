# -*- coding: utf-8 -*-

from __future__ import absolute_import
from coaster import make_name
from sqlalchemy import Column, Integer, DateTime, Unicode
from sqlalchemy.sql import select, func
from sqlalchemy.types import TypeDecorator, TEXT
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.ext.mutable import Mutable
from datetime import datetime
import simplejson


__all_mixins = ['IdMixin', 'TimestampMixin', 'PermissionMixin', 'UrlForMixin',
    'BaseMixin', 'BaseNameMixin', 'BaseScopedNameMixin', 'BaseIdNameMixin',
    'BaseScopedIdMixin', 'BaseScopedIdNameMixin']


class IdMixin(object):
    """
    Provides the :attr:`id` primary key column
    """
    id = Column(Integer, primary_key=True)


class TimestampMixin(object):
    """
    Provides the :attr:`created_at` and :attr:`updated_at` audit timestamps
    """
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=datetime.utcnow, nullable=False)


class PermissionMixin(object):
    """
    Provides the :meth:`permissions` method used by BaseMixin and derived classes
    """
    def permissions(self, user, inherited=None):
        """
        Return permissions available to the given user on this object
        """
        if inherited is not None:
            return inherited
        else:
            return set()


class UrlForMixin(object):
    """
    Provides a placeholder :meth:`url_for` method used by BaseMixin-derived classes
    """
    def url_for(self, action='view', **kwargs):
        return None


class BaseMixin(IdMixin, TimestampMixin, PermissionMixin, UrlForMixin):
    """
    Base mixin class for all tables that adds id and timestamp columns and includes
    stub :meth:`permissions` and :meth:`url_for` methods
    """
    pass


class BaseNameMixin(BaseMixin):
    """
    Base mixin class for named objects
    """
    @declared_attr
    def name(cls):
        return Column(Unicode(250), nullable=False, unique=True)

    @declared_attr
    def title(cls):
        return Column(Unicode(250), nullable=False)

    def __init__(self, *args, **kw):
        super(BaseNameMixin, self).__init__(*args, **kw)
        if not self.name:
            self.make_name()

    def make_name(self):
        if self.title:
            if self.id:
                checkused = lambda c: self.__class__.query.filter(self.__class__.id != self.id).filter_by(name=c).first()
            else:
                checkused = lambda c: self.__class__.query.filter_by(name=c).first()
            self.name = make_name(self.title, maxlength=250,
                checkused=checkused)


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
            __table_args__ = (db.UniqueConstraint('name', 'organizer_id'),)
    """
    @declared_attr
    def name(cls):
        return Column(Unicode(250), nullable=False)

    @declared_attr
    def title(cls):
        return Column(Unicode(250), nullable=False)

    def __init__(self, *args, **kw):
        super(BaseScopedNameMixin, self).__init__(*args, **kw)
        if self.parent and not self.name:
            self.make_name()

    def make_name(self):
        if self.title:
            if self.id:
                checkused = lambda c: self.__class__.query.filter(self.__class__.id != self.id).filter_by(
                    name=c, parent=self.parent).first()
            else:
                checkused = lambda c: self.__class__.query.filter_by(name=c, parent=self.parent).first()
            self.name = make_name(self.title, maxlength=250,
                checkused=checkused)

    def short_title(self):
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
        return Column(Unicode(250), nullable=False)

    @declared_attr
    def title(cls):
        return Column(Unicode(250), nullable=False)

    url_id_attr = 'id'

    def __init__(self, *args, **kw):
        super(BaseIdNameMixin, self).__init__(*args, **kw)
        if not self.name:
            self.make_name()

    def make_name(self):
        if self.title:
            self.name = make_name(self.title, maxlength=250)

    @property
    def url_id(self):
        return self.id

    @property
    def url_name(self):
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
            __table_args__ = (db.UniqueConstraint('url_id', 'event_id'),)
    """
    @declared_attr
    def url_id(cls):
        return Column(Integer, nullable=False)

    url_id_attr = 'url_id'

    def __init__(self, *args, **kw):
        super(BaseScopedIdMixin, self).__init__(*args, **kw)
        if self.parent:
            self.make_id()

    def make_id(self):
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
            __table_args__ = (db.UniqueConstraint('url_id', 'organizer_id'),)
    """
    @declared_attr
    def name(cls):
        return Column(Unicode(250), nullable=False)

    @declared_attr
    def title(cls):
        return Column(Unicode(250), nullable=False)

    def __init__(self, *args, **kw):
        super(BaseScopedIdNameMixin, self).__init__(*args, **kw)
        if self.parent:
            self.make_id()
        if not self.name:
            self.make_name()

    def make_name(self):
        if self.title:
            self.name = make_name(self.title, maxlength=250)

    @property
    def url_name(self):
        return '%d-%s' % (self.url_id, self.name)


# --- Column types ------------------------------------------------------------

__all_columns = ['JsonDict']


# Adapted from http://docs.sqlalchemy.org/en/rel_0_8/orm/extensions/mutable.html#establishing-mutability-on-scalar-column-values

class JsonDict(TypeDecorator):
    """
    Represents a JSON data structure. Usage::

        column = Column(JsonDict)
    """
    impl = TEXT

    def process_bind_param(self, value, dialect):
        if value is not None:
            value = simplejson.dumps(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
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


__all__ = __all_mixins + __all_columns
