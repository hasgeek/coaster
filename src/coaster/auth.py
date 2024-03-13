"""
Authentication management
=========================

Coaster provides a :obj:`current_auth` for handling authentication. Login managers must
comply with its API for Coaster's view handlers to work.

If a login manager installs itself as ``current_app.login_manager`` and provides a
``_load_user()`` method, it will be called when :obj:`current_auth` is invoked for the
first time in a request. Login managers can call :func:`add_auth_attribute` to load the
actor (typically the authenticated user) and any other relevant authentication
attributes. For compatibility with Flask-Login, if the login manager fails to call
:func:`add_auth_attribute`, :obj:`current_auth` will attempt to load a user from
``g._login_user``. However, this value will not be trusted unless a login manager is
called, as the app context may be re-used between requests if it was created prior to
request processing.
"""

# pylint: disable=protected-access

from __future__ import annotations

from collections.abc import Sequence
from threading import Lock
from typing import Any, Generic, NoReturn, TypeVar, cast

from flask import Flask, current_app, g
from flask.globals import request_ctx
from werkzeug.local import LocalProxy
from werkzeug.wrappers import Response as BaseResponse

from .utils import InspectableSet

__all__ = [
    'CurrentAuth',
    'GetCurrentAuth',
    'add_auth_attribute',
    'add_auth_anchor',
    'request_has_auth',
    'current_auth',
]


_Response = TypeVar('_Response', bound=BaseResponse)

# For async/greenlet usage, these are presumed to be monkey-patched by greenlet. The
# locks are not necessary for thread-safety since there is no cross-thread context here.
_add_lock = Lock()  # Used by :func:`add_auth_attribute`
_get_lock = Lock()  # Used by :func:`GetCurrentAuth.__call__`
_prop_lock = Lock()  # Used by :meth:`CurrentAuth.__getattr__`

_internal_attrs = {
    'is_placeholder',
    'actor',
    'anchors',
    'is_anonymous',
    'is_authenticated',
}


def add_auth_attribute(attr: str, value: Any, actor: bool = False) -> None:
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
    if attr in _internal_attrs:
        raise AttributeError(f"Attribute name {attr} is reserved by current_auth")

    # Invoking current_auth will also create it on the local stack. We can then proceed
    # to set attributes on it.
    ca = current_auth._get_current_object()
    if ca.is_placeholder:
        raise RuntimeError("current_auth is a placeholder without a request context")

    with _add_lock:
        ca.__dict__[attr] = value

        if attr == 'user':
            # Special-case 'user' for compatibility with Flask-Login
            if g:
                g._login_user = value
            # A user is always an actor
            actor = True

        if actor:
            ca.__dict__['actor'] = value


def add_auth_anchor(anchor: Any) -> None:
    """Add an anchor to current auth (placeholder pending a spec for anchors)."""
    existing = set(current_auth.anchors)
    existing.add(anchor)
    ca = current_auth._get_current_object()
    object.__setattr__(ca, 'anchors', frozenset(existing))


def request_has_auth() -> bool:
    """
    Check if :obj:`current_auth` was accessed for an actor in the current request.

    Helper function that returns True if :obj:`current_auth` was invoked during
    the current request. A login manager can use this during request teardown
    to set cookies or perform other housekeeping functions.
    """
    return (
        bool(request_ctx)
        and hasattr(request_ctx, 'current_auth')
        and 'actor' in request_ctx.current_auth.__dict__
    )


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

    is_placeholder: bool
    permissions: InspectableSet
    anchors: Sequence[Any]
    actor: Any
    user: Any

    def __init__(self, is_placeholder: bool = False) -> None:
        object.__setattr__(self, 'is_placeholder', is_placeholder)
        object.__setattr__(self, 'permissions', InspectableSet())
        object.__setattr__(self, 'anchors', frozenset())
        if is_placeholder:
            object.__setattr__(self, 'actor', None)
            object.__setattr__(self, 'user', None)

    def __setattr__(self, attr: str, value: Any) -> NoReturn:
        if hasattr(self, attr) and getattr(self, attr) is value:
            # This test is used to allow in-place mutations such as:
            # current_auth.permissions |= {extra}
            return  # type: ignore[misc]
        raise TypeError('current_auth is read-only')

    def __delattr__(self, attr: str) -> NoReturn:
        raise TypeError('current_auth is read-only')

    def __contains__(self, attr: str) -> bool:
        """Check for presence of an attribute."""
        return attr in self.__dict__

    def get(self, attr: str, default: Any = None) -> Any:
        """Get an attribute."""
        # This uses :func:`getattr` instead of looking in :attr:`__dict__` because it
        # needs to trigger the first-use activity that happens in :meth:`__getattr__`
        return getattr(self, attr, default)

    def __repr__(self) -> str:  # pragma: no cover
        return f'CurrentAuth(is_placeholder={self.is_placeholder})'

    def __getattr__(self, attr: str) -> Any:
        """Init :class:`CurrentAuth` on first attribute access."""
        with _prop_lock:
            if 'actor' in self.__dict__:
                # CurrentAuth already initialized
                raise AttributeError(attr)
            self.__dict__['actor'] = None
            self.__dict__.setdefault('user', None)
            self._call_login_manager()
            try:
                return self.__dict__[attr]
            except KeyError:
                raise AttributeError(attr) from None

    def _call_login_manager(self) -> None:
        """Call the app's login manager on first access of user or actor (internal)."""
        # Check for an existing user from Flask-Login
        if not request_ctx:
            # There's no request context for a login manager to operate on
            return
        # If there's no existing user, look for a login manager
        if (
            request_ctx
            and hasattr(current_app, 'login_manager')
            and hasattr(current_app.login_manager, '_load_user')
        ):
            current_app.login_manager._load_user()
            # In case the login manager did not call :func:`add_auth_attribute`, we'll
            # need to do it
            if self.__dict__.get('user') is None:
                user = g.get('_login_user')
                if user is not None:
                    self.__dict__['user'] = user
                    # Set actor=user only if the login manager did not add another actor
                    if self.__dict__.get('actor') is None:
                        self.__dict__['actor'] = user

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


