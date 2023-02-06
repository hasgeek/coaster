"""
SQLAlchemy mixin classes
------------------------

Coaster provides a number of mixin classes for SQLAlchemy models. To use in
your Flask app::

    from flask import Flask
    from flask_sqlalchemy import SQLAlchemy
    from coaster.sqlalchemy import BaseMixin

    app = Flask(__name__)
    db = SQLAlchemy(app)

    class MyModel(BaseMixin, db.Model):
        __tablename__ = 'my_model'

Mixin classes must always appear *before* ``db.Model`` in your model's base classes.
"""

# pylint: disable=too-few-public-methods,no-self-argument

from __future__ import annotations

from collections import abc, namedtuple
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4
import typing as t

from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, declarative_mixin, declared_attr, synonym
from sqlalchemy.sql import func, select
from sqlalchemy_utils.types import UUIDType
import sqlalchemy as sa

from flask import Flask, current_app, url_for
from werkzeug.routing import BuildError

from ..auth import current_auth
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
    Query,
    SqlSplitIdComparator,
    SqlUuidB58Comparator,
    SqlUuidB64Comparator,
    SqlUuidHexComparator,
)
from .functions import auto_init_default, failsafe_add
from .immutable_annotation import immutable
from .registry import RegistryMixin
from .roles import RoleMixin, with_roles

