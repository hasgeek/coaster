# -*- coding: utf-8 -*-

"""
SQLAlchemy patterns
===================

Coaster provides a number of mixin classes for SQLAlchemy models. To use in
your Flask app::

    from flask import Flask
    from flask_sqlalchemy import SQLAlchemy
    from coaster.sqlalchemy import BaseMixin

    app = Flask(__name__)
    db = SQLAlchemy(app)

    class MyModel(BaseMixin, db.Model):
        __tablename__ = 'my_model'

Mixin classes must always appear _before_ ``db.Model`` in your model's base classes.
"""

from __future__ import absolute_import
import uuid as uuid_
import simplejson
from sqlalchemy import Table, Column, ForeignKey, Integer, DateTime, Unicode, UnicodeText, CheckConstraint, Numeric
from sqlalchemy import event, inspect, DDL
from sqlalchemy.sql import select, func, functions
from sqlalchemy.types import UserDefinedType, TypeDecorator, TEXT
from sqlalchemy.orm import composite, synonym, relationship
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.ext.mutable import Mutable, MutableComposite
from sqlalchemy.ext.hybrid import Comparator, hybrid_property
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.ext.compiler import compiles
from sqlalchemy_utils.types import UUIDType
from flask import Markup, url_for
from flask_sqlalchemy import BaseQuery
from .utils import make_name, uuid2buid, uuid2suuid, buid2uuid, suuid2uuid
from .roles import RoleMixin, set_roles, declared_attr_roles  # NOQA
from .gfm import markdown
import six


# --- SQL Functions -----------------------------------------------------------

# Provide sqlalchemy.func.utcnow()
# Adapted from http://docs.sqlalchemy.org/en/rel_1_0/core/compiler.html#utc-timestamp-function
class utcnow(functions.GenericFunction):
    type = DateTime()


@compiles(utcnow)
def __utcnow_default(element, compiler, **kw):
    return 'CURRENT_TIMESTAMP'


@compiles(utcnow, 'mysql')
def __utcnow_mysql(element, compiler, **kw):  # pragma: no-cover
    return 'UTC_TIMESTAMP()'


@compiles(utcnow, 'postgresql')
def __utcnow_postgresql(element, compiler, **kw):
    return 'TIMEZONE(\'utc\', CURRENT_TIMESTAMP)'


@compiles(utcnow, 'mssql')
def __utcnow_mssql(element, compiler, **kw):  # pragma: no-cover
    return 'SYSUTCDATETIME()'


# --- Queries and comparators -------------------------------------------------

class Query(BaseQuery):
    """
    Extends flask_sqlalchemy.BaseQuery to add additional helper methods.
    """

    def notempty(self):
        """
        Returns the equivalent of ``bool(query.count())`` but using an efficient
        SQL EXISTS function, so the database stops counting after the first result
        is found.
        """
        return self.session.query(self.exists()).scalar()

    def isempty(self):
        """
        Returns the equivalent of ``not bool(query.count())`` but using an efficient
        SQL EXISTS function, so the database stops counting after the first result
        is found.
        """
        return not self.session.query(self.exists()).scalar()


class SplitIndexComparator(Comparator):
    """
    Base class for comparators that support splitting a string and
    comparing with one of the split values.
    """

    def __init__(self, expression, splitindex=None):
        super(SplitIndexComparator, self).__init__(expression)
        self.splitindex = splitindex

    def _decode(self, other):
        raise NotImplementedError

    def __eq__(self, other):
        try:
            other = self._decode(other)
        except (ValueError, TypeError):
            return False
        return self.__clause_element__() == other

    def __ne__(self, other):
        try:
            other = self._decode(other)
        except (ValueError, TypeError):
            return True
        return self.__clause_element__() != other

    def in_(self, other):
        _marker = []

        def errordecode(val):
            try:
                return self._decode(val)
            except (ValueError, TypeError):
                return _marker

        otherlist = (v for v in (errordecode(val) for val in other) if v is not _marker)
        return self.__clause_element__().in_(otherlist)


class SqlSplitIdComparator(SplitIndexComparator):
    """
    Allows comparing an id value with a column, useful mostly because of
    the splitindex feature, which splits an incoming string along the ``-``
    character and picks one of the splits for comparison.
    """
    def _decode(self, other):
        if other is None:
            return
        if self.splitindex is not None and isinstance(other, six.string_types):
            other = int(other.split('-')[self.splitindex])
        return other


class SqlHexUuidComparator(SplitIndexComparator):
    """
    Allows comparing UUID fields with hex representations of the UUID
    """
    def _decode(self, other):
        if other is None:
            return
        if not isinstance(other, uuid_.UUID):
            if self.splitindex is not None:
                other = other.split('-')[self.splitindex]
            other = uuid_.UUID(other)
        return other


