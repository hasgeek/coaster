# -*- coding: utf-8 -*-

from __future__ import absolute_import
from coaster import make_name
from sqlalchemy import Column, Integer, DateTime, Unicode, desc
from sqlalchemy.ext.declarative import declared_attr
from datetime import datetime


class IdMixin(object):
    """
    Provides the :attr:`id` primary key column
    """
    @declared_attr
    def id(cls):
        return Column(Integer, primary_key=True)


class TimestampMixin(object):
    """
    Provides the :attr:`created_at` and :attr:`updated_at` audit timestamps
    """
    # We use datetime.utcnow (app-side) instead of func.now() (database-side)
    # because the latter breaks with Flask-Admin.
    @declared_attr
    def created_at(cls):
        return Column(DateTime, default=datetime.utcnow, nullable=False)

    @declared_attr
    def updated_at(cls):
        return Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


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

    def permissions(self, user, inherited=None):
        """
        Permissions for this model, plus permissions inherited from the parent.
        """
        if inherited is not None:
            return inherited | super(BaseScopedNameMixin, self).permissions(user)
        else:
            return self.parent.permissions(user) | super(BaseScopedNameMixin, self).permissions(user)


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
        if not self.url_id:  # Set id only if empty
            existing = self.__class__.query.filter_by(parent=self.parent).order_by(
                desc(self.url_id_attr)).limit(1).first()
            if existing:
                self.url_id = getattr(existing, self.url_id_attr) + 1
            else:
                self.url_id = 1

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
