# -*- coding: utf-8 -*-
# flake8: noqa

"""
Utilities
=========

These functions are not dependent on Flask. They implement common patterns
in Flask-based applications.
"""


from __future__ import absolute_import
from .misc import *
from .text import *
from .markdown import *
from .tsquery import *
from .classes import *
from ..shortuuid import suuid, encode as uuid2suuid, decode as suuid2uuid
