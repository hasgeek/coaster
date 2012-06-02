# -*- coding: utf-8 -*-

from __future__ import absolute_import
from coaster import make_name
from sqlalchemy import Column, Integer, DateTime, Unicode, UniqueConstraint
from sqlalchemy.ext.declarative import declared_attr
from datetime import datetime


class IdMixin(object):
    id = Column(Integer, primary_key=True)


class TimestampMixin(object):
    # We use datetime.utcnow (app-side) instead of func.now() (database-side)
    # because the latter breaks with Flask-Admin.
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class BaseMixin(IdMixin, TimestampMixin):
    """
    Base mixin class for all tables that adds id and timestamp columns
    """
    pass


class BaseNameMixin(IdMixin, TimestampMixin):
    """
    Base mixin class for named objects
    """
    name = Column(Unicode(250), nullable=False, unique=True)
    title = Column(Unicode(250), nullable=False)

    def __init__(self, *args, **kw):
        super(BaseNameMixin, self).__init__(*args, **kw)
        self.make_name()

    def make_name(self):
        if self.title:
            if self.id:
                checkused = lambda c: self.__class__.query.filter(self.__class__.id != self.id).filter_by(name=c).first()
            else:
                checkused = lambda c: self.__class__.query.filter_by(name=c).first()
            self.name = make_name(self.title, maxlength=250,
                checkused=checkused)


class BaseScopedNameMixin(IdMixin, TimestampMixin):
    """
    Base mixin class for named objects within containers. When using this,
    you must provide an model-level attribute "parent" that is a synonym for
    the parent object. You must also create a unique constraint on 'name' in
    combination with the parent foreign key. Sample use case in Flask::

        class Event(db.Model, BaseScopedNameMixin):
            __tablename__ = 'event'
            organizer_id = db.Column(db.Integer, db.ForeignKey('organizer.id'))
            organizer = db.relationship(Organizer)
            parent = db.synonym('organizer')
            __table_args__ = (db.UniqueConstraint('name', 'organizer_id'),)

    """
    name = Column(Unicode(250), nullable=False)
    title = Column(Unicode(250), nullable=False)

    def __init__(self, *args, **kw):
        super(BaseScopedNameMixin, self).__init__(*args, **kw)
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


class BaseIdNameMixin(BaseNameMixin):
    """
    Base mixin class for named objects with an id tag.
    """

    url_id_attr = 'id'

    def __init__(self, *args, **kw):
        super(BaseIdNameMixin, self).__init__(*args, **kw)
        self.make_id()

    def make_id(self):
        pass

    def make_name(self):
        self.name = make_name(self.title, maxlength=250)

    @property
    def url_id(self):
        return self.id

    @property
    def url_name(self):
        return '%d-%s' % (self.url_id, self.name)
