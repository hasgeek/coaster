"""
SQLAlchemy mixin classes
------------------------

Coaster provides a number of mixin classes for SQLAlchemy models. To use in
your Flask app::

    from sqlalchemy.orm import DeclarativeBase
    from flask_sqlalchemy import SQLAlchemy
    from coaster.sqlalchemy import BaseMixin, ModelBase

    class Model(ModelBase, DeclarativeBase):
        '''Model base class.'''

    db = SQLAlchemy(metadata=Model.metadata)
    Model.init_flask_sqlalchemy(db)

    class MyModel(BaseMixin[int], Model):  # Integer serial primary key; alt: UUID
        __tablename__ = 'my_model'

Mixin classes must always appear *before* ``Model`` or ``db.Model`` in your model's
base classes.
"""

# pylint: disable=too-few-public-methods,no-self-argument

from __future__ import annotations

import typing as t
import typing_extensions as te
import warnings
from collections import abc
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import cast, overload
from uuid import UUID, uuid4

from flask import current_app, url_for

try:  # Flask >= 3.0  # pragma: no cover
    from flask.sansio.app import App as FlaskApp
except ModuleNotFoundError:  # Flask < 3.0
    from flask import Flask as FlaskApp

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, declarative_mixin, declared_attr, synonym
from sqlalchemy.sql import func, select
from werkzeug.routing import BuildError

from ..auth import current_auth
from ..typing import ReturnDecorator, WrappedFunc
from ..utils import (
    InspectableSet,
    make_name,
    uuid_from_base58,
    uuid_from_base64,
    uuid_to_base58,
    uuid_to_base64,
)
from ..utils.misc import _punctuation_re
from .comparators import (
    SqlSplitIdComparator,
    SqlUuidB58Comparator,
    SqlUuidB64Comparator,
    SqlUuidHexComparator,
)
from .functions import auto_init_default, failsafe_add
from .immutable_annotation import immutable
from .model import Query, QueryProperty
from .registry import RegistryMixin
from .roles import RoleMixin, with_roles

__all__ = [
    'IdMixin',
    'TimestampMixin',
    'PermissionMixin',
    'UrlDict',
    'UrlForMixin',
    'NoIdMixin',
    'BaseMixin',
    'BaseNameMixin',
    'BaseScopedNameMixin',
    'BaseIdNameMixin',
    'BaseScopedIdMixin',
    'BaseScopedIdNameMixin',
    'CoordinatesMixin',
    'UuidMixin',
    'RoleMixin',
    'RegistryMixin',
]

PkeyType = te.TypeVar('PkeyType', int, UUID, default=int)
# `default=int` is processed by type checkers implementing PEP 696, but seemingly has no
# impact in runtime, so no default will be received in `IdMixin.__init_subclass__`


class PkeyWarning(UserWarning):
    """Warning when the primary key type is not specified as a base class argument."""


@declarative_mixin
class IdMixin(t.Generic[PkeyType]):
    """
    Provides the :attr:`id` primary key column.

    Provides an auto-incrementing integer primary key by default. However, can be told
    to provide a UUID primary key instead::

        from uuid import UUID

        class MyModel(IdMixin[UUID], Model):  # or IdMixin[int]
            ...

        class OtherModel(BaseMixin[UUID], Model):
            ...

    The legacy method using a flag also works, but will break type discovery for the id
    column in static type analysis (mypy or pyright)::

        class MyModel(IdMixin, Model):
            __uuid_primary_key__ = True

    :class:`IdMixin` is a base class for :class:`BaseMixin`, the standard base class.
    """

    query_class: t.ClassVar[t.Type[Query]] = Query
    query: t.ClassVar[QueryProperty]
    #: Use UUID primary key? If yes, UUIDs are automatically generated without
    #: the need to commit to the database. Do not set this directly; pass UUID as a
    #: Generic argument to the base class instead: ``class MyModel(IdMixin[UUID])``.
    __uuid_primary_key__: t.ClassVar[bool] = False

    def __init_subclass__(cls, *args: t.Any, **kwargs: t.Any) -> None:
        # If a generic arg is specified, set `__uuid_primary_key__` from it. Do this
        # before `super().__init_subclass__` calls SQLAlchemy's implementation,
        # which processes the `declared_attr` classmethods into class attributes. They
        # depend on `__uuid_primary_key__` already being set on the class.
        if '__uuid_primary_key__' in cls.__dict__:
            # This is only a warning, but it will turn into an error below if the value
            # varies from the generic arg
            warnings.warn(
                f"`{cls.__qualname__}` must specify primary key type as `int` or `UUID`"
                " to the base class (`IdMixin[int]` or `IdMixin[UUID]`) instead of"
                " specifying `__uuid_primary_key__` directly",
                PkeyWarning,
            )

        for base in te.get_original_bases(cls):
            # XXX: Is this the correct way to examine a generic subclass that may have
            # more generic args in a redefined order? The docs suggest Generic args are
            # assumed positional, but they may be reordered, so how do we determine the
            # arg to IdMixin itself? There is no variant of `cls.mro()` that returns
            # original base classes with their generic args. For now, we expect that
            # generic subclasses _must_ use the static `PkeyType` typevar in their
            # definitions. This may need to be revisited with Python 3.12's new type
            # parameter syntax (via PEP 695).
            origin_base = t.get_origin(base)
            if (
                origin_base is not None
                and issubclass(origin_base, IdMixin)
                and PkeyType in origin_base.__parameters__  # type: ignore[misc]
            ):
                pkey_type = t.get_args(base)[
                    origin_base.__parameters__.index(PkeyType)  # type: ignore[misc]
                ]
                if pkey_type is int:
                    if (
                        '__uuid_primary_key__' in cls.__dict__
                        and cls.__uuid_primary_key__ is not False
                    ):
                        raise TypeError(
                            f"{cls.__qualname__}.__uuid_primary_key__ conflicts with"
                            " pkey type argument to the base class"
                        )
                    cls.__uuid_primary_key__ = False
                elif pkey_type is UUID:
                    if (
                        '__uuid_primary_key__' in cls.__dict__
                        and cls.__uuid_primary_key__ is not True
                    ):
                        raise TypeError(
                            f"{cls.__qualname__}.__uuid_primary_key__ conflicts with"
                            " pkey type argument to the base class"
                        )
                    cls.__uuid_primary_key__ = True
                elif pkey_type is PkeyType:  # type: ignore[misc]
                    # This must be a generic subclass, ignore it
                    pass
                else:
                    raise TypeError(f"Unsupported primary key type in {base!r}")
                break

        super().__init_subclass__(*args, **kwargs)

    @immutable
    @declared_attr
    def id(cls) -> Mapped[PkeyType]:  # noqa: A003
        """Database identity for this model."""
        if cls.__uuid_primary_key__:
            return sa.orm.mapped_column(
                sa.Uuid, default=uuid4, primary_key=True, nullable=False
            )

        return sa.orm.mapped_column(sa.Integer, primary_key=True, nullable=False)

    @declared_attr
    def url_id(cls) -> Mapped[str]:
        """URL-safe representation of the id value, using hex for a UUID id."""
        if cls.__uuid_primary_key__:

            def url_id_uuid_func(self: te.Self) -> str:
                """URL-safe representation of the UUID id as a hex value."""
                return cast(UUID, self.id).hex

            def url_id_uuid_comparator(cls: t.Type) -> SqlUuidHexComparator:
                """Compare two hex UUID values."""
                return SqlUuidHexComparator(cls.id)

            url_id_uuid_func.__name__ = 'url_id'
            url_id_uuid_func.__doc__ = url_id_uuid_func.__doc__
            url_id_property = hybrid_property(url_id_uuid_func).comparator(
                url_id_uuid_comparator
            )
            return url_id_property  # type: ignore[return-value]

        def url_id_int_func(self: te.Self) -> str:
            """URL-safe representation of the integer id as a string."""
            return str(self.id)

        def url_id_int_comparator(cls: t.Type) -> SqlSplitIdComparator:
            """Compare two integer id values."""
            return SqlSplitIdComparator(cls.id)

        url_id_int_func.__name__ = 'url_id'
        url_id_int_func.__doc__ = url_id_int_func.__doc__
        url_id_property = hybrid_property(url_id_int_func).comparator(
            url_id_int_comparator
        )
        return url_id_property  # type: ignore[return-value]

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__} {self.id}>'


