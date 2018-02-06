# -*- coding: utf-8 -*-

"""
Authentication management
=========================

Coaster provides a :obj:`current_auth` for handling authentication. Login
managers must comply with its API for Coaster's view handlers to work.

If a login manager installs itself as ``current_app.login_manager`` and
provides a ``_load_user()`` method, it will be called when :obj:`current_auth`
is invoked for the first time in a request. Login managers can call
:func:`add_auth_attribute` to load the actor (typically the authenticated user)
and any other relevant authentication attributes.

For compatibility with Flask-Login, a user object loaded at
``_request_ctx_stack.top.user`` will be recognised and made available via
:obj:`current_auth`.
"""

from __future__ import absolute_import
import collections
from werkzeug.local import LocalProxy
from flask import _request_ctx_stack, current_app, has_request_context

__all__ = ['add_auth_attribute', 'add_auth_anchor', 'request_has_auth', 'current_auth']


def add_auth_attribute(attr, value, actor=False):
    """
    Helper function for login managers. Adds authorization attributes
    to :obj:`current_auth` for the duration of the request.

    :param str attr: Name of the attribute
    :param value: Value of the attribute
    :param bool actor: Whether this attribute is an actor
       (user or client app accessing own data)

    If the attribute is an actor and :obj:`current_auth` does not currently
    have an actor, the attribute is also made available as
    ``current_auth.actor``, which in turn is used by
    ``current_auth.is_authenticated``.

    The attribute name ``user`` is special-cased:

    1. ``user`` is always treated as an actor
    2. ``user`` is also made available as ``_request_ctx_stack.top.user`` for
       compatibility with Flask-Login
    """
    if attr in ('actor', 'anchors', 'is_anonymous', 'is_authenticated'):
        raise AttributeError("Attribute name %s is reserved by current_auth" % attr)

    # Invoking current_auth will also create it on the local stack. We can
    # then proceed to set attributes on it.
    ca = current_auth._get_current_object()
    # Since :class:`CurrentAuth` overrides ``__setattr__``, we need to use :class:`object`'s.
    object.__setattr__(ca, attr, value)

    if attr == 'user':
        # Special-case 'user' for compatibility with Flask-Login
        _request_ctx_stack.top.user = value
        # A user is always an actor
        actor = True

    if actor and ca.actor is None and value is not None:
        object.__setattr__(ca, 'actor', value)


def add_auth_anchor(anchor):
    """
    Helper function for login managers and view handlers to add a new auth anchor.
    This is a placeholder until anchors are properly specified.
    """
    current_auth.anchors._add(anchor)


def request_has_auth():
    """
    Helper function that returns True if :obj:`current_auth` was invoked during
    the current request. A login manager can use this during request teardown
    to set cookies or perform other housekeeping functions.
    """
    return hasattr(_request_ctx_stack.top, 'current_auth')


class AuthAnchors(collections.Set):
    """
    Hosts a set without write access.
    """
    def __init__(self, members=None):
        self.__members = set(members) if members is not None else set()

    def __repr__(self):  # pragma: no cover
        return 'AuthAnchors({members})'.format(members=repr(self.__members))

    def __len__(self):
        return len(self.__members)

    def __contains__(self, member):
        return member in self.__members

    def __iter__(self):
        for member in self.__members:
            yield member

    def _add(self, member):
        self.__members.add(member)


class CurrentAuth(object):
    """
    Holding class for current authenticated objects such as user accounts.
    This class is constructed by :obj:`current_auth`. Typical uses:

    Check if you have a valid actor in the current request::

        if current_auth.is_authenticated:

    Reverse check, for anonymous user. Your login manager may or may not
    treat these as special database objects::

        if current_auth.is_anonymous:

    Access the underlying user object via the :attr:`user` attribute::

        if document.user == current_auth.user:
            other_document.user = current_auth.user

    If your login manager supports security actors other than users (such
    as access tokens or client apps), the current actor will be available
    as the :attr:`actor` attribute. Users are always treated as actors.

    Additional attributes provided by your login manager are also available as
    direct attributes of :obj:`current_auth`.
    """
    def __init__(self, user):
        object.__setattr__(self, 'user', user)
        object.__setattr__(self, 'actor', user)
        object.__setattr__(self, 'anchors', AuthAnchors())  # TODO: Placeholder for anchors

    def __setattr__(self, attr, value):
        raise AttributeError('CurrentAuth is read-only')

    def __repr__(self):  # pragma: no cover
        return 'CurrentAuth(%s)' % repr(self.actor)

    @property
    def is_anonymous(self):
        """
        Property that returns ``True`` if an actor is not present, or if an
        actor is present but has an ``is_anonymous`` attribute
        set to ``True``.
        """
        if self.actor is not None:
            return getattr(self.actor, 'is_anonymous', False)
        return True

    @property
    def is_authenticated(self):
        """
        Property that returns ``True`` if an actor is present.
        """
        return self.actor is not None


def _get_current_auth():
    # 1. Do we have a request?
    if has_request_context():
        # 2. Does this request already have current_auth? If so, return it
        if hasattr(_request_ctx_stack.top, 'current_auth'):
            return _request_ctx_stack.top.current_auth

        # 3. If not, does it have a known user (Flask-Login protocol)? If so, construct current_auth
        if hasattr(_request_ctx_stack.top, 'user'):
            _request_ctx_stack.top.current_auth = CurrentAuth(_request_ctx_stack.top.user)
        # 4. If none of these, construct a blank one and probe for content
        else:
            ca = CurrentAuth(None)
            # If the login manager below calls :func:`add_auth_attribute`,
            # we'll have a recursive entry into :func:`_get_current_auth`, so make sure
            # the stack has an empty :class:`CurrentAuth` on it
            _request_ctx_stack.top.current_auth = ca
            # 4.1. Now check for a login manager and call it
            # Flask-Login, Flask-Lastuser or equivalent must add a login_manager
            if hasattr(current_app, 'login_manager') and hasattr(current_app.login_manager, '_load_user'):
                current_app.login_manager._load_user()
            # 4.2. In case the login manager did not call :func:`add_auth_attribute`, we'll
            # need to copy the user symbol manually
            if ca.user is None:
                object.__setattr__(ca, 'user', getattr(_request_ctx_stack.top, 'user', None))

        # Return the newly constructed current_auth
        return _request_ctx_stack.top.current_auth
    # Fallback if there is no request context. Return a blank current_auth
    # so that ``current_auth.is_authenticated`` remains valid for checking status
    return CurrentAuth(None)  # Make this work even when there's no request


#: A proxy object that hosts state for user authentication, attempting to load
#: state from request context if not already loaded. Returns a
#: :class:`CurrentAuth`. Typical use::
#:
#:     from coaster.auth import current_auth
#:
#:     @app.route('/')
#:     def user_check():
#:         if current_auth.is_authenticated:
#:             return "We have a user"
#:         else:
#:             return "User not logged in"
current_auth = LocalProxy(_get_current_auth)