class SqlBuidComparator(SplitIndexComparator):
    """
    Allows comparing UUID fields with URL-safe Base64 (BUID) representations
    of the UUID
    """
    def _decode(self, other):
        if other is None:
            return
        if not isinstance(other, uuid_.UUID):
            if self.splitindex is not None:
                other = other.split('-')[self.splitindex]
            other = buid2uuid(other)
        return other


class SqlSuuidComparator(SplitIndexComparator):
    """
    Allows comparing UUID fields with ShortUUID representations of the UUID
    """
    def _decode(self, other):
        if other is None:
            return
        if not isinstance(other, uuid_.UUID):
            if self.splitindex is not None:
                other = other.split('-')[self.splitindex]
            other = suuid2uuid(other)
        return other


# --- Mixins ------------------------------------------------------------------

__all_mixins = ['IdMixin', 'TimestampMixin', 'PermissionMixin', 'UrlForMixin',
    'BaseMixin', 'BaseNameMixin', 'BaseScopedNameMixin', 'BaseIdNameMixin',
    'BaseScopedIdMixin', 'BaseScopedIdNameMixin', 'CoordinatesMixin',
    'UuidMixin', 'RoleMixin']


class IdMixin(object):
    """
    Provides the :attr:`id` primary key column
    """
    query_class = Query
    #: Use UUID primary key? If yes, UUIDs are automatically generated without
    #: the need to commit to the database
    __uuid_primary_key__ = False

    @declared_attr
    def id(cls):
        """
        Database identity for this model, used for foreign key references from other models
        """
        if cls.__uuid_primary_key__:
            return Column(UUIDType(binary=False), default=uuid_.uuid4, primary_key=True, nullable=False)
        else:
            return Column(Integer, primary_key=True, nullable=False)

    @declared_attr
    def url_id(cls):
        """The URL id"""
        if cls.__uuid_primary_key__:
            def url_id_func(self):
                """The URL id, UUID primary key rendered as a hex string"""
                return self.id.hex
            url_id_property = hybrid_property(url_id_func)

            @url_id_property.comparator
            def url_id_is(cls):
                return SqlHexUuidComparator(cls.id)

            return url_id_property
        else:
            def url_id_func(self):
                """The URL id, integer primary key rendered as a string"""
                return six.text_type(self.id)
            url_id_property = hybrid_property(url_id_func)

            @url_id_property.expression
            def url_id_expression(cls):
                """The URL id, integer primary key"""
                return cls.id

            return url_id_property

    def __repr__(self):
        return '<%s %s>' % (self.__class__.__name__, self.id)


class UuidMixin(object):
    """
    Provides a ``uuid`` attribute that is either a SQL UUID column or an alias
    to the existing ``id`` column if the class uses UUID primary keys. Also
    provides hybrid properties ``url_id``, ``buid`` and ``suuid`` that provide
    hex, BUID and ShortUUID representations of the ``uuid`` column.

    :class:`UuidMixin` must appear before other classes in the base class order::

        class MyDocument(UuidMixin, BaseMixin, db.Model):
            pass

    Compatibility table:

    +-----------------------+-------------+-----------------------------------------+
    | Base class            | Compatible? | Notes                                   |
    +=======================+=============+=========================================+
    | BaseMixin             | Yes         |                                         |
    +-----------------------+-------------+-----------------------------------------+
    | BaseIdNameMixin       | Yes         |                                         |
    +-----------------------+-------------+-----------------------------------------+
    | BaseNameMixin         | N/A         | ``name`` is secondary key, not ``uuid`` |
    +-----------------------+-------------+-----------------------------------------+
    | BaseScopedNameMixin   | N/A         | ``name`` is secondary key, not ``uuid`` |
    +-----------------------+-------------+-----------------------------------------+
    | BaseScopedIdMixin     | No          | Conflicting :attr:`url_id` attribute    |
    +-----------------------+-------------+-----------------------------------------+
    | BaseScopedIdNameMixin | No          | Conflicting :attr:`url_id` attribute    |
    +-----------------------+-------------+-----------------------------------------+
    """
    @declared_attr
    @declared_attr_roles(read={'all'})
    def uuid(cls):
        """UUID column, or synonym to existing :attr:`id` column if that is a UUID"""
        if hasattr(cls, '__uuid_primary_key__') and cls.__uuid_primary_key__:
            return synonym('id')
        else:
            return Column(UUIDType(binary=False), default=uuid_.uuid4, unique=True, nullable=False)

    @set_roles(read={'all'})
    @hybrid_property
    def url_id(self):
        """URL-friendly UUID representation as a hex string"""
        return self.uuid.hex

    @url_id.comparator
    def url_id(cls):
        # For some reason the test fails if we use `cls.uuid` here
        # but works fine in the `buid` and `suuid` comparators below
        if hasattr(cls, '__uuid_primary_key__') and cls.__uuid_primary_key__:
            return SqlHexUuidComparator(cls.id)
        else:
            return SqlHexUuidComparator(cls.uuid)

    @set_roles(read={'all'})
    @hybrid_property
    def buid(self):
        """URL-friendly UUID representation, using URL-safe Base64 (BUID)"""
        return uuid2buid(self.uuid)

    @buid.setter
    def buid(self, value):
        self.uuid = buid2uuid(value)

    @buid.comparator
    def buid(cls):
        return SqlBuidComparator(cls.uuid)

    @set_roles(read={'all'})
    @hybrid_property
    def suuid(self):
        """URL-friendly UUID representation, using ShortUUID"""
        return uuid2suuid(self.uuid)

    @suuid.setter
    def suuid(self, value):
        self.uuid = suuid2uuid(value)

    @suuid.comparator
    def suuid(cls):
        return SqlSuuidComparator(cls.uuid)