@declarative_mixin
class UuidMixin:
    """
    Provides a :attr:`uuid` attribute.

    If the class has :attr:`__uuid_primary_key__` set to `True`, :attr:`uuid` becomes
    an alias to the existing UUID :attr:`id` column. If not, a new UUID column is
    provided.

    Also provides representations of the UUID value in hex (:attr:`uuid_hex`), URL-safe
    Base64 (:attr:`uuid_b64`) and Base58 (:attr:`uuid_b58`). :attr:`uuid_hex` is
    recommended over :attr:`IdMixin.url_id` as that name is ambiguous. Base58 is
    recommended over Base64 for URLs that contain text slugs as the Base64 alphabet
    includes the ``_`` and ``-`` characters that may also appear in text slugs.

    :attr:`buid` is a legacy alias for :attr:`uuid_b64` and should not be used in new
    code.
    """

    __uuid_primary_key__: t.ClassVar[bool]

    @immutable
    @with_roles(read={'all'})
    @declared_attr
    @classmethod
    def uuid(cls) -> Mapped[UUID]:
        """UUID column, or synonym to existing :attr:`id` column if that is a UUID."""
        if hasattr(cls, '__uuid_primary_key__') and cls.__uuid_primary_key__:
            return synonym('id')
        return sa.orm.mapped_column(sa.Uuid, default=uuid4, unique=True, nullable=False)

    @hybrid_property
    def uuid_hex(self) -> str:
        """URL-friendly UUID representation as a hex string."""
        return self.uuid.hex

    @uuid_hex.inplace.comparator
    @classmethod
    def _uuid_hex_comparator(cls) -> SqlUuidHexComparator:
        """Return SQL comparator for UUID in hex format."""
        return SqlUuidHexComparator(cls.uuid)

    @hybrid_property
    def uuid_b64(self) -> str:
        """URL-friendly UUID representation, using URL-safe Base64 (BUID)."""
        return uuid_to_base64(self.uuid)

    @uuid_b64.inplace.setter
    def _uuid_b64_setter(self, value: str) -> None:
        """Set UUID in Base64 format."""
        self.uuid = uuid_from_base64(value)

    @uuid_b64.inplace.comparator
    @classmethod
    def _uuid_b64_comparator(cls) -> SqlUuidB64Comparator:
        """Return SQL comparator for UUID in Base64 format."""
        return SqlUuidB64Comparator(cls.uuid)

    #: Retain `buid` as a public attribute for backward compatibility
    buid = uuid_b64

    #: Since `with_roles` annotates the attribute, both aliases (uuid_b64 and buid)
    #: will become public to the `all` role as a result of this annotation.
    with_roles(uuid_b64, read={'all'})

    @hybrid_property
    def uuid_b58(self) -> str:
        """URL-friendly UUID representation, using Base58 with the Bitcoin alphabet."""
        return uuid_to_base58(self.uuid)

    @uuid_b58.inplace.setter
    def _uuid_b58_setter(self, value: str) -> None:
        self.uuid = uuid_from_base58(value)

    @uuid_b58.inplace.comparator
    def _uuid_b58_comparator(cls) -> SqlUuidB58Comparator:
        """Return SQL comparator for UUID in Base58 format."""
        return SqlUuidB58Comparator(cls.uuid)

    with_roles(uuid_b58, read={'all'})