__all__ = [
    'Mapped',
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


@declarative_mixin
class IdMixin:
    """
    Provides the :attr:`id` primary key column.

    Provides an auto-incrementing integer primary key by default. However, can be told
    to provide a UUID primary key by specifying a flag on the class::

        class MyModel(IdMixin, db.Model):
            __uuid_primary_key__ = True

    :class:`IdMixin` is a base class for :class:`BaseMixin`, the standard base class.
    """

    query: Query
    query_class = Query
    #: Use UUID primary key? If yes, UUIDs are automatically generated without
    #: the need to commit to the database
    __uuid_primary_key__ = False

    @declared_attr
    def id(cls) -> Mapped[int | UUID]:  # noqa: A003
        """Database identity for this model."""
        if cls.__uuid_primary_key__:
            return immutable(
                sa.Column(
                    UUIDType(binary=False),
                    default=uuid4,
                    primary_key=True,
                    nullable=False,
                )
            )
        return immutable(sa.Column(sa.Integer, primary_key=True, nullable=False))

    @declared_attr
    def url_id(cls) -> Mapped[int | UUID]:
        """URL-safe representation of the id value, using hex for a UUID id."""
        if cls.__uuid_primary_key__:

            def url_id_func(self):
                """URL-safe representation of the UUID id as a hex value."""
                return self.id.hex

            def url_id_is(cls):
                """Compare two hex UUID values."""
                return SqlUuidHexComparator(cls.id)

            url_id_func.__name__ = 'url_id'
            url_id_property = hybrid_property(url_id_func).comparator(
                url_id_is  # type: ignore[arg-type]
            )
            return url_id_property

        def url_id_func(self):  # type: ignore  # pylint: disable=function-redefined
            """URL-safe representation of the integer id as a string."""
            return str(self.id)

        def url_id_expression(cls):
            """Database column for id, for SQL expressions."""
            return cls.id

        url_id_func.__name__ = 'url_id'
        url_id_property = hybrid_property(url_id_func).expression(url_id_expression)
        return url_id_property

    def __repr__(self):
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

    @with_roles(read={'all'})
    @declared_attr
    def uuid(cls) -> Mapped[UUID]:
        """UUID column, or synonym to existing :attr:`id` column if that is a UUID."""
        if hasattr(cls, '__uuid_primary_key__') and cls.__uuid_primary_key__:
            return synonym('id')
        return immutable(
            sa.Column(
                UUIDType(binary=False),
                default=uuid4,
                unique=True,
                nullable=False,
            )
        )

    @hybrid_property
    def uuid_hex(self):
        """URL-friendly UUID representation as a hex string."""
        return self.uuid.hex

    @uuid_hex.comparator  # type: ignore[no-redef]
    def uuid_hex(cls):
        """Return SQL comparator for UUID in hex format."""
        # For some reason the test fails if we use `cls.uuid` here
        # but works fine in the `uuid_b64` and `uuid_b58` comparators below
        if hasattr(cls, '__uuid_primary_key__') and cls.__uuid_primary_key__:
            return SqlUuidHexComparator(cls.id)
        return SqlUuidHexComparator(cls.uuid)

    @hybrid_property
    def uuid_b64(self):
        """URL-friendly UUID representation, using URL-safe Base64 (BUID)."""
        return uuid_to_base64(self.uuid)

    @uuid_b64.setter  # type: ignore[no-redef]
    def uuid_b64(self, value):
        """Set UUID in Base64 format."""
        self.uuid = uuid_from_base64(value)

    @uuid_b64.comparator  # type: ignore[no-redef]
    def uuid_b64(cls):
        """Return SQL comparator for UUID in Base64 format."""
        return SqlUuidB64Comparator(cls.uuid)

    #: Retain `buid` as a public attribute for backward compatibility
    buid = uuid_b64

    #: Since `with_roles` annotates the attribute, both aliases (uuid_b64 and buid)
    #: will become public to the `all` role as a result of this annotation.
    with_roles(uuid_b64, read={'all'})

    @hybrid_property
    def uuid_b58(self):
        """URL-friendly UUID representation, using Base58 with the Bitcoin alphabet."""
        return uuid_to_base58(self.uuid)

    @uuid_b58.setter  # type: ignore[no-redef]
    def uuid_b58(self, value):
        self.uuid = uuid_from_base58(value)

    @uuid_b58.comparator  # type: ignore[no-redef]
    def uuid_b58(cls):
        """Return SQL comparator for UUID in Base58 format."""
        return SqlUuidB58Comparator(cls.uuid)

    with_roles(uuid_b58, read={'all'})


# Also see functions.make_timestamp_columns
@declarative_mixin
class TimestampMixin:
    """Provides the :attr:`created_at` and :attr:`updated_at` audit timestamps."""

    __with_timezone__ = False
    query: Query
    query_class = Query

    @immutable
    @declared_attr
    def created_at(cls) -> Mapped[datetime]:
        """Timestamp for when this instance was created, in UTC."""
        return sa.Column(
            sa.TIMESTAMP(timezone=cls.__with_timezone__),
            default=func.utcnow(),
            nullable=False,
        )

    @declared_attr
    def updated_at(cls) -> Mapped[datetime]:
        """Timestamp for when this instance was last updated (via the app), in UTC."""
        return sa.Column(
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
        self, actor, inherited: t.Optional[t.Set[str]] = None
    ) -> t.Set[str]:
        """Return permissions available to the given user on this object."""
        if inherited is not None:
            return set(inherited)
        return set()

    @property
    def current_permissions(self) -> InspectableSet[str]:
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


UrlEndpointData = namedtuple(
    'UrlEndpointData',
    ['endpoint', 'paramattrs', 'external', 'roles', 'requires_kwargs'],
)


class UrlDictStub:
    """
    Dictionary-based access to URLs for a model instance, used by :class:`UrlForMixin`.

    This class proxies to :meth:`UrlForMixin.url_for` for keyword-based lookup. Uses
    :attr:`UrlForMixin.url_for_endpoints` for enumeration, but with URLs limited to
    those available under current roles.
    """

    def __get__(self, obj, cls=None):
        if obj is None:
            return self  # pragma: no cover
        return UrlDict(obj)


class UrlDict(abc.Mapping):
    """Provides dictionary access to an object's URLs."""

    def __init__(self, obj):
        self.obj = obj

    def __getitem__(self, key):
        try:
            return self.obj.url_for(key, _external=True)
        except BuildError as exc:
            raise KeyError(key) from exc

    def __len__(self):
        return len(self.obj.url_for_endpoints[None]) + (
            len(self.obj.url_for_endpoints.get(current_app._get_current_object(), {}))
            if current_app
            else 0
        )

    def __iter__(self):
        # 1. Iterate through all actions available to the None app and to current_app
        # 2. If the action requires specific roles, confirm overlap with current_roles
        # 3. Confirm the action does not require additional parameters
        # 4. Yield whatever passes the tests
        current_roles = self.obj.roles_for(current_auth.actor)
        for app, app_actions in self.obj.url_for_endpoints.items():
            if app is None or (
                current_app and app is current_app._get_current_object()
            ):
                for action, epdata in app_actions.items():
                    if not epdata.requires_kwargs and (
                        epdata.roles is None or current_roles.has_any(epdata.roles)
                    ):
                        yield action


class UrlForMixin:
    """Provides a :meth:`url_for` method used by BaseMixin-derived classes."""

    #: Mapping of {app: {action: UrlEndpointData}}, where attr is a string or tuple of
    #: strings. The same action can point to different endpoints in different apps. The
    #: app may also be None as fallback. Each subclass will get its own dictionary.
    #: This particular dictionary is only used as an inherited fallback.
    url_for_endpoints: t.Dict[t.Optional[Flask], t.Dict[str, UrlEndpointData]] = {
        None: {}
    }
    #: Mapping of {app: {action: (classview, attr)}}
    view_for_endpoints: t.Dict[Flask, t.Dict[str, t.Tuple[t.Any, str]]] = {}

    #: Dictionary of URLs available on this object
    urls = UrlDictStub()

    def url_for(self, action='view', **kwargs) -> str:
        """Return public URL to this instance for a given action (default 'view')."""
        app = current_app._get_current_object() if current_app else None
        if app is not None and action in self.url_for_endpoints.get(app, {}):
            epdata = self.url_for_endpoints[app][action]
        else:
            try:
                epdata = self.url_for_endpoints[None][action]
            except KeyError as exc:
                raise BuildError(action, kwargs, 'GET') from exc
        params = {}
        for param, attr in list(epdata.paramattrs.items()):
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
                params[param] = attr(self)
            else:
                params[param] = getattr(self, attr)
        if epdata.external is not None:
            params['_external'] = epdata.external
        params.update(kwargs)  # Let kwargs override params

        # url_for from flask
        return url_for(epdata.endpoint, **params)

    @property
    def absolute_url(self) -> t.Optional[str]:
        """Absolute URL to this object."""
        try:
            return self.url_for(_external=True)
        except BuildError:
            return None

    @classmethod
    def is_url_for(
        cls, _action, _endpoint=None, _app=None, _external=None, **paramattrs
    ):
        """
        View decorator that registers the view as a :meth:`url_for` target.

        :param str _action: Action to register a URL under
        :param str _endpoint: View endpoint name to pass to Flask's ``url_for``
        :param _app: The app to register this action on (if your repo has multiple apps)
        :param _external: If `True`, URLs are assumed to be external-facing by default
        :param dict paramattrs: Mapping of URL parameter to attribute on the object
        """

        def decorator(f):
            cls.register_endpoint(
                action=_action,
                endpoint=_endpoint or f.__name__,
                app=_app,
                external=_external,
                paramattrs=paramattrs,
            )
            return f

        return decorator

    @classmethod
    def register_endpoint(
        cls, action, endpoint, app=None, external=None, roles=None, paramattrs=None
    ):
        """
        Register an endpoint to a :meth:`url_for` action.

        :param view_func: View handler to be registered
        :param str action: Action to register a URL under
        :param str endpoint: View endpoint name to pass to Flask's ``url_for``
        :param app: Flask app (default: `None`)
        :param external: If `True`, URLs are assumed to be external-facing by default
        :param roles: Roles to which this URL is available, required by :class:`UrlDict`
        :param dict paramattrs: Mapping of URL parameter to attribute on the object
        """
        if 'url_for_endpoints' not in cls.__dict__:
            cls.url_for_endpoints = {
                None: {}
            }  # Stick it into the class with the first endpoint
        cls.url_for_endpoints.setdefault(app, {})

        for keyword in paramattrs:
            if isinstance(paramattrs[keyword], str) and '.' in paramattrs[keyword]:
                paramattrs[keyword] = tuple(paramattrs[keyword].split('.'))
        requires_kwargs = False
        for attrs in paramattrs.values():
            if isinstance(attrs, tuple) and attrs[0].startswith('**'):
                requires_kwargs = True
                break
        cls.url_for_endpoints[app][action] = UrlEndpointData(
            endpoint=endpoint,
            paramattrs=paramattrs if paramattrs is not None else {},
            external=external,
            roles=roles,
            requires_kwargs=requires_kwargs,
        )

    @classmethod
    def register_view_for(cls, app, action, classview, attr):
        """Register a classview and viewhandler for a given app and action."""
        if 'view_for_endpoints' not in cls.__dict__:
            cls.view_for_endpoints = {}
        cls.view_for_endpoints.setdefault(app, {})[action] = (classview, attr)

    def view_for(self, action='view'):
        """Return the classview viewhandler that handles the specified action."""
        app = current_app._get_current_object()
        view, attr = self.view_for_endpoints[app][action]
        return getattr(view(self), attr)

    def classview_for(self, action='view'):
        """Return the classview containing the viewhandler for the specified action."""
        app = current_app._get_current_object()
        return self.view_for_endpoints[app][action][0](self)


@declarative_mixin
class NoIdMixin(TimestampMixin, PermissionMixin, RoleMixin, RegistryMixin, UrlForMixin):
    """
    Mixin that combines all mixin classes except :class:`IdMixin`.

    For use anywhere the timestamp columns and helper methods are required, but an id
    column is not.
    """

    def _set_fields(self, fields):
        """Set field values."""
        for f in fields:
            if hasattr(self, f):
                setattr(self, f, fields[f])
            else:
                raise TypeError(
                    f"'{f}' is an invalid argument for {self.__class__.__name__}"
                )


@declarative_mixin
class BaseMixin(IdMixin, NoIdMixin):
    """Base mixin class for all tables that have an id column."""


@declarative_mixin
class BaseNameMixin(BaseMixin):
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
    reserved_names: t.Collection[str] = []
    #: Allow blank names after all?
    __name_blank_allowed__ = False
    #: How long are names and title allowed to be? `None` for unlimited length
    __name_length__: t.Optional[int] = 250
    __title_length__: t.Optional[int] = 250

    @declared_attr
    def name(cls) -> Mapped[str]:
        """Column for URL name of this object, unique across all instances."""
        if cls.__name_length__ is None:
            column_type = sa.Unicode()
        else:
            column_type = sa.Unicode(cls.__name_length__)
        if cls.__name_blank_allowed__:
            return sa.Column(column_type, nullable=False, unique=True)
        return sa.Column(
            column_type, sa.CheckConstraint("name <> ''"), nullable=False, unique=True
        )

    @declared_attr
    def title(cls) -> Mapped[str]:
        """Column for title of this object."""
        if cls.__title_length__ is None:
            column_type = sa.Unicode()
        else:
            column_type = sa.Unicode(cls.__title_length__)
        return sa.Column(column_type, nullable=False)

    @property
    def title_for_name(self):
        """
        Variant of :attr:`title` suitable for :meth:`make_name`.

        Returns :attr:`title` unmodified, but subclasses may override.
        """
        return self.title

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        if not self.name:
            self.make_name()

    def __repr__(self):
        return f'<{self.__class__.__name__} {self.name} "{self.title}">'

    @classmethod
    def get(cls, name):
        """Get an instance matching the name."""
        return cls.query.filter_by(name=name).one_or_none()

    @classmethod
    def upsert(cls, name, **fields):
        """Insert or update an instance."""
        instance = cls.get(name)
        if instance:
            instance._set_fields(fields)
        else:
            instance = cls(name=name, **fields)
            instance = failsafe_add(cls.query.session, instance, name=name)
        return instance

    def make_name(self, reserved: t.Collection[str] = ()):
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

                def checkused(c):
                    return bool(
                        c in reserved
                        or c in self.reserved_names
                        or self.__class__.query.filter(  # pylint: disable=W0143
                            self.__class__.id != self.id
                        )
                        .filter_by(name=c)
                        .notempty()
                    )

            else:

                def checkused(c):
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
class BaseScopedNameMixin(BaseMixin):
    """
    Base mixin class for named objects within containers.

    When using this class, you must provide an model-level attribute "parent" that is a
    synonym for the parent object. You must also create a unique constraint on 'name'
    in combination with the parent foreign key. Sample use case in Flask::

        class Event(BaseScopedNameMixin, db.Model):
            __tablename__ = 'event'
            organizer_id = db.Column(None, db.ForeignKey('organizer.id'))
            organizer = db.relationship(Organizer)
            parent = db.synonym('organizer')
            __table_args__ = (db.UniqueConstraint('organizer_id', 'name'),)

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
    reserved_names: t.Collection[str] = []
    #: Allow blank names after all?
    __name_blank_allowed__ = False
    #: How long are names and title allowed to be? `None` for unlimited length
    __name_length__: t.Optional[int] = 250
    __title_length__: t.Optional[int] = 250

    @declared_attr
    def name(cls) -> Mapped[str]:
        """Column for URL name of this object, unique within a parent container."""
        if cls.__name_length__ is None:
            column_type = sa.Unicode()
        else:
            column_type = sa.Unicode(cls.__name_length__)
        if cls.__name_blank_allowed__:
            return sa.Column(column_type, nullable=False)
        return sa.Column(column_type, sa.CheckConstraint("name <> ''"), nullable=False)

    @declared_attr
    def title(cls) -> Mapped[str]:
        """Column for title of this object."""
        if cls.__title_length__ is None:
            column_type = sa.Unicode()
        else:
            column_type = sa.Unicode(cls.__title_length__)
        return sa.Column(column_type, nullable=False)

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        if self.parent and not self.name:
            self.make_name()

    def __repr__(self):
        return (
            f'<{self.__class__.__name__} {self.name} "{self.title}" of {self.parent!r}>'
        )

    @classmethod
    def get(cls, parent, name):
        """Get an instance matching the parent and name."""
        return cls.query.filter_by(parent=parent, name=name).one_or_none()

    @classmethod
    def upsert(cls, parent, name, **fields):
        """Insert or update an instance."""
        instance = cls.get(parent, name)
        if instance:
            instance._set_fields(fields)
        else:
            instance = cls(parent=parent, name=name, **fields)
            instance = failsafe_add(
                cls.query.session, instance, parent=parent, name=name
            )
        return instance

    def make_name(self, reserved: t.Collection[str] = ()):
        """
        Autogenerate :attr:`name` from the :attr:`title` (via :attr:`title_for_name`).

        If the auto-generated name is already in use in this model, :meth:`make_name`
        tries again by suffixing numbers starting with 2 until an available name is
        found.
        """
        if self.title:  # pylint: disable=using-constant-test
            if sa.inspect(self).has_identity:  # type: ignore[union-attr]

                def checkused(c):
                    return bool(
                        c in reserved
                        or c in self.reserved_names
                        or self.__class__.query.filter(
                            self.__class__.id != self.id  # pylint: disable=W0143
                        )
                        .filter_by(name=c, parent=self.parent)
                        .first()
                    )

            else:

                def checkused(c):
                    return bool(
                        c in reserved
                        or c in self.reserved_names
                        or self.__class__.query.filter_by(
                            name=c, parent=self.parent
                        ).first()
                    )

            with self.__class__.query.session.no_autoflush:
                self.name = make_name(
                    self.title_for_name,
                    maxlength=self.__name_length__ or 250,
                    checkused=checkused,
                )

    @property
    def short_title(self):
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
    def title_for_name(self):
        """
        Variant of :attr:`title` suitable for :meth:`make_name`.

        Returns :attr:`short_title`, but subclasses may override.
        """
        return self.short_title

    def permissions(self, actor, inherited=None):
        """Permissions for this model, plus permissions inherited from the parent."""
        if inherited is not None:
            return inherited | super().permissions(actor)
        elif self.parent is not None and isinstance(self.parent, PermissionMixin):
            return self.parent.permissions(actor) | super().permissions(actor)
        return super().permissions(actor)


@declarative_mixin
class BaseIdNameMixin(BaseMixin):
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
    __name_blank_allowed__ = False
    #: How long are names and title allowed to be? `None` for unlimited length
    __name_length__: t.Optional[int] = 250
    __title_length__: t.Optional[int] = 250

    @declared_attr
    def name(cls) -> Mapped[str]:
        """Column for the URL name of this object, non-unique."""
        if cls.__name_length__ is None:
            column_type = sa.Unicode()
        else:
            column_type = sa.Unicode(cls.__name_length__)
        if cls.__name_blank_allowed__:
            return sa.Column(column_type, nullable=False)
        return sa.Column(column_type, sa.CheckConstraint("name <> ''"), nullable=False)

    @declared_attr
    def title(cls) -> Mapped[str]:
        """Column for the title of this object."""
        if cls.__title_length__ is None:
            column_type = sa.Unicode()
        else:
            column_type = sa.Unicode(cls.__title_length__)
        return sa.Column(column_type, nullable=False)

    @property
    def title_for_name(self):
        """
        Variant of :attr:`title` suitable for :meth:`make_name`.

        Returns :attr:`title` unmodified, but subclasses may override.
        """
        return self.title

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        if not self.name:
            self.make_name()

    def __repr__(self):
        return f'<{self.__class__.__name__} {self.url_id_name} "{self.title}">'

    def make_name(self):
        """Autogenerate a :attr:`name` from :attr:`title_for_name`."""
        if self.title:  # pylint: disable=using-constant-test
            self.name = make_name(
                self.title_for_name, maxlength=self.__name_length__ or 250
            )

    @hybrid_property
    def url_id_name(self):
        """Id and name in ``id-name`` format for use in URLs."""
        return f'{self.url_id}-{self.name}'

    @url_id_name.comparator  # type: ignore[no-redef]
    def url_id_name(cls):
        """Return SQL comparator for id and name."""
        if cls.__uuid_primary_key__:
            return SqlUuidHexComparator(cls.id, splitindex=0)
        return SqlSplitIdComparator(cls.id, splitindex=0)

    url_name = url_id_name  # Legacy name

    @hybrid_property
    def url_name_uuid_b58(self):
        """
        Name and UUID in Base58 rendering, in ``name-uuid`` format, for use in URLs.

        To use this, the class must derive from :class:`UuidMixin` as that provides
        the ``uuid_b58`` property.
        """
        return f'{self.name}-{self.uuid_b58}'

    @url_name_uuid_b58.comparator  # type: ignore[no-redef]
    def url_name_uuid_b58(cls):
        """Return SQL comparator for name and UUID in Base58 format."""
        return SqlUuidB58Comparator(cls.uuid, splitindex=-1)


@declarative_mixin
class BaseScopedIdMixin(BaseMixin):
    """
    Base mixin class for objects with an id that is unique within a parent.

    Implementations must provide a 'parent' attribute that is either a relationship
    or a synonym to a relationship referring to the parent object, and must
    declare a unique constraint between url_id and the parent. Sample use case in
    Flask::

        class Issue(BaseScopedIdMixin, db.Model):
            __tablename__ = 'issue'
            event_id = db.Column(None, db.ForeignKey('event.id'))
            event = db.relationship(Event)
            parent = db.synonym('event')
            __table_args__ = (db.UniqueConstraint('event_id', 'url_id'),)
    """

    # FIXME: Rename this to `scoped_id` and provide a migration guide.
    @with_roles(read={'all'})
    @declared_attr
    def url_id(cls) -> Mapped[int]:
        """Column for an id number that is unique within the parent container."""
        return sa.Column(sa.Integer, nullable=False)

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        if self.parent:
            self.make_id()

    def __repr__(self):
        return f'<{self.__class__.__name__} {self.url_id} of {self.parent!r}>'

    @classmethod
    def get(cls, parent, url_id):
        """Get an instance matching the parent and url_id."""
        return cls.query.filter_by(parent=parent, url_id=url_id).one_or_none()

    def make_id(self):
        """Create a new URL id that is unique to the parent container."""
        if self.url_id is None:  # Set id only if empty
            self.url_id = (
                select(func.coalesce(func.max(self.__class__.url_id + 1), 1))
                .where(
                    self.__class__.parent == self.parent,
                )
                .as_scalar()
            )

    def permissions(self, actor, inherited=None):
        """Permissions for this model, plus permissions inherited from the parent."""
        if inherited is not None:
            return inherited | super().permissions(actor)
        if self.parent is not None and isinstance(self.parent, PermissionMixin):
            return self.parent.permissions(actor) | super().permissions(actor)
        return super().permissions(actor)


@declarative_mixin
class BaseScopedIdNameMixin(BaseScopedIdMixin):
    """
    Base mixin class for named objects with an id tag that is unique within a parent.

    Implementations must provide a 'parent' attribute that is a synonym to the parent
    relationship, and must declare a unique constraint between url_id and the parent.
    Sample use case in Flask::

        class Event(BaseScopedIdNameMixin, db.Model):
            __tablename__ = 'event'
            organizer_id = db.Column(None, db.ForeignKey('organizer.id'))
            organizer = db.relationship(Organizer)
            parent = db.synonym('organizer')
            __table_args__ = (db.UniqueConstraint('organizer_id', 'url_id'),)

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
    __name_blank_allowed__ = False
    #: How long are names and title allowed to be? `None` for unlimited length
    __name_length__: t.Optional[int] = 250
    __title_length__: t.Optional[int] = 250

    @declared_attr
    def name(cls) -> Mapped[str]:
        """Column for the URL name of this instance, non-unique."""
        if cls.__name_length__ is None:
            column_type = sa.Unicode()
        else:
            column_type = sa.Unicode(cls.__name_length__)
        if cls.__name_blank_allowed__:
            return sa.Column(column_type, nullable=False)
        return sa.Column(column_type, sa.CheckConstraint("name <> ''"), nullable=False)

    @declared_attr
    def title(cls) -> Mapped[str]:
        """Column for the title of this instance."""
        if cls.__title_length__ is None:
            column_type = sa.Unicode()
        else:
            column_type = sa.Unicode(cls.__title_length__)
        return sa.Column(column_type, nullable=False)

    @property
    def title_for_name(self):
        """
        Variant of :attr:`title` suitable for :meth:`make_name`.

        Returns :attr:`title` unmodified, but subclasses may override.
        """
        return self.title

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        if self.parent:
            self.make_id()
        if not self.name:
            self.make_name()

    def __repr__(self):
        return (
            f'<{self.__class__.__name__} {self.url_id_name} "{self.title}"'
            ' of {self.parent!r}>'
        )

    @classmethod
    def get(cls, parent, url_id):
        """Get an instance matching the parent and name."""
        return cls.query.filter_by(parent=parent, url_id=url_id).one_or_none()

    def make_name(self):
        """Autogenerate :attr:`name` from :attr:`title` (via :attr:`title_for_name)."""
        if self.title:
            self.name = make_name(
                self.title_for_name, maxlength=self.__name_length__ or 250
            )

    @hybrid_property
    def url_id_name(self):
        """Combine :attr:`url_id` and :attr:`name` in ``id-name`` syntax for URLs."""
        return f'{self.url_id}-{self.name}'

    @url_id_name.comparator  # type: ignore[no-redef]
    def url_id_name(cls):
        """Return SQL comparator for id and name."""
        return SqlSplitIdComparator(cls.url_id, splitindex=0)

    url_name = url_id_name  # Legacy name

    @hybrid_property
    def url_name_uuid_b58(self):
        """
        Provide a URL stub in ``name-uuid`` syntax.

        Combines :attr:`name` with :attr:`UuidMixin.uuid_b58`. The subclass must use
        :class:`UuidMixin` to get this method.
        """
        return f'{self.name}-{self.uuid_b58}'

    @url_name_uuid_b58.comparator  # type: ignore[no-redef]
    def url_name_uuid_b58(cls):
        """Return SQL comparator for name and UUID in Base58 format."""
        return SqlUuidB58Comparator(cls.uuid, splitindex=-1)


@declarative_mixin
class CoordinatesMixin:
    """
    Mixin for models that store location coordinates.

    Adds :attr:`latitude` and :attr:`longitude` columns, and a :attr:`coordinates` tuple
    property.
    """

    latitude = sa.Column(sa.Numeric)
    longitude = sa.Column(sa.Numeric)

    @property
    def has_coordinates(self):
        """Return `True` if both latitude and longitude are present."""
        return self.latitude is not None and self.longitude is not None

    @property
    def has_missing_coordinates(self):
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
    ):
        """Set coordinates."""
        self.latitude, self.longitude = value  # type: ignore[assignment]


