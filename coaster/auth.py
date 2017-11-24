# -*- coding: utf-8 -*-

"""
Authentication management
=========================

Coaster provides a :obj:`current_auth` for handling authentication. Login
managers must comply with its API for Coaster's view handlers to work. Mostly
compatible with Flask-Login for the use cases Coaster requires.

Login managers must install themselves as ``current_app.login_manager``, and
must provide a ``_load_user()`` method, which loads the user object into
Flask's request context as ``_request_ctx_stack.top.user``. Additional auth
context can be loaded into a dictionary named ``_request_ctx_stack.top.auth``.

Login managers can use :func:`add_auth_attribute` to have these details
handled for them.
"""

from __future__ import absolute_import
from werkzeug.local import LocalProxy
from flask import _request_ctx_stack, current_app, has_request_context


def add_auth_attribute(attr, value):
    """
    Helper function for login managers. Adds authorization attributes
    that will be made available via :obj:`current_auth`.
    """
    # Special-case 'user' for compatibility with Flask-Login
    if attr == 'user':
        _request_ctx_stack.top.user = value
    else:
        if not hasattr(_request_ctx_stack.top, 'auth'):
            _request_ctx_stack.top.auth = {}
        _request_ctx_stack.top.auth[attr] = value


class CurrentAuth(object):
    """
    Holding class for current authenticated objects such as user accounts.
    This class is constructed by :obj:`current_auth`. Typical uses:

    Check if you have a valid authenticated user in the current request::

        if current_auth.is_authenticated:

    Reverse check, for anonymous user. Your login manager may or may not
    treat these as special database objects::

        if current_auth.is_anonymous:

    Access the underlying user object via the ``user`` attribute::

        if document.user == current_auth.user:
            other_document.user = current_auth.user

    If your login manager provided additional auth attributes, these will be
    available from :obj:`current_auth`. The following two are directly
    provided.
    """
    def __init__(self, user, **kwargs):
        object.__setattr__(self, 'user', user)
        for key, value in kwargs.items():
            object.__setattr__(self, key, value)

    def __setattr__(self, attr, value):
        raise AttributeError('CurrentAuth is read-only')

    def __repr__(self):  # pragma: no cover
        return 'CurrentAuth(%s)' % repr(self.user)

    @property
    def is_anonymous(self):
        """
        Property that returns ``True`` if the login manager did not report a
        user. Returns the user object's ``is_anonymous`` attribute if present,
        defaulting to ``False``. Login managers can supply a special anonymous
        user object with this attribute set, if anonymous user objects are
        required by the app.
        """
        if self.user:
            return getattr(self.user, 'is_anonymous', False)
        return True

    @property
    def is_authenticated(self):
        """
        Property that returns the opposite of :attr:`is_anonymous`. Using this
        property is recommended for compatibility with Flask-Login and Django.

        This may change in future if new authentication types support
        simultaneously being authenticated while anonymous.
        """
        return not self.is_anonymous


def _get_user():
    if has_request_context() and not hasattr(_request_ctx_stack.top, 'user'):
        # Flask-Login, Flask-Lastuser or equivalent must add this
        if hasattr(current_app, 'login_manager'):
            current_app.login_manager._load_user()

    return CurrentAuth(getattr(_request_ctx_stack.top, 'user', None), **getattr(_request_ctx_stack.top, 'auth', {}))


#: A proxy object that returns the currently logged in user, attempting to
#: load it if not already loaded. Returns a :class:`CurrentAuth`. Typical use::
#:
#:     from coaster.auth import current_auth
#:
#:     @app.route('/')
#:     def user_check():
#:         if current_auth.is_authenticated:
#:             return "We have a user"
#:         else:
#:             return "User not logged in"
current_auth = LocalProxy(_get_user)