# Also see functions.make_timestamp_columns
@declarative_mixin
class TimestampMixin:
    """Provides the :attr:`created_at` and :attr:`updated_at` audit timestamps."""

    query_class: t.ClassVar[t.Type[Query]] = Query
    query: t.ClassVar[QueryProperty]
    __with_timezone__: t.ClassVar[bool] = False

    @immutable
    @declared_attr
    def created_at(cls) -> Mapped[datetime]:
        """Timestamp for when this instance was created, in UTC."""
        return sa.orm.mapped_column(
            sa.TIMESTAMP(timezone=cls.__with_timezone__),
            default=func.utcnow(),
            nullable=False,
        )

    @declared_attr
    def updated_at(cls) -> Mapped[datetime]:
        """Timestamp for when this instance was last updated (via the app), in UTC."""
        return sa.orm.mapped_column(
            sa.TIMESTAMP(timezone=cls.__with_timezone__),
            default=func.utcnow(),
            onupdate=func.utcnow(),
            nullable=False,
        )


@declarative_mixin
class PermissionMixin:
    """
    Provides the :meth:`permissions` method.

    Base class for :class:`BaseMixin`. The permissions mechanism is deprecated. New code
    should use the role granting mechanism in :class:`RoleMixin`.
    """

    def permissions(
        self, actor: t.Any, inherited: t.Optional[t.Set[str]] = None
    ) -> t.Set[str]:
        """Return permissions available to the given user on this object."""
        if inherited is not None:
            return set(inherited)
        return set()

    @property
    def current_permissions(self) -> InspectableSet[set]:
        """
        Available permissions for the current user on this object.

        This property depends on `current_auth` to provide the current user and
        existing permissions.
        """
        # current_auth.permissions will be an InspectableSet.
        # Cast it back into a regular set so that the permissions method can call the
        # .add() and .update() methods on it. If the set is empty, pass None instead.
        # This will signal to BaseScoped* base classes to consult their parents for
        # additional permissions.
        return InspectableSet(
            self.permissions(current_auth.actor, set(current_auth.permissions) or None)
        )


_UR = t.TypeVar('_UR', bound='NoIdMixin')


@dataclass
class UrlEndpointData:
    endpoint: str
    paramattrs: t.Dict[str, t.Union[str, t.Tuple[str, ...], t.Callable[[_UR], str]]]
    external: t.Optional[bool]
    roles: t.Optional[t.Collection[str]]
    requires_kwargs: bool


class UrlDictStub:
    """
    Dictionary-based access to URLs for a model instance, used by :class:`UrlForMixin`.

    This class proxies to :meth:`UrlForMixin.url_for` for keyword-based lookup. Uses
    :attr:`UrlForMixin.url_for_endpoints` for enumeration, but with URLs limited to
    those available under current roles.
    """

    @overload
    def __get__(self, obj: None, cls: t.Type[_UR]) -> te.Self:
        ...

    @overload
    def __get__(self, obj: _UR, cls: t.Type[_UR]) -> UrlDict[_UR]:
        ...

    def __get__(
        self, obj: t.Optional[_UR], cls: t.Type[_UR]
    ) -> t.Union[te.Self, UrlDict[_UR]]:
        if obj is None:
            return self
        return UrlDict(obj)


class UrlDict(abc.Mapping, t.Generic[_UR]):
    """Provides dictionary access to an object's URLs."""

    def __init__(self, obj: _UR) -> None:
        self.obj = obj

    def __getitem__(self, key: str) -> str:
        try:
            return self.obj.url_for(key, _external=True)
        except BuildError as exc:
            raise KeyError(key) from exc

    def __len__(self) -> int:
        # pylint: disable=protected-access
        return len(self.obj.url_for_endpoints[None]) + (
            len(
                self.obj.url_for_endpoints.get(
                    current_app._get_current_object(), {}  # type: ignore[attr-defined]
                )
            )
            if current_app
            else 0
        )

    def __iter__(self) -> t.Iterator[str]:
        # 1. Iterate through all actions available to the None app and to current_app
        # 2. If the action requires specific roles, confirm overlap with current_roles
        # 3. Confirm the action does not require additional parameters
        # 4. Yield whatever passes the tests
        current_roles = self.obj.roles_for(current_auth.actor)
        for app, app_actions in self.obj.url_for_endpoints.items():
            # pylint: disable=protected-access
            if app is None or (
                current_app
                and app
                is current_app._get_current_object()  # type: ignore[attr-defined]
            ):
                for action, endpoint_data in app_actions.items():
                    if not endpoint_data.requires_kwargs and (
                        endpoint_data.roles is None
                        or current_roles.has_any(endpoint_data.roles)
                    ):
                        yield action