def _set_auth_cookie_after_request(response: _Response) -> _Response:
    # TODO
    return response


def init_app(app: Flask) -> None:
    """Optionally initialize current_auth for auth cookie management in an app."""
    app.config.setdefault('AUTH_COOKIE_NAME', 'auth')
    for our_config, flask_config in [
        ('AUTH_COOKIE_DOMAIN', 'SESSION_COOKIE_DOMAIN'),
        ('AUTH_COOKIE_PATH', 'SESSION_COOKIE_PATH'),
        ('AUTH_COOKIE_HTTPONLY', 'SESSION_COOKIE_HTTPONLY'),
        ('AUTH_COOKIE_SECURE', 'SESSION_COOKIE_SECURE'),
        ('PERMANENT_AUTH_LIFETIME', 'PERMANENT_SESSION_LIFETIME'),
    ]:
        app.config.setdefault(our_config, app.config.get(flask_config))
    app.config.setdefault(
        'AUTH_SECRET_KEYS',
        app.config.get('SECRET_KEYS', [app.config.get('SECRET_KEY')]),
    )
    app.after_request(_set_auth_cookie_after_request)


_CurrentAuthType_co = TypeVar('_CurrentAuthType_co', bound=CurrentAuth, covariant=True)


class GetCurrentAuth(Generic[_CurrentAuthType_co]):
    """Helper for :attr:`current_auth` proxy to use a :class:`CurrentAuth` subclass."""

    def __init__(self, cls: type[_CurrentAuthType_co]) -> None:
        self.cls = cls

    def __call__(self) -> _CurrentAuthType_co:
        """Provide :attr:`current_auth` for the request context."""
        # 1. Do we have a request context?
        if request_ctx:
            with _get_lock:
                # 2. Does this request already have current_auth? If so, return it
                ca = getattr(request_ctx, 'current_auth', None)
                if ca is None:
                    # 3. If not, create it
                    ca = self.cls()
                    request_ctx.current_auth = ca  # type: ignore[attr-defined]
                elif not isinstance(ca, self.cls):
                    # If ca is not an instance of self.cls but self.cls is a subclass of
                    # ca.__class__, then re-create with self.cls. This is needed because
                    # there could be more than one version of the `current_auth` local
                    # proxy, and if the default implementation created a default
                    # CurrentAuth instance, but a custom proxy expected a sub-class,
                    # then it must get the sub-class. However, the sub-class must never
                    # be re-cast as the base class.
                    if issubclass(self.cls, ca.__class__):
                        new_ca = self.cls()
                        new_ca.__dict__.update(ca.__dict__)
                        request_ctx.current_auth = new_ca  # type: ignore[attr-defined]
                        ca = new_ca
            # 4. Return current_auth
            return ca

        # 5. Fallback if there is no request context. Return a placeholder current_auth
        # so that ``current_auth.is_authenticated`` remains valid for checking status
        return self.cls(is_placeholder=True)

    @classmethod
    def proxy(cls, subcls: type[_CurrentAuthType_co]) -> _CurrentAuthType_co:
        """Create a local proxy using a specific subclass of :class:`CurrentAuth`."""
        return cast(_CurrentAuthType_co, LocalProxy(cls(subcls)))


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
current_auth = GetCurrentAuth.proxy(CurrentAuth)
