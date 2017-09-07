# -*- coding: utf-8 -*-

"""
Utilities
=========

These functions are not dependent on Flask. They implement common patterns
in Flask-based applications.
"""

from __future__ import absolute_import
from .misc import *  # NOQA
from .text import *  # NOQA
from .tsquery import *  # NOQA
from .classes import *  # NOQA
from ..shortuuid import suuid, encode as uuid2suuid, decode as suuid2uuid  # NOQA