class UrlForMixin:
    """Provides a :meth:`url_for` method used by BaseMixin-derived classes."""

    #: Mapping of {app: {action: UrlEndpointData}}. The same action can point to
    #: different endpoints in different apps. The app may also be None as fallback. Each
    #: subclass will get its own dictionary. This particular dictionary is only used as
    #: an inherited fallback.
    url_for_endpoints: t.ClassVar[
        t.Dict[t.Optional[FlaskApp], t.Dict[str, UrlEndpointData]]
    ] = {None: {}}
    #: Mapping of {app: {action: (classview, attr)}}
    view_for_endpoints: t.ClassVar[
        t.Dict[t.Optional[FlaskApp], t.Dict[str, t.Tuple[t.Any, str]]]
    ] = {}

    #: Dictionary of URLs available on this object
    urls = UrlDictStub()

    def url_for(self, action: str = 'view', **kwargs) -> str:
        """Return public URL to this instance for a given action (default 'view')."""
        # pylint: disable=protected-access
        app = (
            current_app._get_current_object()  # type: ignore[attr-defined]
            if current_app
            else None
        )
        if app is not None and action in self.url_for_endpoints.get(app, {}):
            endpoint_data = self.url_for_endpoints[app][action]
        else:
            try:
                endpoint_data = self.url_for_endpoints[None][action]
            except KeyError as exc:
                raise BuildError(action, kwargs, 'GET') from exc
        params = {}
        for param, attr in list(endpoint_data.paramattrs.items()):
            if isinstance(attr, tuple):
                # attr is a tuple containing:
                # 1. ('parent', 'name') --> self.parent.name
                # 2. ('**entity', 'name') --> kwargs['entity'].name
                if attr[0].startswith('**'):
                    item = kwargs.pop(attr[0][2:])
                    attr = attr[1:]
                else:
                    item = self
                for subattr in attr:
                    item = getattr(item, subattr)
                params[param] = item
            elif callable(attr):
                # TODO: Support callables expecting kwargs
                params[param] = attr(self)  # type: ignore[type-var]
            else:
                params[param] = getattr(self, attr)
        if endpoint_data.external is not None:
            params['_external'] = endpoint_data.external

        # FIXME: Why do we have this? It needs test coverage
        params.update(kwargs)  # Let kwargs override params

        # url_for from flask
        return url_for(endpoint_data.endpoint, **params)

    @property
    def absolute_url(self) -> t.Optional[str]:
        """Absolute URL to this object."""
        try:
            return self.url_for(_external=True)
        except BuildError:
            return None

    @classmethod
    def is_url_for(
        cls,
        __action: str,
        __endpoint: t.Optional[str] = None,
        __app: t.Optional[FlaskApp] = None,
        /,
        _external: t.Optional[bool] = None,
        **paramattrs: t.Union[str, t.Tuple[str, ...], t.Callable[[t.Any], str]],
    ) -> ReturnDecorator:
        """
        Decorator that registers a view as a :meth:`url_for` target.

        :param __action: Action to register a URL under
        :param __endpoint: View endpoint name to pass to Flask's ``url_for``
        :param __app: The app to register this action on (if using multiple apps)
        :param _external: If `True`, URLs are assumed to be external-facing by default
        :param dict paramattrs: Mapping of URL parameter to attribute on the object
        """

        def decorator(f: WrappedFunc) -> WrappedFunc:
            cls.register_endpoint(
                action=__action,
                endpoint=__endpoint or f.__name__,
                app=__app,
                external=_external,
                paramattrs=paramattrs,
            )
            return f

        return decorator

    @classmethod
    def register_endpoint(
        cls,
        action: str,
        *,
        endpoint: str,
        app: t.Optional[FlaskApp],
        paramattrs: t.Mapping[
            str, t.Union[str, t.Tuple[str, ...], t.Callable[[t.Any], str]]
        ],
        roles: t.Optional[t.Collection[str]] = None,
        external: t.Optional[bool] = None,
    ) -> None:
        """
        Register an endpoint to a :meth:`url_for` action.

        :param view_func: View handler to be registered
        :param str action: Action to register a URL under
        :param str endpoint: View endpoint name to pass to Flask's ``url_for``
        :param app: Flask app (default: `None`)
        :param external: If `True`, URLs are assumed to be external-facing by default
        :param roles: Roles to which this URL is available, required by :class:`UrlDict`
        :param dict paramattrs: Mapping of URL parameter to attribute name on the object
        """
        if 'url_for_endpoints' not in cls.__dict__:
            cls.url_for_endpoints = {
                None: {}
            }  # Stick it into the class with the first endpoint
        cls.url_for_endpoints.setdefault(app, {})

        paramattrs = dict(paramattrs)
        for keyword, attrs in paramattrs.items():
            if isinstance(attrs, str) and '.' in attrs:
                paramattrs[keyword] = tuple(attrs.split('.'))
        requires_kwargs = False
        for attrs in paramattrs.values():
            if isinstance(attrs, tuple) and attrs[0].startswith('**'):
                requires_kwargs = True
                break
        cls.url_for_endpoints[app][action] = UrlEndpointData(
            endpoint=endpoint,
            paramattrs=paramattrs,
            external=external,
            roles=roles,
            requires_kwargs=requires_kwargs,
        )

    @classmethod
    def register_view_for(
        cls, app: t.Optional[FlaskApp], action: str, classview: t.Any, attr: str
    ) -> None:
        """Register a classview and viewhandler for a given app and action."""
        if 'view_for_endpoints' not in cls.__dict__:
            cls.view_for_endpoints = {}
        cls.view_for_endpoints.setdefault(app, {})[action] = (classview, attr)

    def view_for(self, action: str = 'view') -> t.Any:
        """Return the classview viewhandler that handles the specified action."""
        # pylint: disable=protected-access
        app = current_app._get_current_object()  # type: ignore[attr-defined]
        view, attr = self.view_for_endpoints[app][action]
        return getattr(view(self), attr)

    def classview_for(self, action: str = 'view') -> t.Any:
        """Return the classview containing the viewhandler for the specified action."""
        # pylint: disable=protected-access
        app = current_app._get_current_object()  # type: ignore[attr-defined]
        return self.view_for_endpoints[app][action][0](self)


@declarative_mixin
class NoIdMixin(TimestampMixin, PermissionMixin, RoleMixin, RegistryMixin, UrlForMixin):
    """
    Mixin that combines all mixin classes except :class:`IdMixin`.

    For use anywhere the timestamp columns and helper methods are required, but an id
    column is not.
    """

    def _set_fields(self, fields: t.Mapping[str, t.Any]) -> None:
        """Set field values."""
        for f in fields:
            if hasattr(self, f):
                setattr(self, f, fields[f])
            else:
                raise TypeError(
                    f"'{f}' is an invalid argument for {self.__class__.__name__}"
                )


@declarative_mixin
class BaseMixin(IdMixin[PkeyType], NoIdMixin):
    """Base mixin class for all tables that have an id column."""


