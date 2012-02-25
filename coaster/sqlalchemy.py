# -*- coding: utf-8 -*-

from __future__ import absolute_import
from coaster import make_name
from sqlalchemy import Column, Integer, DateTime, Unicode, func
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
