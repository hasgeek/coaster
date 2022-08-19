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

For compatibility with Flask-Login, a user object loaded at ``g._login_user`` will be
recognised and made available via :obj:`current_auth`.
"""
# pylint: disable=protected-access

from threading import Lock, RLock
import typing as t

from flask import current_app, g, request
from werkzeug.local import LocalProxy

from .utils import InspectableSet

__all__ = ['add_auth_attribute', 'add_auth_anchor', 'request_has_auth', 'current_auth']

# For async/greenlet usage, these are presumed to be monkey-patched by greenlet. The
# locks are not necessary for thread-safety since there is no cross-thread context here.
_add_lock = Lock()  # Used by add_auth_attribute
_get_lock = RLock()  # Used by _get_current_auth, which may get one recursive call


def add_auth_attribute(attr: str, value: t.Any, actor: bool = False) -> None:
    """
    Add authorization attributes to :obj:`current_auth` for the duration of the request.

    :param str attr: Name of the attribute
    :param value: Value of the attribute
    :param bool actor: Whether this attribute is an actor (user or client app accessing
       own data)

    If the attribute is an actor and :obj:`current_auth` does not currently have an
    actor, the attribute is also made available as ``current_auth.actor``, which in turn
    is used by ``current_auth.is_authenticated``.

    The attribute name ``user`` is special-cased:

    1. ``user`` is always treated as an actor
    2. ``user`` is also made available as ``g._login_user`` for compatibility with
       Flask-Login
    """
    if attr in (
        'is_placeholder',
        'actor',
        'anchors',
        'is_anonymous',
        'is_authenticated',
    ):
        raise AttributeError(f"Attribute name {attr} is reserved by current_auth")

    # Invoking current_auth will also create it on the local stack. We can then proceed
    # to set attributes on it.
    ca = current_auth._get_current_object()
    if ca.is_placeholder:
        raise RuntimeError("current_auth is a placeholder without a request context")
    # Since :class:`CurrentAuth` overrides ``__setattr__``, we need to use
    # :class:`object`'s.
    with _add_lock:
        object.__setattr__(ca, attr, value)

        if attr == 'user':
            # Special-case 'user' for compatibility with Flask-Login
            if g:
                g._login_user = value
            # A user is always an actor
            actor = True

        if actor:
            object.__setattr__(ca, 'actor', value)


def add_auth_anchor(anchor):
    """Add an anchor to current auth (placeholder pending a spec for anchors)."""
    existing = set(current_auth.anchors)
    existing.add(anchor)
    ca = current_auth._get_current_object()
    object.__setattr__(ca, 'anchors', frozenset(existing))


def request_has_auth():
    """
    Check if request accessed auth.

    Helper function that returns True if :obj:`current_auth` was invoked during
    the current request. A login manager can use this during request teardown
    to set cookies or perform other housekeeping functions.
    """
    return bool(request) and hasattr(request, '_current_auth')


class CurrentAuth:
    """
    Holding class for current authenticated objects such as user accounts.

    This class is constructed by :obj:`current_auth`. Typical uses:

    1. Check if you have a valid actor in the current request::

        if current_auth:
            ...

    which is equivalent to::

        if current_auth.is_authenticated:
            ...
        if not current_auth.is_anonymous:
            ...

    2. Access the underlying user object via the :attr:`user` attribute::

        if document.user == current_auth.user:
            other_document.user = current_auth.user

    If your login manager supports security actors other than users (such
    as access tokens or client apps), the current actor will be available
    as the :attr:`actor` attribute. Users are always treated as actors.

    Additional attributes provided by your login manager are also available as
    direct attributes of :obj:`current_auth`.
    """

    user: t.Any
    actor: t.Any
    permissions: InspectableSet

    def __init__(self, user: t.Any, is_placeholder: bool = False) -> None:
        object.__setattr__(self, 'is_placeholder', is_placeholder)
        object.__setattr__(self, 'user', user)
        object.__setattr__(self, 'actor', user)
        object.__setattr__(self, 'permissions', InspectableSet())
        object.__setattr__(  # TODO: Placeholder for anchors
            self, 'anchors', frozenset()
        )

    def __setattr__(self, attr: str, value: t.Any) -> t.NoReturn:
        raise AttributeError('CurrentAuth is read-only')

    def __delattr__(self, attr: str) -> t.NoReturn:
        raise AttributeError('CurrentAuth is read-only')

    # For mypy to recognise CurrentAuth as a bag of attributes
    def __getattr__(self, attr: str) -> t.Any:
        try:
            return self.__dict__[attr]
        except KeyError:
            raise AttributeError(attr) from None

    def __contains__(self, attr: str) -> bool:
        """Check for presence of an attribute."""
        return attr in self.__dict__

    def get(self, attr: str, default: t.Any = None) -> t.Any:
        """Get an attribute."""
        return self.__dict__.get(attr, default)

    def __repr__(self) -> str:  # pragma: no cover
        return f'CurrentAuth({self.actor!r})'

    def __bool__(self) -> bool:
        """Return ``True`` if an actor is present, ``False`` if not."""
        return self.actor is not None

    @property
    def is_anonymous(self) -> bool:
        """Explicit version of ``not bool(current_auth)``."""
        return not bool(self)

    @property
    def is_authenticated(self) -> bool:
        """Explicit version of ``bool(current_auth)``."""
        return bool(self)


def _get_current_auth() -> CurrentAuth:
    """Provide current_auth for the request context."""
    # pylint: disable=too-many-nested-blocks
    # 1. Do we have a request context?
    if request:
        with _get_lock:
            # 2. Does this app context already have current_auth? If so, return it
            ca = getattr(request, '_current_auth', None)
            if ca is None:
                # 3. If not, does it have a known user (Flask-Login protocol)? If so,
                # construct current_auth with it
                request._current_auth = ca = CurrentAuth(  # type: ignore[attr-defined]
                    g.get('_login_user', None)
                )
                # 4. If no existing user, look for a login manager
                if ca.user is None:
                    # 4.1. Check for a login manager and call it. Flask-Login,
                    # Flask-Lastuser or equivalent must add a login_manager
                    if (
                        request
                        and hasattr(current_app, 'login_manager')
                        and hasattr(current_app.login_manager, '_load_user')
                    ):
                        # This call may invoke `current_auth` and result in one
                        # recursive another call to `_get_current_auth`. To make this
                        # work, we use a recursive lock in `_get_lock`, and ensure
                        # `g._current_auth` already exists as a stub
                        current_app.login_manager._load_user()
                    # 4.2. In case the login manager did not call
                    # :func:`add_auth_attribute`, we'll need to do it
                    if ca.user is None:
                        user = g.get('_login_user')
                        if user:
                            object.__setattr__(ca, 'user', user)
                            # Set actor=user only if the login manager did not add
                            # another
                            if ca.actor is None:
                                object.__setattr__(ca, 'actor', user)

        # 5. Return current_auth
        return ca

    # 6. Fallback if there is no request context. Return a blank current_auth
    # so that ``current_auth.is_authenticated`` remains valid for checking status
    # Make this work even when there's no request
    return CurrentAuth(None, is_placeholder=True)


#: A proxy object that hosts state for user authentication, attempting to load
#: state from request context if not already loaded. Returns a
#: :class:`CurrentAuth`. Typical use::
#:
#:     from coaster.auth import current_auth
#:
#:     @app.route('/')
#:     def user_check():
#:         if current_auth:
#:             return "We have a user"
#:         else:
#:             return "User not logged in"
current_auth: CurrentAuth = t.cast(CurrentAuth, LocalProxy(_get_current_auth))