@declarative_mixin
class BaseNameMixin(BaseMixin[PkeyType]):
    """
    Base mixin class for named objects.

    .. versionchanged:: 0.5.0
        If you used BaseNameMixin in your app before Coaster 0.5.0:
        :attr:`name` can no longer be a blank string in addition to being
        non-null. This is configurable and enforced with a SQL CHECK constraint,
        which needs a database migration:

    ::

        for tablename in ['named_table1', 'named_table2', ...]:
            # Drop CHECK constraint first in case it was already present
            op.drop_constraint(tablename + '_name_check', tablename)
            # Create CHECK constraint
            op.create_check_constraint(
                tablename + '_name_check',
                tablename,
                "name <> ''")
    """

    #: Prevent use of these reserved names
    reserved_names: t.ClassVar[t.Collection[str]] = []
    #: Allow blank names after all?
    __name_blank_allowed__: t.ClassVar[bool] = False
    #: How long are names and title allowed to be? `None` for unlimited length
    __name_length__: t.ClassVar[t.Optional[int]] = 250
    __title_length__: t.ClassVar[t.Optional[int]] = 250

    @declared_attr
    def name(cls) -> Mapped[str]:
        """Column for URL name of this object, unique across all instances."""
        if cls.__name_length__ is None:
            column_type = sa.Unicode()
        else:
            column_type = sa.Unicode(cls.__name_length__)
        if cls.__name_blank_allowed__:
            return sa.orm.mapped_column(column_type, nullable=False, unique=True)
        return sa.orm.mapped_column(
            column_type, sa.CheckConstraint("name <> ''"), nullable=False, unique=True
        )

    @declared_attr
    def title(cls) -> Mapped[str]:
        """Column for title of this object."""
        if cls.__title_length__ is None:
            column_type = sa.Unicode()
        else:
            column_type = sa.Unicode(cls.__title_length__)
        return sa.orm.mapped_column(column_type, nullable=False)

    @property
    def title_for_name(self) -> str:
        """
        Variant of :attr:`title` suitable for :meth:`make_name`.

        Returns :attr:`title` unmodified, but subclasses may override.
        """
        return self.title

    def __init__(self, *args, **kw) -> None:
        super().__init__(*args, **kw)
        if not self.name:
            self.make_name()

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__} {self.name} "{self.title}">'

    def __format__(self, format_spec: str) -> str:
        """Format using self.title."""
        if format_spec:
            # pylint: disable=not-callable
            return (self.title or '').__format__(format_spec)
        return self.title or ''

    @classmethod
    def get(cls, name: str) -> t.Optional[te.Self]:
        """Get an instance matching the name."""
        return cls.query.filter_by(name=name).one_or_none()

    @classmethod
    def upsert(cls, name: str, **fields) -> te.Self:
        """Insert or update an instance."""
        instance = cls.get(name)
        if instance is not None:
            instance._set_fields(fields)  # pylint: disable=protected-access
        else:
            instance = cls(name=name, **fields)
            instance = failsafe_add(cls.query.session, instance, name=name)
        return instance

    def make_name(self, reserved: t.Collection[str] = ()) -> None:
        """
        Autogenerate :attr:`name` from the :attr:`title` (via :attr:`title_for_name`).

        If the auto-generated name is already in use in this model, :meth:`make_name`
        tries again by suffixing numbers starting with 2 until an available name is
        found.

        :param reserved: Reserved names unavailable for use. Complements the
            :attr:`reserved_names` collection.
        """
        if self.title:  # pylint: disable=using-constant-test
            if sa.inspect(self).has_identity:  # type: ignore[union-attr]

                def checkused(c: str) -> bool:
                    # pylint: disable=comparison-with-callable
                    return bool(
                        c in reserved
                        or c in self.reserved_names
                        or self.__class__.query.filter(self.__class__.id != self.id)
                        .filter_by(name=c)
                        .notempty()
                    )

            else:

                def checkused(c: str) -> bool:
                    return bool(
                        c in reserved
                        or c in self.reserved_names
                        or self.__class__.query.filter_by(name=c).notempty()
                    )

            with self.__class__.query.session.no_autoflush:
                self.name = make_name(
                    self.title_for_name,
                    maxlength=self.__name_length__ or 50,
                    checkused=checkused,
                )


