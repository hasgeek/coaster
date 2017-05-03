# -*- coding: utf-8 -*-

from __future__ import absolute_import
from flask_sqlalchemy import SQLAlchemy

__all__ = ['SQLAlchemy', 'db']


db = SQLAlchemy()
