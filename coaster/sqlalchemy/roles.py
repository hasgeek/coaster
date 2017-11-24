# -*- coding: utf-8 -*-

"""
Role-based access control
-------------------------

Coaster provides a :class:`RoleMixin` class that can be used to define role-based access
control to the attributes and methods of any SQLAlchemy model. :class:`RoleMixin` is a
base class for :class:`~coaster.sqlalchemy.BaseMixin` and applies to all derived classes.

Roles are freeform string tokens. A model may freely define and grant roles to
users based on internal criteria. The following standard tokens are
recommended. Required tokens are granted by :class:`RoleMixin` itself.

1. ``all``: Any user, authenticated or anonymous (required)
2. ``anon``: Anonymous user (required)
3. ``user``: Logged in user or user token (required)
4. ``creator``: The creator of an object (may or may not be the current owner)
5. ``owner``: The current owner of an object
6. ``author``: Author of the object's contents
7. ``editor``: Someone authorised to edit the object
8. ``reader``: Someone authorised to read the object (assuming it's not public)

Example use::

    from flask import Flask
    from flask_sqlalchemy import SQLAlchemy
    from coaster.sqlalchemy import BaseMixin, with_roles

    app = Flask(__name__)
    db = SQLAlchemy(app)

    class DeclaredAttrMixin(object):
        # Standard usage
        @with_roles(rw={'owner'})
        def mixed_in1(cls):
            return db.Column(db.Unicode(250))

        # Roundabout approach
        @declared_attr
        def mixed_in2(cls):
            return with_roles(db.Column(db.Unicode(250)),
                rw={'owner'})

        # Deprecated since 0.6.1
        @declared_attr
        @declared_attr_roles(rw={'owner', 'editor'}, read={'all'})
        def mixed_in3(cls):
            return db.Column(db.Unicode(250))


    class RoleModel(DeclaredAttrMixin, RoleMixin, db.Model):
        __tablename__ = 'role_model'

        # The low level approach is to declare roles in advance.
        # 'all' is a special role that is always granted from the base class.
        # Avoid this approach because you may accidentally lose roles defined
        # in base classes.

        __roles__ = {
            'all': {
                'read': {'id', 'name', 'title'}
            }
        }

        # Recommended: annotate roles on the attributes using ``with_roles``.
        # These annotations always add to anything specified in ``__roles__``.

        id = db.Column(db.Integer, primary_key=True)
        name = with_roles(db.Column(db.Unicode(250)),
            rw={'owner'})  # Specify read+write access

        # ``with_roles`` can also be called later. This is typically required
        # for properties, where roles must be assigned after the property is
        # fully described.

        _title = db.Column('title', db.Unicode(250))

        @property
        def title(self):
            return self._title

        @title.setter
        def title(self, value):
            self._title = value

        title = with_roles(title, write={'owner', 'editor'})  # This grants 'owner' and 'editor' write but not read access

        # ``with_roles`` can be used as a decorator on functions.
        # 'call' is an alias for 'read', to be used for clarity.

        @with_roles(call={'all'})
        def hello(self):
            return "Hello!"

        # Your model is responsible for granting roles given a user or
        # user token. The format of tokens is not specified by RoleMixin.

        def roles_for(self, user=None, token=None):
            # Calling super give us a result set with the standard roles
            result = super(RoleModel, self).roles_for(user, token)
            if token == 'owner-secret':
                result.add('owner')  # Grant owner role
            return result
"""

from __future__ import absolute_import
from functools import wraps
import collections
from copy import deepcopy
from sqlalchemy import event
from sqlalchemy.orm import mapper
from sqlalchemy.orm.attributes import InstrumentedAttribute

__all__ = ['RoleAccessProxy', 'RoleMixin', 'with_roles', 'declared_attr_roles']

# Global dictionary for temporary storage of roles until the mapper_configured events
__cache__ = {}


