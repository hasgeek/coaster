# -*- coding: utf-8 -*-

"""
Role-based access control
-------------------------

Coaster provides a :class:`RoleMixin` class that can be used to define role-based access
control to the attributes and methods of any SQLAlchemy model. :class:`RoleMixin` is a
base class for :class:`~coaster.sqlalchemy.mixins.BaseMixin` and applies to all derived
classes. Access is defined as one of 'call' (for methods), 'read' or 'write' (both for
attributes).

Roles are freeform string tokens. A model may freely define and grant roles to actors
(users and sometimes client apps) based on internal criteria. The following standard tokens
are recommended. Required tokens are granted by :class:`RoleMixin` itself.

1. ``all``: Any actor, authenticated or anonymous (required)
2. ``anon``: Anonymous actor (required)
3. ``auth``: Authenticated actor (required)
4. ``creator``: The creator of an object (may or may not be the current owner)
5. ``owner``: The current owner of an object
6. ``author``: Author of the object's contents (all creators are authors)
7. ``editor``: Someone authorised to edit the object
8. ``reader``: Someone authorised to read the object (assuming it's not public)

Example use::

    from flask import Flask
    from flask_sqlalchemy import SQLAlchemy
    from coaster.sqlalchemy import BaseMixin, with_roles

    app = Flask(__name__)
    db = SQLAlchemy(app)

    class ColumnMixin(object):
        '''
        Mixin class that offers some columns to the RoleModel class below,
        demonstrating two ways to use with_roles.
        '''
        @with_roles(rw={'owner'})
        def mixed_in1(cls):
            return db.Column(db.Unicode(250))

        @declared_attr
        def mixed_in2(cls):
            return with_roles(db.Column(db.Unicode(250)),
                rw={'owner'})


    class RoleModel(ColumnMixin, RoleMixin, db.Model):
        __tablename__ = 'role_model'

        # The low level approach is to declare roles in advance.
        # 'all' is a special role that is always granted from the base class.
        # Avoid this approach because you may accidentally lose roles if a
        # subclass does not copy __roles__ from parent classes.

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

        # ``with_roles`` can also be called later. This is required for
        # properties, where roles must be assigned after the property is
        # fully described.

        _title = db.Column('title', db.Unicode(250))

        @property
        def title(self):
            return self._title

        @title.setter
        def title(self, value):
            self._title = value

        # This grants 'owner' and 'editor' write but not read access
        title = with_roles(title, write={'owner', 'editor'})

        # ``with_roles`` can be used as a decorator on methods, in which case
        # access is controlled with the 'call' action.

        @with_roles(call={'all'})
        def hello(self):
            return "Hello!"

        # Your model is responsible for granting roles given an actor or anchors
        # (an iterable).

        def roles_for(self, actor=None, anchors=()):
            # Calling super give us a result set with the standard roles
            result = super(RoleModel, self).roles_for(actor, anchors)
            if 'owner-secret' in anchors:
                result.add('owner')  # Grant owner role
            return result
"""

from __future__ import absolute_import
from functools import wraps
import collections
from copy import deepcopy
import warnings
from sqlalchemy import event
from sqlalchemy.orm import mapper
from sqlalchemy.orm.attributes import InstrumentedAttribute
from ..utils import is_collection, InspectableSet
from ..auth import current_auth

__all__ = ['RoleAccessProxy', 'RoleMixin', 'with_roles', 'declared_attr_roles']

# Global dictionary for temporary storage of roles until the mapper_configured events
__cache__ = {}


class RoleAccessProxy(collections.Mapping):
    """
    A proxy interface that wraps an object and provides passthrough read and
    write access to attributes that the specified roles have access to.
    Consults the ``__roles__`` dictionary on the object for determining which roles can
    access which attributes. Provides both attribute and dictionary interfaces.

    Note that if the underlying attribute is a callable and is specified with
    the 'call' action, it will be available via attribute access but not
    dictionary access.

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
        object.__setattr__(self, '_obj', obj)
        object.__setattr__(self, 'current_roles', InspectableSet(roles))

        # Call, read and write access attributes for the given roles
        call = set()
        read = set()
        write = set()

        for role in roles:
            call.update(obj.__roles__.get(role, {}).get('call', set()))
            read.update(obj.__roles__.get(role, {}).get('read', set()))
            write.update(obj.__roles__.get(role, {}).get('write', set()))

        object.__setattr__(self, '_call', call)
        object.__setattr__(self, '_read', read)
        object.__setattr__(self, '_write', write)

    def __repr__(self):  # pragma: no cover
        return 'RoleAccessProxy(obj={obj}, roles={roles})'.format(
            obj=repr(self._obj), roles=repr(self.current_roles))

    def __getattr__(self, attr):
        # See also __getitem__, which doesn't consult _call
        if attr in self._read or attr in self._call:
            return getattr(self._obj, attr)
        else:
            raise AttributeError(attr)

    def __setattr__(self, attr, value):
        # See also __setitem__
        if attr in self._write:
            return setattr(self._obj, attr, value)
        else:
            raise AttributeError(attr)

    def __getitem__(self, key):
        # See also __getattr__, which also looks in _call
        if key in self._read:
            return getattr(self._obj, key)
        else:
            raise KeyError(key)

    def __len__(self):
        return len(self._read)

    def __contains__(self, key):
        return key in self._read or key in self._call

    def __setitem__(self, key, value):
        # See also __setattr__
        if key in self._write:
            return setattr(self._obj, key, value)
        else:
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

    When used with properties, with_roles must always be applied after the
    property is fully described::

        @property
        def title(self):
            return self._title

        @title.setter
        def title(self, value):
            self._title = value

        # Either of the following is fine, since with_roles annotates objects
        # instead of wrapping them. The return value can be discarded if it's
        # already present on the host object:

        with_roles(title, read={'all'}, write={'owner', 'editor'})
        title = with_roles(title, read={'all'}, write={'owner', 'editor'})


    :param set rw: Roles which get read and write access to the decorated
        attribute
    :param set call: Roles which get call access to the decorated method
    :param set read: Roles which get read access to the decorated attribute
    :param set write: Roles which get write access to the decorated attribute
    """
    # Convert lists and None values to sets
    rw = set(rw) if rw else set()
    call = set(call) if call else set()
    read = set(read) if read else set()
    write = set(write) if write else set()
    # `rw` is shorthand for read+write
    read.update(rw)
    write.update(rw)

    def inner(attr):
        __cache__[attr] = {'call': call, 'read': read, 'write': write}
        try:
            attr._coaster_roles = {'call': call, 'read': read, 'write': write}
            # If the attr has a restrictive __slots__, we'll get an attribute error.
            # Unfortunately, because of the way SQLAlchemy works, by copying objects
            # into subclasses, the cache alone is not a reliable mechanism. We need both.
        except AttributeError:
            pass
        return attr

    if is_collection(obj):
        # Protect against accidental specification of roles instead of an object
        raise TypeError('Roles must be specified as named parameters')
    elif obj is not None:
        return inner(obj)
    else:
        return inner