# Supply a default value for UUID-based id columns
def __uuid_default_listener(uuidcolumn):
    @event.listens_for(uuidcolumn, 'init_scalar', retval=True, propagate=True)
    def init_scalar(target, value, dict_):
        # A subclass may override the column and not provide a default. Watch out for that.
        default = uuidcolumn.columns[0].default
        if default:
            value = uuidcolumn.columns[0].default.arg(None)
            dict_[uuidcolumn.key] = value
            return value


# Setup listeners for UUID-based subclasses
def __configure_id_listener(mapper, class_):
    if hasattr(class_, '__uuid_primary_key__') and class_.__uuid_primary_key__:
        __uuid_default_listener(mapper.attrs.id)


def __configure_uuid_listener(mapper, class_):
    if hasattr(class_, '__uuid_primary_key__') and class_.__uuid_primary_key__:
        return
    # Only configure this listener if the class doesn't use UUID primary keys,
    # as the `uuid` column will only be an alias for `id` in that case
    __uuid_default_listener(mapper.attrs.uuid)


event.listen(IdMixin, 'mapper_configured', __configure_id_listener, propagate=True)
event.listen(UuidMixin, 'mapper_configured', __configure_uuid_listener, propagate=True)


def make_timestamp_columns():
    """Return two columns, created_at and updated_at, with appropriate defaults"""
    return (
        Column('created_at', DateTime, default=func.utcnow(), nullable=False),
        Column('updated_at', DateTime, default=func.utcnow(), onupdate=func.utcnow(), nullable=False),
        )


class TimestampMixin(object):
    """
    Provides the :attr:`created_at` and :attr:`updated_at` audit timestamps
    """
    query_class = Query
    #: Timestamp for when this instance was created, in UTC
    created_at = Column(DateTime, default=func.utcnow(), nullable=False)
    #: Timestamp for when this instance was last updated (via the app), in UTC
    updated_at = Column(DateTime, default=func.utcnow(), onupdate=func.utcnow(), nullable=False)


class PermissionMixin(object):
    """
    Provides the :meth:`permissions` method used by BaseMixin and derived classes
    """
    def permissions(self, user, inherited=None):
        """
        Return permissions available to the given user on this object
        """
        if inherited is not None:
            return set(inherited)
        else:
            return set()


class UrlForMixin(object):
    """
    Provides a :meth:`url_for` method used by BaseMixin-derived classes
    """
    #: Mapping of {action: (endpoint, {param: attr})}, where attr is a string or tuple of strings.
    #: This particular dictionary is only used as a fallback. Each subclass will get its own dictionary.
    url_for_endpoints = {}

    def url_for(self, action='view', **kwargs):
        """
        Return public URL to this instance for a given action (default 'view')
        """
        if action not in self.url_for_endpoints:
            # FIXME: Legacy behaviour, fails silently, but shouldn't. url_for itself raises a BuildError
            return
        endpoint, paramattrs, _external = self.url_for_endpoints[action]
        params = {}
        for param, attr in list(paramattrs.items()):
            if isinstance(attr, tuple):
                item = self
                for subattr in attr:
                    item = getattr(item, subattr)
                params[param] = item
            elif callable(attr):
                params[param] = attr(self)
            else:
                params[param] = getattr(self, attr)
        if _external is not None:
            params['_external'] = _external
        params.update(kwargs)  # Let kwargs override params

        # url_for from flask
        return url_for(endpoint, **params)

    @classmethod
    def is_url_for(cls, _action, _endpoint=None, _external=None, **paramattrs):
        def decorator(f):
            if 'url_for_endpoints' not in cls.__dict__:
                cls.url_for_endpoints = {}  # Stick it into the class with the first endpoint

            for keyword in paramattrs:
                if isinstance(paramattrs[keyword], six.string_types) and '.' in paramattrs[keyword]:
                    paramattrs[keyword] = tuple(paramattrs[keyword].split('.'))
            cls.url_for_endpoints[_action] = _endpoint or f.__name__, paramattrs, _external
            return f
        return decorator