@declarative_mixin
class BaseScopedNameMixin(BaseMixin[PkeyType]):
    """
    Base mixin class for named objects within containers.

    When using this class, you must provide an model-level attribute "parent" that is a
    synonym for the parent object. You must also create a unique constraint on 'name'
    in combination with the parent foreign key. Sample use case in Flask::

        class Event(BaseScopedNameMixin, Model):
            __tablename__ = 'event'
            organizer_id: Mapped[int] = sa.orm.mapped_column(sa.ForeignKey(
                'organizer.id'
            ))
            organizer: Mapped[Organizer] = relationship(Organizer)
            parent = sa.orm.synonym('organizer')
            __table_args__ = (sa.UniqueConstraint('organizer_id', 'name'),)

    .. versionchanged:: 0.5.0
        If you used BaseScopedNameMixin in your app before Coaster 0.5.0:
        :attr:`name` can no longer be a blank string in addition to being
        non-null. This is configurable and enforced with a SQL CHECK constraint,
        which needs a database migration:

    ::

        for tablename in ['named_table1', 'named_table2', ...]:
            # Drop CHECK constraint first in case it was already present
            op.drop_constraint(tablename + '_name_check', tablename)
            # Create CHECK constraint
            op.create_check_constraint(
                tablename + '_name_check',
                tablename,
                "name <> ''")
    """

    #: Prevent use of these reserved names
    reserved_names: t.ClassVar[t.Collection[str]] = []
    #: Allow blank names after all?
    __name_blank_allowed__: t.ClassVar[bool] = False
    #: How long are names and title allowed to be? `None` for unlimited length
    __name_length__: t.ClassVar[t.Optional[int]] = 250
    __title_length__: t.ClassVar[t.Optional[int]] = 250

    #: Specify expected type for a 'parent' attr
    parent: t.Any

    @declared_attr
    def name(cls) -> Mapped[str]:
        """Column for URL name of this object, unique within a parent container."""
        if cls.__name_length__ is None:
            column_type = sa.Unicode()
        else:
            column_type = sa.Unicode(cls.__name_length__)
        if cls.__name_blank_allowed__:
            return sa.orm.mapped_column(column_type, nullable=False)
        return sa.orm.mapped_column(
            column_type, sa.CheckConstraint("name <> ''"), nullable=False
        )

    @declared_attr
    def title(cls) -> Mapped[str]:
        """Column for title of this object."""
        if cls.__title_length__ is None:
            column_type = sa.Unicode()
        else:
            column_type = sa.Unicode(cls.__title_length__)
        return sa.orm.mapped_column(column_type, nullable=False)

    def __init__(self, *args, **kw) -> None:
        super().__init__(*args, **kw)
        if self.parent and not self.name:
            self.make_name()

    def __repr__(self) -> str:
        return (
            f'<{self.__class__.__name__} {self.name} "{self.title}" of {self.parent!r}>'
        )

    def __format__(self, format_spec: str) -> str:
        """Format using self.title."""
        if format_spec:
            # pylint: disable=not-callable
            return (self.title or '').__format__(format_spec)
        return self.title or ''

    @classmethod
    def get(cls, parent: t.Any, name: str) -> t.Optional[te.Self]:
        """Get an instance matching the parent and name."""
        return cls.query.filter_by(parent=parent, name=name).one_or_none()

    @classmethod
    def upsert(cls, parent: t.Any, name: str, **fields) -> te.Self:
        """Insert or update an instance."""
        instance = cls.get(parent, name)
        if instance is not None:
            instance._set_fields(fields)  # pylint: disable=protected-access
        else:
            instance = cls(parent=parent, name=name, **fields)
            instance = failsafe_add(
                cls.query.session, instance, parent=parent, name=name
            )
        return instance

    def make_name(self, reserved: t.Collection[str] = ()) -> None:
        """
        Autogenerate :attr:`name` from the :attr:`title` (via :attr:`title_for_name`).

        If the auto-generated name is already in use in this model, :meth:`make_name`
        tries again by suffixing numbers starting with 2 until an available name is
        found.
        """
        if self.title:  # pylint: disable=using-constant-test
            if sa.inspect(self).has_identity:  # type: ignore[union-attr]

                def checkused(c: str) -> bool:
                    return bool(
                        c in reserved
                        or c in self.reserved_names
                        or self.__class__.query.filter(
                            self.__class__.id != self.id  # pylint: disable=W0143
                        )
                        .filter_by(name=c, parent=self.parent)
                        .notempty()
                    )

            else:

                def checkused(c: str) -> bool:
                    return bool(
                        c in reserved
                        or c in self.reserved_names
                        or self.__class__.query.filter_by(
                            name=c, parent=self.parent
                        ).notempty()
                    )

            with self.__class__.query.session.no_autoflush:
                self.name = make_name(
                    self.title_for_name,
                    maxlength=self.__name_length__ or 250,
                    checkused=checkused,
                )

    @property
    def short_title(self) -> str:
        """Abbreviated title that subtracts the parent's title from this instance's."""
        if (
            self.title
            and self.parent is not None
            and hasattr(self.parent, 'title')
            and self.parent.title
            and self.title.startswith(self.parent.title)
        ):
            short = self.title[len(self.parent.title) :].strip()
            match = _punctuation_re.match(short)
            if match:
                short = short[match.end() :].strip()
            if short:
                return short
        return self.title

    @property
    def title_for_name(self) -> str:
        """
        Variant of :attr:`title` suitable for :meth:`make_name`.

        Returns :attr:`short_title`, but subclasses may override.
        """
        return self.short_title

    def permissions(
        self, actor: t.Any, inherited: t.Optional[t.Set[str]] = None
    ) -> t.Set[str]:
        """Permissions for this model, plus permissions inherited from the parent."""
        if inherited is not None:
            return inherited | super().permissions(actor)
        if self.parent is not None and isinstance(self.parent, PermissionMixin):
            return self.parent.permissions(actor) | super().permissions(actor)
        return super().permissions(actor)


@declarative_mixin
class BaseIdNameMixin(BaseMixin[PkeyType]):
    """
    Base mixin class for named objects with an id tag.

    .. versionchanged:: 0.5.0
        If you used BaseIdNameMixin in your app before Coaster 0.5.0:
        :attr:`name` can no longer be a blank string in addition to being
        non-null. This is configurable and enforced with a SQL CHECK constraint,
        which needs a database migration:

    ::

        for tablename in ['named_table1', 'named_table2', ...]:
            # Drop CHECK constraint first in case it was already present
            op.drop_constraint(tablename + '_name_check', tablename)
            # Create CHECK constraint
            op.create_check_constraint(
                tablename + '_name_check',
                tablename,
                "name <> ''")
    """

    #: Allow blank names after all?
    __name_blank_allowed__: t.ClassVar[bool] = False
    #: How long are names and title allowed to be? `None` for unlimited length
    __name_length__: t.ClassVar[t.Optional[int]] = 250
    __title_length__: t.ClassVar[t.Optional[int]] = 250

    @declared_attr
    def name(cls) -> Mapped[str]:
        """Column for the URL name of this object, non-unique."""
        if cls.__name_length__ is None:
            column_type = sa.Unicode()
        else:
            column_type = sa.Unicode(cls.__name_length__)
        if cls.__name_blank_allowed__:
            return sa.orm.mapped_column(column_type, nullable=False)
        return sa.orm.mapped_column(
            column_type, sa.CheckConstraint("name <> ''"), nullable=False
        )

    @declared_attr
    def title(cls) -> Mapped[str]:
        """Column for the title of this object."""
        if cls.__title_length__ is None:
            column_type = sa.Unicode()
        else:
            column_type = sa.Unicode(cls.__title_length__)
        return sa.orm.mapped_column(column_type, nullable=False)

    @property
    def title_for_name(self) -> str:
        """
        Variant of :attr:`title` suitable for :meth:`make_name`.

        Returns :attr:`title` unmodified, but subclasses may override.
        """
        return self.title

    def __init__(self, *args, **kw) -> None:
        super().__init__(*args, **kw)
        if not self.name:
            self.make_name()

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__} {self.url_id_name} "{self.title}">'

    def __format__(self, format_spec: str) -> str:
        """Format using self.title."""
        if format_spec:
            # pylint: disable=not-callable
            return (self.title or '').__format__(format_spec)
        return self.title or ''

    def make_name(self) -> None:
        """Autogenerate a :attr:`name` from :attr:`title_for_name`."""
        if self.title:  # pylint: disable=using-constant-test
            self.name = make_name(
                self.title_for_name, maxlength=self.__name_length__ or 250
            )

    @hybrid_property
    def url_id_name(self) -> str:
        """Id and name in ``id-name`` format for use in URLs."""
        return f'{self.url_id}-{self.name}'

    @url_id_name.inplace.comparator
    @classmethod
    def _url_id_name_comparator(
        cls,
    ) -> t.Union[SqlUuidHexComparator, SqlSplitIdComparator]:
        """Return SQL comparator for id and name."""
        if cls.__uuid_primary_key__:
            return SqlUuidHexComparator(cls.id, splitindex=0)
        return SqlSplitIdComparator(cls.id, splitindex=0)

    url_name = url_id_name  # Legacy name

    @hybrid_property
    def url_name_uuid_b58(self) -> str:
        """
        Name and UUID in Base58 rendering, in ``name-uuid`` format, for use in URLs.

        To use this, the class must derive from :class:`UuidMixin` as that provides
        the ``uuid_b58`` property.
        """
        return f'{self.name}-{self.uuid_b58}'  # type: ignore[attr-defined]

    @url_name_uuid_b58.inplace.comparator
    @classmethod
    def _url_name_uuid_b58_comparator(cls) -> SqlUuidB58Comparator:
        """Return SQL comparator for name and UUID in Base58 format."""
        return SqlUuidB58Comparator(
            cls.uuid, splitindex=-1  # type: ignore[attr-defined]
        )


