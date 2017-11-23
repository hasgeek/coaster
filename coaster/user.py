# -*- coding: utf-8 -*-

"""
User account management
=======================

Provides a :obj:`current_user` for handling user accounts. Login managers
must comply with its API for Coaster's view handlers to work. Mostly
compatible with Flask-Login for the use cases Coaster requires.

Login managers must install themselves as ``current_app.login_manager``, and
must provide a ``_load_user()`` method, which loads the user object into
Flask's request context as ``_request_ctx_stack.top.user``.
"""

from __future__ import absolute_import
from werkzeug.local import LocalProxy
from flask import _request_ctx_stack, current_app, has_request_context


class UserProxy(object):
    """
    Proxy class for user objects. Passes through access to all attributes, but
    if you need the actual underlying object to assign or compare with, access
    it from the ``self`` attribute. This proxy is constructed by
    :obj:`current_user`. Typical uses:

    Check if you have a valid authenticated user in the current request::

        if current_user.is_authenticated:

    Reverse check, for anonymous user. Your login manager may or may not
    treat these as special database objects::

        if current_user.is_anonymous:

    Directly read and write attributes, and call methods on the user object.
    These are passed through to the underlying object::

        if current_user.name == 'foo':
            current_user.name = 'bar'
        current_user.set_updated()

    However, for assignments and comparisons of the user object itself, you
    must address it with the proxy's :attr:`self` attribute. This aspect is
    where :class:`UserProxy` is incompatible with the ``UserMixin`` class in
    Flask-Login::

        if document.user == current_user.self:
            other_document.user = current_user.self
    """
    def __init__(self, user):
        object.__setattr__(self, 'self', user)

    def __getattr__(self, attr):
        return getattr(self.self, attr)

    def __setattr__(self, attr, value):
        setattr(self.self, attr, value)

    @property
    def is_anonymous(self):
        """
        Property that returns ``True`` if the proxy is not affiliated with a
        user object. Returns the user object's ``is_anonymous`` attribute if
        present, defaulting to ``False``. Login managers can supply a special
        anonymous user object with this attribute set, if anonymous user objects
        are required by the app.
        """
        if self.self:
            return getattr(self.self, 'is_anonymous', False)
        return True

    @property
    def is_authenticated(self):
        """
        Property that returns the opposite of :attr:`is_anonymous`. Using this
        property is recommended for compatibility with Flask-Login and Django.
        """
        return not self.is_anonymous


def _get_user():
    if has_request_context() and not hasattr(_request_ctx_stack.top, 'user'):
        # Flask-Login, Flask-Lastuser or equivalent must add this
        if hasattr(current_app, 'login_manager'):
            current_app.login_manager._load_user()

    return UserProxy(getattr(_request_ctx_stack.top, 'user', None))


#: A proxy object that returns the currently logged in user, attempting to
#: load it if not already loaded. Returns a :class:`UserProxy`. Typical use::
#:
#:     from coaster.user import current_user
#:
#:     @app.route('/')
#:     def user_check():
#:         if current_user.is_authenticated:
#:             return "We have a user"
#:         else:
#:             return "User not logged in"
current_user = LocalProxy(_get_user)