class BaseMixin(IdMixin, TimestampMixin, PermissionMixin, RoleMixin, UrlForMixin):
    """
    Base mixin class for all tables that adds id and timestamp columns and includes
    stub :meth:`permissions` and :meth:`url_for` methods
    """
    def _set_fields(self, fields):
        """Helper method for :meth:`upsert` in the various subclasses"""
        for f in fields:
            if hasattr(self, f):
                setattr(self, f, fields[f])
            else:
                raise TypeError("'{arg}' is an invalid argument for {instance_type}".format(arg=f, instance_type=self.__class__.__name__))


class BaseNameMixin(BaseMixin):
    """
    Base mixin class for named objects

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
            op.create_check_constraint(tablename + '_name_check', tablename, "name <> ''")
    """
    #: Prevent use of these reserved names
    reserved_names = []
    #: Allow blank names after all?
    __name_blank_allowed__ = False
    #: How long should names and titles be?
    __name_length__ = __title_length__ = 250

    @declared_attr
    def name(cls):
        """The URL name of this object, unique across all instances of this model"""
        if cls.__name_blank_allowed__:
            return Column(Unicode(cls.__name_length__), nullable=False, unique=True)
        else:
            return Column(Unicode(cls.__name_length__), CheckConstraint("name <> ''"), nullable=False, unique=True)

    @declared_attr
    def title(cls):
        """The title of this object"""
        return Column(Unicode(cls.__title_length__), nullable=False)

    def __init__(self, *args, **kw):
        super(BaseNameMixin, self).__init__(*args, **kw)
        if not self.name:
            self.make_name()

    def __repr__(self):
        return '<%s %s "%s">' % (self.__class__.__name__, self.name, self.title)

    @classmethod
    def get(cls, name):
        """Get an instance matching the name"""
        return cls.query.filter_by(name=name).one_or_none()

    @classmethod
    def upsert(cls, name, **fields):
        """Insert or update an instance"""
        instance = cls.get(name)
        if instance:
            instance._set_fields(fields)
        else:
            instance = cls(name=name, **fields)
            instance = failsafe_add(cls.query.session, instance, name=name)
        return instance

    def make_name(self, reserved=[]):
        """
        Autogenerates a :attr:`name` from the :attr:`title`. If the auto-generated name is already
        in use in this model, :meth:`make_name` tries again by suffixing numbers starting with 2
        until an available name is found.

        :param reserved: List or set of reserved names unavailable for use
        """
        if self.title:
            if inspect(self).has_identity:
                def checkused(c):
                    return bool(c in reserved or c in self.reserved_names or
                        self.__class__.query.filter(self.__class__.id != self.id).filter_by(name=c).notempty())
            else:
                def checkused(c):
                    return bool(c in reserved or c in self.reserved_names or
                        self.__class__.query.filter_by(name=c).notempty())
            with self.__class__.query.session.no_autoflush:
                self.name = six.text_type(make_name(self.title, maxlength=self.__name_length__, checkused=checkused))