# with_roles was set_roles when originally introduced in 0.6.0
# set_roles is deprecated since 0.6.1
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
    warnings.warn("declared_attr_roles is deprecated; use with_roles", stacklevel=2)
    return inner


class RoleMixin(object):
    """
    Provides methods for role-based access control.

    Subclasses must define a :attr:`__roles__` dictionary with roles
    and the attributes they have call, read and write access to::

        __roles__ = {
            'role_name': {
                'call': {'meth1', 'meth2'},
                'read': {'attr1', 'attr2'},
                'write': {'attr1', 'attr2'},
                },
            }

    The :func:`with_roles` decorator is recommended over :attr:`__roles__`.
    """
    # This empty dictionary is necessary for the configure step below to work
    __roles__ = {}

    def roles_for(self, actor=None, anchors=()):
        """
        Return roles available to the given ``actor`` or ``anchors`` on this
        object. The data type for both parameters are intentionally undefined
        here. Subclasses are free to define them in any way appropriate. Actors
        and anchors are assumed to be valid.

        The role ``all`` is always granted. If ``actor`` is
        specified, the role ``auth`` is granted. If not, ``anon`` is
        granted.

        Subclasses overriding :meth:`roles_for` must always call :func:`super`
        to ensure they are receiving the standard roles. Recommended
        boilerplate::

            def roles_for(self, actor=None, anchors=()):
                roles = super(YourClass, self).roles_for(actor, anchors)
                # 'roles' is a set. Add more roles here
                # ...
                return roles
        """
        if actor is None:
            result = {'all', 'anon'}
        else:
            result = {'all', 'auth'}
        return result

    @property
    def current_roles(self):
        """
        :class:`~coaster.utils.classes.InspectableSet` containing currently
        available roles on this object, using
        :obj:`~coaster.auth.current_auth`. Use in the view layer to inspect
        for a role being present:

            if obj.current_roles.editor:
                pass

            {% if obj.current_roles.editor %}...{% endif %}

        This property is also available in :class:`RoleAccessProxy`.
        """
        return InspectableSet(self.roles_for(actor=current_auth.actor, anchors=current_auth.anchors))

    def actors_with(self, roles):
        """
        Return an iterable of all actors who have the specified roles on this
        object. The iterable may be a list, tuple, set or SQLAlchemy query.

        Must be implemented by subclasses.
        """
        raise NotImplementedError('Subclasses must implement actors_with')

    def access_for(self, roles=None, actor=None, anchors=[]):
        """
        Return a proxy object that limits read and write access to attributes
        based on the actor's roles. If the ``roles`` parameter isn't
        provided, :meth:`roles_for` is called with the other parameters::

            # This typical call:
            obj.access_for(actor=current_auth.actor)
            # Is shorthand for:
            obj.access_for(roles=obj.roles_for(actor=current_auth.actor))
        """
        if roles is None:
            roles = self.roles_for(actor=actor, anchors=anchors)
        elif actor is not None or anchors:
            raise TypeError('If roles are specified, actor/anchors must not be specified')
        return RoleAccessProxy(self, roles=roles)

    def current_access(self):
        """
        Wraps :meth:`access_for` with :obj:`~coaster.auth.current_auth` to
        return a proxy for the currently authenticated user.
        """
        return self.access_for(actor=current_auth.actor, anchors=current_auth.anchors)


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
                for role in data.get('call', []):
                    cls.__roles__.setdefault(role, {}).setdefault('call', set()).add(name)
                for role in data.get('read', []):
                    cls.__roles__.setdefault(role, {}).setdefault('read', set()).add(name)
                for role in data.get('write', []):
                    cls.__roles__.setdefault(role, {}).setdefault('write', set()).add(name)
                processed.add(name)


@event.listens_for(mapper, 'after_configured')
def __clear_cache():
    for key in tuple(__cache__):
        del __cache__[key]