@declarative_mixin
class BaseScopedIdMixin(BaseMixin[PkeyType]):
    """
    Base mixin class for objects with an id that is unique within a parent.

    Implementations must provide a 'parent' attribute that is either a relationship
    or a synonym to a relationship referring to the parent object, and must
    declare a unique constraint between url_id and the parent. Sample use case in
    Flask::

        class Issue(BaseScopedIdMixin, Model):
            __tablename__ = 'issue'
            event_id: Mapped[int] = sa.orm.mapped_column(sa.ForeignKey('event.id'))
            event: Mapped[Event] = relationship(Event)
            parent = sa.orm.synonym('event')
            __table_args__ = (sa.UniqueConstraint('event_id', 'url_id'),)
    """

    #: Specify expected type for a 'parent' attr
    parent: t.Any

    # FIXME: Rename this to `scoped_id` and provide a migration guide.
    @with_roles(read={'all'})
    @declared_attr
    def url_id(cls) -> Mapped[int]:  # type: ignore[override]
        """Column for an id number that is unique within the parent container."""
        return sa.orm.mapped_column(sa.Integer, nullable=False)

    def __init__(self, *args, **kw) -> None:
        super().__init__(*args, **kw)
        if self.parent:
            self.make_id()

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__} {self.url_id} of {self.parent!r}>'

    @classmethod
    def get(cls, parent: t.Any, url_id: t.Union[str, int]) -> t.Optional[te.Self]:
        """Get an instance matching the parent and url_id."""
        return cls.query.filter_by(parent=parent, url_id=url_id).one_or_none()

    def make_id(self) -> None:
        """Create a new URL id that is unique to the parent container."""
        if self.url_id is None:  # Set id only if empty
            self.url_id = (
                # pylint: disable=not-callable
                select(func.coalesce(func.max(self.__class__.url_id + 1), 1))
                .where(
                    self.__class__.parent == self.parent,
                )
                .scalar_subquery()
            )

    def permissions(
        self, actor: t.Any, inherited: t.Optional[t.Set[str]] = None
    ) -> t.Set[str]:
        """Permissions for this model, plus permissions inherited from the parent."""
        if inherited is not None:
            return inherited | super().permissions(actor)
        if self.parent is not None and isinstance(self.parent, PermissionMixin):
            return self.parent.permissions(actor) | super().permissions(actor)
        return super().permissions(actor)


