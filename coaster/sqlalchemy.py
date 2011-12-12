# -*- coding: utf-8 -*-

from __future__ import absolute_import
from sqlalchemy import Column, Integer, DateTime, Unicode, func

class IdMixin(object):
    id = Column(Integer, primary_key=True)

class TimestampMixin(object):
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

class BaseMixin(IdMixin, TimestampMixin):
    """
    Base mixin class for all tables that adds id and timestamp columns
    """
    pass

class BaseNameMixin(IdMixin, TimestampMixin):
    """
    Base mixin class for named objects
    """
    name = Column(Unicode(250), nullable=False)
    title = Column(Unicode(250), nullable=False)