# --- Auto-populate columns ------------------------------------------------------------


# Setup listeners for UUID-based subclasses
def _configure_id_listener(mapper, class_):
    if hasattr(class_, '__uuid_primary_key__') and class_.__uuid_primary_key__:
        auto_init_default(mapper.column_attrs.id)


def _configure_uuid_listener(mapper, class_):
    if hasattr(class_, '__uuid_primary_key__') and class_.__uuid_primary_key__:
        return
    # Only configure this listener if the class doesn't use UUID primary keys,
    # as the `uuid` column will only be an alias for `id` in that case
    auto_init_default(mapper.column_attrs.uuid)


sa.event.listen(IdMixin, 'mapper_configured', _configure_id_listener, propagate=True)
sa.event.listen(
    UuidMixin, 'mapper_configured', _configure_uuid_listener, propagate=True
)


# Populate name and url_id columns
def _make_name(mapper, connection, target):
    if target.name is None:
        target.make_name()


def _make_scoped_name(mapper, connection, target):
    if target.name is None and target.parent is not None:
        target.make_name()


def _make_scoped_id(mapper, connection, target):
    if target.url_id is None and target.parent is not None:
        target.make_id()


sa.event.listen(BaseNameMixin, 'before_insert', _make_name, propagate=True)
sa.event.listen(BaseIdNameMixin, 'before_insert', _make_name, propagate=True)
sa.event.listen(BaseScopedIdMixin, 'before_insert', _make_scoped_id, propagate=True)
sa.event.listen(BaseScopedNameMixin, 'before_insert', _make_scoped_name, propagate=True)
sa.event.listen(BaseScopedIdNameMixin, 'before_insert', _make_scoped_id, propagate=True)
sa.event.listen(BaseScopedIdNameMixin, 'before_insert', _make_name, propagate=True)