@declarative_mixin
class BaseScopedIdNameMixin(BaseScopedIdMixin[PkeyType]):
    """
    Base mixin class for named objects with an id tag that is unique within a parent.

    Implementations must provide a 'parent' attribute that is a synonym to the parent
    relationship, and must declare a unique constraint between url_id and the parent.
    Sample use case in Flask::

        class Event(BaseScopedIdNameMixin, Model):
            __tablename__ = 'event'
            organizer_id: Mapped[int] = sa.orm.mapped_column(sa.ForeignKey(
                'organizer.id'
            ))
            organizer: Mapped[Organizer] = relationship(Organizer)
            parent = sa.orm.synonym('organizer')
            __table_args__ = (sa.UniqueConstraint('organizer_id', 'url_id'),)

    .. versionchanged:: 0.5.0
        If you used BaseScopedIdNameMixin in your app before Coaster 0.5.0:
        :attr:`name` can no longer be a blank string in addition to being
        non-null. This is configurable and enforced with a SQL CHECK constraint,
        which needs a database migration:

    ::

        for tablename in ['named_table1', 'named_table2', ...]:
            # Drop CHECK constraint first in case it was already present
            op.drop_constraint(tablename + '_name_check', tablename)
            # Create CHECK constraint
            op.create_check_constraint(
                tablename + '_name_check',
                tablename,
                "name <> ''")
    """

    #: Allow blank names after all?
    __name_blank_allowed__: t.ClassVar[bool] = False
    #: How long are names and title allowed to be? `None` for unlimited length
    __name_length__: t.ClassVar[t.Optional[int]] = 250
    __title_length__: t.ClassVar[t.Optional[int]] = 250

    @declared_attr
    def name(cls) -> Mapped[str]:
        """Column for the URL name of this instance, non-unique."""
        if cls.__name_length__ is None:
            column_type = sa.Unicode()
        else:
            column_type = sa.Unicode(cls.__name_length__)
        if cls.__name_blank_allowed__:
            return sa.orm.mapped_column(column_type, nullable=False)
        return sa.orm.mapped_column(
            column_type, sa.CheckConstraint("name <> ''"), nullable=False
        )

    @declared_attr
    def title(cls) -> Mapped[str]:
        """Column for the title of this instance."""
        if cls.__title_length__ is None:
            column_type = sa.Unicode()
        else:
            column_type = sa.Unicode(cls.__title_length__)
        return sa.orm.mapped_column(column_type, nullable=False)

    @property
    def title_for_name(self) -> str:
        """
        Variant of :attr:`title` suitable for :meth:`make_name`.

        Returns :attr:`title` unmodified, but subclasses may override.
        """
        return self.title

    def __init__(self, *args, **kw) -> None:
        super().__init__(*args, **kw)
        if self.parent:
            self.make_id()
        if not self.name:
            self.make_name()

    def __repr__(self) -> str:
        return (
            f'<{self.__class__.__name__} {self.url_id_name} "{self.title}"'
            ' of {self.parent!r}>'
        )

    def __format__(self, format_spec: str) -> str:
        """Format using self.title."""
        if format_spec:
            # pylint: disable=not-callable
            return (self.title or '').__format__(format_spec)
        return self.title or ''

    @classmethod
    def get(cls, parent: t.Any, url_id: t.Union[int, str]) -> t.Optional[te.Self]:
        """Get an instance matching the parent and name."""
        return cls.query.filter_by(parent=parent, url_id=url_id).one_or_none()

    def make_name(self) -> None:
        """Autogenerate :attr:`name` from :attr:`title` (via :attr:`title_for_name`)."""
        if self.title:  # pylint: disable=using-constant-test
            self.name = make_name(
                self.title_for_name, maxlength=self.__name_length__ or 250
            )

    @hybrid_property
    def url_id_name(self) -> str:
        """Combine :attr:`url_id` and :attr:`name` in ``id-name`` syntax for URLs."""
        return f'{self.url_id}-{self.name}'

    @url_id_name.inplace.comparator
    @classmethod
    def _url_id_name_comparator(cls) -> SqlSplitIdComparator:
        """Return SQL comparator for id and name."""
        return SqlSplitIdComparator(cls.url_id, splitindex=0)

    url_name = url_id_name  # Legacy name

    @hybrid_property
    def url_name_uuid_b58(self) -> str:
        """
        Provide a URL stub in ``name-uuid`` syntax.

        Combines :attr:`name` with :attr:`UuidMixin.uuid_b58`. The subclass must use
        :class:`UuidMixin` to get this method.
        """
        return f'{self.name}-{self.uuid_b58}'  # type: ignore[attr-defined]

    @url_name_uuid_b58.inplace.comparator
    @classmethod
    def _url_name_uuid_b58_comparator(cls) -> SqlUuidB58Comparator:
        """Return SQL comparator for name and UUID in Base58 format."""
        return SqlUuidB58Comparator(
            cls.uuid, splitindex=-1  # type: ignore[attr-defined]
        )


@declarative_mixin
class CoordinatesMixin:
    """
    Mixin for models that store location coordinates.

    Adds :attr:`latitude` and :attr:`longitude` columns, and a :attr:`coordinates` tuple
    property.
    """

    latitude: Mapped[t.Optional[Decimal]] = sa.orm.mapped_column(
        sa.Numeric, nullable=True
    )
    longitude: Mapped[t.Optional[Decimal]] = sa.orm.mapped_column(
        sa.Numeric, nullable=True
    )

    @property
    def has_coordinates(self) -> bool:
        """Return `True` if both latitude and longitude are present."""
        return self.latitude is not None and self.longitude is not None

    @property
    def has_missing_coordinates(self) -> bool:
        """Return `True` if one or both of latitude and longitude are missing."""
        return self.latitude is None or self.longitude is None

    @property
    def coordinates(
        self,
    ) -> t.Tuple[t.Union[float, Decimal, None], t.Union[float, Decimal, None]]:
        """Tuple of (latitude, longitude)."""
        return self.latitude, self.longitude

    @coordinates.setter
    def coordinates(
        self,
        value: t.Tuple[t.Union[float, Decimal, None], t.Union[float, Decimal, None]],
    ) -> None:
        """Set coordinates."""
        self.latitude, self.longitude = value  # type: ignore[assignment]


# --- Auto-populate columns ------------------------------------------------------------


# Setup listeners for UUID-based subclasses
def _configure_id_listener(mapper: t.Any, class_: t.Type[IdMixin]) -> None:
    if hasattr(class_, '__uuid_primary_key__') and class_.__uuid_primary_key__:
        auto_init_default(mapper.column_attrs.id)


def _configure_uuid_listener(mapper: t.Any, class_: t.Type[UuidMixin]) -> None:
    if hasattr(class_, '__uuid_primary_key__') and class_.__uuid_primary_key__:
        return
    # Only configure this listener if the class doesn't use UUID primary keys,
    # as the `uuid` column will only be an alias for `id` in that case
    auto_init_default(mapper.column_attrs.uuid)


event.listen(IdMixin, 'mapper_configured', _configure_id_listener, propagate=True)
event.listen(UuidMixin, 'mapper_configured', _configure_uuid_listener, propagate=True)


# Populate name and url_id columns
def _make_name(_mapper: t.Any, _connection: t.Any, target: BaseNameMixin) -> None:
    if target.name is None:
        target.make_name()  # type: ignore[unreachable]


def _make_scoped_name(
    _mapper: t.Any, _connection: t.Any, target: BaseScopedNameMixin
) -> None:
    if target.name is None and target.parent is not None:  # type: ignore[unreachable]
        target.make_name()  # type: ignore[unreachable]


def _make_scoped_id(
    _mapper: t.Any, _connection: t.Any, target: BaseScopedIdMixin
) -> None:
    if target.url_id is None and target.parent is not None:  # type: ignore[unreachable]
        target.make_id()  # type: ignore[unreachable]


event.listen(BaseNameMixin, 'before_insert', _make_name, propagate=True)
event.listen(BaseIdNameMixin, 'before_insert', _make_name, propagate=True)
event.listen(BaseScopedIdMixin, 'before_insert', _make_scoped_id, propagate=True)
event.listen(BaseScopedNameMixin, 'before_insert', _make_scoped_name, propagate=True)
event.listen(BaseScopedIdNameMixin, 'before_insert', _make_scoped_id, propagate=True)
event.listen(BaseScopedIdNameMixin, 'before_insert', _make_name, propagate=True)