class BaseScopedNameMixin(BaseMixin):
    """
    Base mixin class for named objects within containers. When using this,
    you must provide an model-level attribute "parent" that is a synonym for
    the parent object. You must also create a unique constraint on 'name' in
    combination with the parent foreign key. Sample use case in Flask::

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
            op.create_check_constraint(tablename + '_name_check', tablename, "name <> ''")
    """
    #: Prevent use of these reserved names
    reserved_names = []
    #: Allow blank names after all?
    __name_blank_allowed__ = False
    #: How long should names and titles be?
    __name_length__ = __title_length__ = 250

    @declared_attr
    def name(cls):
        """The URL name of this object, unique within a parent container"""
        if cls.__name_blank_allowed__:
            return Column(Unicode(cls.__name_length__), nullable=False)
        else:
            return Column(Unicode(cls.__name_length__), CheckConstraint("name <> ''"), nullable=False)

    @declared_attr
    def title(cls):
        """The title of this object"""
        return Column(Unicode(cls.__title_length__), nullable=False)

    def __init__(self, *args, **kw):
        super(BaseScopedNameMixin, self).__init__(*args, **kw)
        if self.parent and not self.name:
            self.make_name()

    def __repr__(self):
        return '<%s %s "%s" of %s>' % (self.__class__.__name__, self.name, self.title,
            repr(self.parent)[1:-1] if self.parent else None)

    @classmethod
    def get(cls, parent, name):
        """Get an instance matching the parent and name"""
        return cls.query.filter_by(parent=parent, name=name).one_or_none()

    @classmethod
    def upsert(cls, parent, name, **fields):
        """Insert or update an instance"""
        instance = cls.get(parent, name)
        if instance:
            instance._set_fields(fields)
        else:
            instance = cls(parent=parent, name=name, **fields)
            instance = failsafe_add(cls.query.session, instance, parent=parent, name=name)
        return instance

    def make_name(self, reserved=[]):
        """
        Autogenerates a :attr:`name` from the :attr:`title`. If the auto-generated name is already
        in use in this model, :meth:`make_name` tries again by suffixing numbers starting with 2
        until an available name is found.
        """
        if self.title:
            if inspect(self).has_identity:
                def checkused(c):
                    return bool(c in reserved or c in self.reserved_names or
                        self.__class__.query.filter(self.__class__.id != self.id).filter_by(
                            name=c, parent=self.parent).first())
            else:
                def checkused(c):
                    return bool(c in reserved or c in self.reserved_names or
                        self.__class__.query.filter_by(name=c, parent=self.parent).first())
            with self.__class__.query.session.no_autoflush:
                self.name = six.text_type(make_name(self.short_title(), maxlength=self.__name_length__, checkused=checkused))

    def short_title(self):
        """
        Generates an abbreviated title by subtracting the parent's title from this instance's title.
        """
        if self.title and self.parent is not None and hasattr(self.parent, 'title') and self.parent.title:
            if self.title.startswith(self.parent.title):
                short = self.title[len(self.parent.title):].strip()
                if short:
                    return short
        return self.title

    def permissions(self, user, inherited=None):
        """
        Permissions for this model, plus permissions inherited from the parent.
        """
        if inherited is not None:
            return inherited | super(BaseScopedNameMixin, self).permissions(user)
        elif self.parent is not None and isinstance(self.parent, PermissionMixin):
            return self.parent.permissions(user) | super(BaseScopedNameMixin, self).permissions(user)
        else:
            return super(BaseScopedNameMixin, self).permissions(user)


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
            op.create_check_constraint(tablename + '_name_check', tablename, "name <> ''")
    """
    #: Allow blank names after all?
    __name_blank_allowed__ = False
    #: How long should names and titles be?
    __name_length__ = __title_length__ = 250

    @declared_attr
    def name(cls):
        """The URL name of this object, non-unique"""
        if cls.__name_blank_allowed__:
            return Column(Unicode(cls.__name_length__), nullable=False)
        else:
            return Column(Unicode(cls.__name_length__), CheckConstraint("name <> ''"), nullable=False)

    @declared_attr
    def title(cls):
        """The title of this object"""
        return Column(Unicode(cls.__title_length__), nullable=False)

    def __init__(self, *args, **kw):
        super(BaseIdNameMixin, self).__init__(*args, **kw)
        if not self.name:
            self.make_name()

    def __repr__(self):
        return '<%s %s "%s">' % (self.__class__.__name__, self.url_name, self.title)

    def make_name(self):
        """Autogenerates a :attr:`name` from the :attr:`title`"""
        if self.title:
            self.name = six.text_type(make_name(self.title, maxlength=self.__name_length__))

    @set_roles(read={'all'})
    @hybrid_property
    def url_id_name(self):
        """
        Returns a URL name combining :attr:`url_id` and :attr:`name` in id-name
        syntax. This property is also available as :attr:`url_name` for legacy
        reasons.
        """
        return '%s-%s' % (self.url_id, self.name)

    @url_id_name.comparator
    def url_id_name(cls):
        if cls.__uuid_primary_key__:
            return SqlHexUuidComparator(cls.id, splitindex=0)
        elif issubclass(cls, UuidMixin):
            return SqlHexUuidComparator(cls.uuid, splitindex=0)
        else:
            return SqlSplitIdComparator(cls.id, splitindex=0)

    url_name = url_id_name  # Legacy name

    @set_roles(read={'all'})
    @hybrid_property
    def url_name_suuid(self):
        """
        Returns a URL name combining :attr:`name` and :attr:`suuid` in name-suuid syntax.
        To use this, the class must derive from :class:`UuidMixin`.
        """
        return '%s-%s' % (self.name, self.suuid)

    @url_name_suuid.comparator
    def url_name_suuid(cls):
        return SqlSuuidComparator(cls.uuid, splitindex=-1)


class BaseScopedIdMixin(BaseMixin):
    """
    Base mixin class for objects with an id that is unique within a parent.
    Implementations must provide a 'parent' attribute that is either a relationship
    or a synonym to a relationship referring to the parent object, and must
    declare a unique constraint between url_id and the parent. Sample use case in Flask::

        class Issue(BaseScopedIdMixin, db.Model):
            __tablename__ = 'issue'
            event_id = db.Column(None, db.ForeignKey('event.id'))
            event = db.relationship(Event)
            parent = db.synonym('event')
            __table_args__ = (db.UniqueConstraint('event_id', 'url_id'),)
    """
    @declared_attr
    @declared_attr_roles(read={'all'})
    def url_id(cls):
        """Contains an id number that is unique within the parent container"""
        return Column(Integer, nullable=False)

    def __init__(self, *args, **kw):
        super(BaseScopedIdMixin, self).__init__(*args, **kw)
        if self.parent:
            self.make_id()

    def __repr__(self):
        return '<%s %s of %s>' % (self.__class__.__name__, self.url_id,
            repr(self.parent)[1:-1] if self.parent else None)

    @classmethod
    def get(cls, parent, url_id):
        """Get an instance matching the parent and url_id"""
        return cls.query.filter_by(parent=parent, url_id=url_id).one_or_none()

    def make_id(self):
        """Create a new URL id that is unique to the parent container"""
        if self.url_id is None:  # Set id only if empty
            self.url_id = select([func.coalesce(func.max(self.__class__.url_id + 1), 1)],
                self.__class__.parent == self.parent)

    def permissions(self, user, inherited=None):
        """
        Permissions for this model, plus permissions inherited from the parent.
        """
        if inherited is not None:
            return inherited | super(BaseScopedIdMixin, self).permissions(user)
        else:
            return self.parent.permissions(user) | super(BaseScopedIdMixin, self).permissions(user)


class BaseScopedIdNameMixin(BaseScopedIdMixin):
    """
    Base mixin class for named objects with an id tag that is unique within a
    parent. Implementations must provide a 'parent' attribute that is a
    synonym to the parent relationship, and must declare a unique constraint
    between url_id and the parent. Sample use case in Flask::

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
            op.create_check_constraint(tablename + '_name_check', tablename, "name <> ''")
    """
    #: Allow blank names after all?
    __name_blank_allowed__ = False
    #: How long should names and titles be?
    __name_length__ = __title_length__ = 250

    @declared_attr
    def name(cls):
        """The URL name of this instance, non-unique"""
        if cls.__name_blank_allowed__:
            return Column(Unicode(cls.__name_length__), nullable=False)
        else:
            return Column(Unicode(cls.__name_length__), CheckConstraint("name <> ''"), nullable=False)

    @declared_attr
    def title(cls):
        """The title of this instance"""
        return Column(Unicode(cls.__title_length__), nullable=False)

    def __init__(self, *args, **kw):
        super(BaseScopedIdNameMixin, self).__init__(*args, **kw)
        if self.parent:
            self.make_id()
        if not self.name:
            self.make_name()

    def __repr__(self):
        return '<%s %s "%s" of %s>' % (self.__class__.__name__, self.url_name, self.title,
            repr(self.parent)[1:-1] if self.parent else None)

    @classmethod
    def get(cls, parent, url_id):
        """Get an instance matching the parent and name"""
        return cls.query.filter_by(parent=parent, url_id=url_id).one_or_none()

    def make_name(self):
        """Autogenerates a title from the name"""
        if self.title:
            self.name = six.text_type(make_name(self.title, maxlength=self.__name_length__))

    @set_roles(read={'all'})
    @hybrid_property
    def url_id_name(self):
        """Returns a URL name combining :attr:`url_id` and :attr:`name` in id-name syntax"""
        return '%s-%s' % (self.url_id, self.name)

    @url_id_name.comparator
    def url_id_name(cls):
        return SqlSplitIdComparator(cls.url_id, splitindex=0)

    url_name = url_id_name  # Legacy name


class CoordinatesMixin(object):
    """
    Adds :attr:`latitude` and :attr:`longitude` columns with a shorthand :attr:`coordinates`
    property that returns both.
    """

    latitude = Column(Numeric)
    longitude = Column(Numeric)

    @property
    def coordinates(self):
        return self.latitude, self.longitude

    @coordinates.setter
    def coordinates(self, value):
        self.latitude, self.longitude = value


# --- Column types ------------------------------------------------------------

__all_columns = ['JsonDict', 'MarkdownComposite', 'MarkdownColumn']


class JsonType(UserDefinedType):
    """The PostgreSQL JSON type."""

    def get_col_spec(self):
        return 'JSON'


class JsonbType(UserDefinedType):
    """The PostgreSQL JSONB type."""

    def get_col_spec(self):
        return 'JSONB'


# Adapted from http://docs.sqlalchemy.org/en/rel_0_8/orm/extensions/mutable.html#establishing-mutability-on-scalar-column-values

class JsonDict(TypeDecorator):
    """
    Represents a JSON data structure. Usage::

        column = Column(JsonDict)

    The column will be represented to the database as a ``JSONB`` column if
    the server is PostgreSQL 9.4 or later, ``JSON`` if PostgreSQL 9.2 or 9.3,
    and ``TEXT`` for everything else. The column behaves like a JSON store
    regardless of the backing data type.
    """

    impl = TEXT

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            version = tuple(dialect.server_version_info[:2])
            if version in [(9, 2), (9, 3)]:
                return dialect.type_descriptor(JsonType)
            elif version >= (9, 4):
                return dialect.type_descriptor(JsonbType)
        return dialect.type_descriptor(self.impl)

    def process_bind_param(self, value, dialect):
        if value is not None:
            value = simplejson.dumps(value, default=lambda o: six.text_type(o))
        return value

    def process_result_value(self, value, dialect):
        if value is not None and isinstance(value, six.string_types):
            # Psycopg2 >= 2.5 will auto-decode JSON columns, so
            # we only attempt decoding if the value is a string.
            # Since this column stores dicts only, processed values
            # can never be strings.
            value = simplejson.loads(value, use_decimal=True)
        return value


class MutableDict(Mutable, dict):
    @classmethod
    def coerce(cls, key, value):
        """Convert plain dictionaries to MutableDict."""

        if not isinstance(value, MutableDict):
            if isinstance(value, dict):
                return MutableDict(value)
            elif isinstance(value, six.string_types):
                # Assume JSON string
                if value:
                    return MutableDict(simplejson.loads(value, use_decimal=True))
                else:
                    return MutableDict()  # Empty value is an empty dict

            # this call will raise ValueError
            return Mutable.coerce(key, value)
        else:
            return value

    def __setitem__(self, key, value):
        """Detect dictionary set events and emit change events."""

        dict.__setitem__(self, key, value)
        self.changed()

    def __delitem__(self, key):
        """Detect dictionary del events and emit change events."""

        dict.__delitem__(self, key)
        self.changed()

MutableDict.associate_with(JsonDict)


@six.python_2_unicode_compatible
class MarkdownComposite(MutableComposite):
    """
    Represents GitHub-flavoured Markdown text and rendered HTML as a composite column.
    """
    def __init__(self, text, html=None):
        if html is None:
            self.text = text  # This will regenerate HTML
        else:
            object.__setattr__(self, 'text', text)
            object.__setattr__(self, '_html', html)

    # If the text value is set, regenerate HTML, then notify parents of the change
    def __setattr__(self, key, value):
        if key == 'text':
            object.__setattr__(self, '_html', markdown(value))
        object.__setattr__(self, key, value)
        self.changed()

    # Return column values for SQLAlchemy to insert into the database
    def __composite_values__(self):
        return (self.text, self._html)

    # Return a string representation of the text (see class decorator)
    def __str__(self):
        return six.text_type(self.text)

    # Return a HTML representation of the text
    def __html__(self):
        return self._html or u''

    # Return a Markup string of the HTML
    @property
    def html(self):
        return Markup(self._html or u'')

    # Compare text value
    def __eq__(self, other):
        return (self.text == other.text) if isinstance(other, MarkdownComposite) else (self.text == other)

    def __ne__(self, other):
        return not self.__eq__(other)

    # Return state for pickling
    def __getstate__(self):
        return (self.text, self._html)

    # Set state from pickle
    def __setstate__(self, state):
        object.__setattr__(self, 'text', state[0])
        object.__setattr__(self, '_html', state[1])
        self.changed()

    def __bool__(self):
        return bool(self.text)

    __nonzero__ = __bool__

    # Allow a composite column to be assigned a string value
    @classmethod
    def coerce(cls, key, value):
        return cls(value)


def MarkdownColumn(name, deferred=False, group=None, **kwargs):
    """
    Create a composite column that autogenerates HTML from Markdown text,
    storing data in db columns named with ``_html`` and ``_text`` prefixes.
    """
    return composite(MarkdownComposite,
        Column(name + '_text', UnicodeText, **kwargs),
        Column(name + '_html', UnicodeText, **kwargs),
        deferred=deferred, group=group or name
        )


# --- Helper functions --------------------------------------------------------

__all_functions = ['failsafe_add', 'set_roles', 'declared_attr_roles', 'primary_relationship']


def failsafe_add(_session, _instance, **filters):
    """
    Add and commit a new instance in a nested transaction (using SQL SAVEPOINT),
    gracefully handling failure in case a conflicting entry is already in the
    database (which may occur due to parallel requests causing race conditions
    in a production environment with multiple workers).

    Returns the instance saved to database if no error occurred, or loaded from
    database using the provided filters if an error occurred. If the filters fail
    to load from the database, the original IntegrityError is re-raised, as it
    is assumed to imply that the commit failed because of missing or invalid
    data, not because of a duplicate entry.

    However, when no filters are provided, nothing is returned and IntegrityError
    is also suppressed as there is no way to distinguish between data validation
    failure and an existing conflicting record in the database. Use this option
    when failures are acceptable but the cost of verification is not.

    Usage: ``failsafe_add(db.session, instance, **filters)`` where filters
    are the parameters passed to ``Model.query.filter_by(**filters).one()``
    to load the instance.

    You must commit the transaction as usual after calling ``failsafe_add``.

    :param _session: Database session
    :param _instance: Instance to commit
    :param filters: Filters required to load existing instance from the
        database in case the commit fails (required)
    :return: Instance that is in the database
    """
    if _instance in _session:
        # This instance is already in the session, most likely due to a
        # save-update cascade. SQLAlchemy will flush before beginning a
        # nested transaction, which defeats the purpose of nesting, so
        # remove it for now and add it back inside the SAVEPOINT.
        _session.expunge(_instance)
    _session.begin_nested()
    try:
        _session.add(_instance)
        _session.commit()
        if filters:
            return _instance
    except IntegrityError as e:
        _session.rollback()
        if filters:
            try:
                return _session.query(_instance.__class__).filter_by(**filters).one()
            except NoResultFound:  # Do not trap the other exception, MultipleResultsFound
                raise e


def primary_relationship(parent, child, parentrel, parentcol):
    """
    When a parent-child relationship is defined as one-to-many,
    :func:`primary_relationship` lets the parent refer to one child as the
    primary.

    Creates a secondary table to hold the reference. Under PostgreSQL, a trigger
    is added as well to ensure foreign key integrity.

    Multi-column primary keys on either parent or child are unsupported at this time.

    :param parent: The parent model (on which this relationship will be placed)
    :param child: The child model
    :param str parentrel: Name of the relationship on the child model that refers back to the parent model
    :param str parentcol: Name of the table column on the child model that refers back to the parent model
    """

    parent_table_name = parent.__tablename__
    child_table_name = child.__tablename__
    primary_table_name = parent_table_name + '_' + child_table_name + '_primary'
    parent_id_columns = [c.name for c in inspect(parent).primary_key]
    child_id_columns = [c.name for c in inspect(child).primary_key]

    primary_table_columns = (
        [Column(
            parent_table_name + '_' + name,
            None,
            ForeignKey(parent_table_name + '.' + name, ondelete='CASCADE'),
            primary_key=True,
            nullable=False) for name in parent_id_columns] +
        [Column(
            child_table_name + '_' + name,
            None,
            ForeignKey(child_table_name + '.' + name, ondelete='CASCADE'),
            nullable=False) for name in child_id_columns] +
        list(make_timestamp_columns())
        )

    primary_table = Table(primary_table_name, parent.metadata, *primary_table_columns)
    result = relationship(child, uselist=False, secondary=primary_table)

    # FIXME: Setting up a listener before the relationship is added to the model breaks it.
    # Have to do this later.

    # @event.listens_for(result, 'set')
    # def _validate_child(target, value, oldvalue, initiator):
    #     if value and getattr(value, parentrel) != target:
    #         raise ValueError("The target is not affiliated with this parent")

    # XXX: To support multi-column primary keys, update this SQL function
    event.listen(primary_table, 'after_create', DDL('''
        CREATE FUNCTION {primary_table_name}_validate() RETURNS TRIGGER AS $$
        DECLARE
            target RECORD;
        BEGIN
            SELECT {parentcol} INTO target FROM {child_table_name} WHERE {child_id_column} = NEW.{rhs};
            IF (target.{parentcol} != NEW.{lhs}) THEN
                RAISE foreign_key_violation USING MESSAGE = 'The target is not affiliated with this parent';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER {primary_table_name}_trigger BEFORE INSERT OR UPDATE
        ON {primary_table_name}
        FOR EACH ROW EXECUTE PROCEDURE {primary_table_name}_validate();
        '''.format(
        primary_table_name=primary_table_name,
        parentcol=parentcol,
        child_table_name=child_table_name,
        child_id_column=child_id_columns[0],
        lhs=parent_table_name + '_' + parent_id_columns[0],
        rhs=child_table_name + '_' + child_id_columns[0],
        )).execute_if(dialect='postgresql'))

    event.listen(primary_table, 'before_drop', DDL('''
        DROP TRIGGER {primary_table_name}_trigger ON {primary_table_name};
        DROP FUNCTION {primary_table_name}_validate();
        '''.format(primary_table_name=primary_table_name)).execute_if(dialect='postgresql'))

    return result


__all__ = __all_mixins + __all_columns + __all_functions