class RoleAccessProxy(collections.Mapping):
    """
    A proxy interface that wraps an object and provides passthrough read and
    write access to attributes that the specified roles have access to.
    Consults the ``__roles__`` dictionary on the object for determining which roles can
    access which attributes. Provides both attribute and dictionary interfaces.

    Note that if the underlying attribute is a callable, calls are controlled
    by the read action. Care should be taken when the callable mutates the
    object.

    :class:`RoleAccessProxy` is typically accessed directly from the target
    object via :meth:`~RoleMixin.access_for` (from :class:`RoleMixin`).

    Example::

        proxy = RoleAccessProxy(obj, roles={'writer'})
        proxy.attr1
        proxy.attr1 = 'new value'
        proxy['attr2'] = 'new value'
        dict(proxy)

    :param obj: The object that should be wrapped with the proxy
    :param roles: A set of roles to determine what attributes are accessible

    """
    def __init__(self, obj, roles):
        self.__dict__['_obj'] = obj
        self.__dict__['_roles'] = roles

        # Read and write access attributes for the given roles
        read = set()
        write = set()

        for role in roles:
            read.update(obj.__roles__.get(role, {}).get('read', set()))
            write.update(obj.__roles__.get(role, {}).get('write', set()))

        self.__dict__['_read'] = read
        self.__dict__['_write'] = write

    def __repr__(self):  # pragma: no cover
        return '<RoleAccessProxy(obj={obj}, roles={roles})>'.format(
            obj=repr(self._obj), roles=repr(self._roles))

    def __getattr__(self, attr):
        if attr in self._read:
            return getattr(self._obj, attr)
        else:
            raise AttributeError(attr)

    def __setattr__(self, attr, value):
        if attr in self._write:
            return setattr(self._obj, attr, value)
        else:
            raise AttributeError(attr)

    def __getitem__(self, key):
        try:
            return self.__getattr__(key)
        except AttributeError:
            raise KeyError(key)

    def __len__(self):
        return len(self._read)

    def __contains__(self, key):
        return key in self._read

    def __setitem__(self, key, value):
        try:
            self.__setattr__(key, value)
        except AttributeError:
            raise KeyError(key)

    def __iter__(self):
        for key in self._read:
            yield key


def with_roles(obj=None, rw=None, call=None, read=None, write=None):
    """
    Convenience function and decorator to define roles on an attribute. Only
    works with :class:`RoleMixin`, which reads the annotations made by this
    function and populates :attr:`~RoleMixin.__roles__`.

    Examples::

        id = db.Column(Integer, primary_key=True)
        with_roles(id, read={'all'})

        @with_roles(read={'all'})
        @hybrid_property
        def url_id(self):
            return str(self.id)

    :param set rw: Roles which get read and write access to the decorated
        attribute
    :param set call: Roles which get call access to the decorated method.
        Due to technical limitations, ``call`` is just an alias for ``read``.
        Any role with read access to a method can also call it
    :param set read: Roles which get read access to the decorated attribute
    :param set write: Roles which get write access to the decorated attribute
    """
    # Convert lists and None values to sets
    rw = set(rw) if rw else set()
    call = set(call) if call else set()
    read = set(read) if read else set()
    write = set(write) if write else set()
    # `call` is just an alias for `read` due to limitations in RoleAccessProxy.
    read.update(call)
    # `rw` is shorthand for read+write
    read.update(rw)
    write.update(rw)

    def inner(attr):
        __cache__[attr] = {'read': read, 'write': write}
        try:
            attr._coaster_roles = {'read': read, 'write': write}
            # If the attr has a restrictive __slots__, we'll get an attribute error.
            # Unfortunately, because of the way SQLAlchemy works, by copying objects
            # into subclasses, the cache alone is not a reliable mechanism. We need both.
        except AttributeError:
            pass
        return attr

    if isinstance(obj, (list, tuple, set)):
        # Protect against accidental specification of roles instead of an object
        raise TypeError('Roles must be specified as named parameters')
    elif obj is not None:
        return inner(obj)
    else:
        return inner

# with_roles was set_roles when originally introduced in 0.6.0
set_roles = with_roles


def declared_attr_roles(rw=None, call=None, read=None, write=None):
    """
    Equivalent of :func:`with_roles` for use with ``@declared_attr``::

        @declared_attr
        @declared_attr_roles(read={'all'})
        def my_column(cls):
            return Column(Integer)

    While :func:`with_roles` is always the outermost decorator on properties
    and functions, :func:`declared_attr_roles` must appear below
    ``@declared_attr`` to work correctly.

    .. deprecated:: 0.6.1
        Use :func:`with_roles` instead. It works for
        :class:`~sqlalchemy.ext.declarative.declared_attr` since 0.6.1
    """
    def inner(f):
        @wraps(f)
        def attr(cls):
            # Pass f(cls) as a parameter to with_roles.inner to avoid the test for
            # iterables within with_roles. We have no idea about the use cases for
            # declared_attr in downstream code. There could be a declared_attr
            # that returns a list that should be accessible via the proxy.
            return with_roles(rw=rw, call=call, read=read, write=write)(f(cls))
        return attr
    return inner


class RoleMixin(object):
    """
    Provides methods for role-based access control.

    Subclasses must define a :attr:`__roles__` dictionary with roles
    and the attributes they have read and write access to::

        __roles__ = {
            'role_name': {
                'read': {'attr1', 'attr2'}
                'write': {'attr1', 'attr2'}
                },
            }
    """
    # This empty dictionary is necessary for the configure step below to work
    __roles__ = {}

    def roles_for(self, user=None, token=None):
        """
        Return roles available to the given ``user`` or ``token`` on this
        object. The data type for both parameters are intentionally undefined
        here. Subclasses are free to define them in any way appropriate. Users
        and tokens are assumed to be valid.

        The role ``all`` is always granted. If either ``user`` or ``token`` is
        specified, the role ``user`` is granted. If neither, ``anon`` is
        granted.
        """
        if user is not None and token is not None:
            raise TypeError('Either user or token must be specified, not both')

        if user is None and token is None:
            result = {'all', 'anon'}
        else:
            result = {'all', 'user'}
        return result

    def users_with(self, roles):
        """
        Return an iterable of all users who have the specified roles on this
        object. The iterable may be a list, tuple, set or SQLAlchemy query.

        Must be implemented by subclasses.
        """
        raise NotImplementedError('Subclasses must implement users_with')

    def make_token_for(self, user, roles=None, token=None):
        """
        Generate a token for the specified user that grants access to this
        object alone, with either all roles available to the user, or just
        the specified subset. If an existing token is available, add to it.

        This method should return ``None`` if a token cannot be generated.
        Must be implemented by subclasses.
        """
        # TODO: Consider implementing this method so subclasses don't have to.
        # This is where we introduce a standard implementation such as JWT or
        # libmacaroons.
        raise NotImplementedError('Subclasses must implement make_token_for')

    def access_for(self, roles=None, user=None, token=None):
        """
        Return a proxy object that limits read and write access to attributes
        based on the user's roles. If the ``roles`` parameter isn't provided,
        but a ``user`` or ``token`` is provided instead, :meth:`roles_for` is
        called::

            # This typical call:
            obj.access_for(user=current_auth.user)
            # Is shorthand for:
            obj.access_for(roles=obj.roles_for(user=current_auth.user))
        """
        if roles is None:
            roles = self.roles_for(user=user, token=token)
        elif user is not None or token is not None:
            raise TypeError('If roles are specified, user and token must not be specified')
        return RoleAccessProxy(self, roles=roles)


@event.listens_for(RoleMixin, 'mapper_configured', propagate=True)
def __configure_roles(mapper, cls):
    """
    Run through attributes of the class looking for role decorations from
    :func:`with_roles` and add them to :attr:`cls.__roles__`
    """
    # Don't mutate ``__roles__`` in the base class.
    # The subclass must have its own.
    # Since classes may specify ``__roles__`` directly without
    # using :func:`with_roles`, we must preserve existing content.
    if '__roles__' not in cls.__dict__:
        # If the following line is confusing, it's because reading an
        # attribute on an object invokes the Method Resolution Order (MRO)
        # mechanism to find it on base classes, while writing always writes
        # to the current object.
        cls.__roles__ = deepcopy(cls.__roles__)

    # An attribute may be defined more than once in base classes. Only handle the first
    processed = set()

    # Loop through all attributes in this and base classes, looking for role annotations
    for base in cls.__mro__:
        for name, attr in base.__dict__.items():
            if name in processed or name.startswith('__'):
                continue

            if isinstance(attr, collections.Hashable) and attr in __cache__:
                data = __cache__[attr]
                del __cache__[attr]
            elif isinstance(attr, InstrumentedAttribute) and attr.property in __cache__:
                data = __cache__[attr.property]
                del __cache__[attr.property]
            elif hasattr(attr, '_coaster_roles'):
                data = attr._coaster_roles
            else:
                data = None
            if data is not None:
                for role in data.get('read', []):
                    cls.__roles__.setdefault(role, {}).setdefault('read', set()).add(name)
                for role in data.get('write', []):
                    cls.__roles__.setdefault(role, {}).setdefault('write', set()).add(name)
                processed.add(name)


@event.listens_for(mapper, 'after_configured')
def __clear_cache():
    for key in tuple(__cache__):
        del __cache__[key]
