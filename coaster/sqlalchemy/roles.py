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
(users and sometimes client apps) based on internal criteria. The following standard
tokens are recommended. Required tokens are granted by :class:`RoleMixin` itself.

1. ``all``: Any actor, authenticated or anonymous (required)
2. ``anon``: Anonymous actor (required)
3. ``auth``: Authenticated actor (required)
4. ``creator``: The creator of an object (may or may not be the current owner)
5. ``owner``: The current owner of an object
6. ``author``: Author of the object's contents (all creators are authors)
7. ``editor``: Someone authorised to edit the object
8. ``reader``: Someone authorised to read the object (assuming it's not public)
9. ``subject``: User who is described by an object, typically having limited rights

Example use::

    from flask import Flask
    from flask_sqlalchemy import SQLAlchemy
    from coaster.sqlalchemy import BaseMixin, with_roles

    app = Flask(__name__)
    db = SQLAlchemy(app)

    class ColumnMixin(object):
        '''
        Mixin class that offers some columns to the RoleModel class below,
        demonstrating two ways to use `with_roles`.
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

        # The low level approach is to declare roles all at once.
        # 'all' is a special role that is always granted from the base class.
        # Avoid this approach in a parent or mixin class as definitions will
        # be lost if the subclass does not copy `__roles__`.

        __roles__ = {
            'all': {
                'read': {'id', 'name', 'title'},
            },
            'owner': {
                'granted_by': ['user'],
            },
        }

        # Recommended for parent and mixin classes: annotate roles on the attributes
        # using `with_roles`. These annotations are added to `__roles__` when
        # SQLAlchemy configures mappers.

        id = db.Column(db.Integer, primary_key=True)
        name = with_roles(db.Column(db.Unicode(250)),
            rw={'owner'})  # Specify read+write access

        user_id = db.Column(None, db.ForeignKey('user.id'), nullable=False)
        user = with_roles(
            db.relationship(User),
            grants={'owner'},  # Use `grants` here or `granted_by` in `__roles__`
            )

        # `with_roles` can also be called later. This is required for
        # properties, where roles must be assigned after the property is
        # fully described:

        _title = db.Column('title', db.Unicode(250))

        @property
        def title(self):
            return self._title

        @title.setter
        def title(self, value):
            self._title = value

        # This grants 'owner' and 'editor' write but not read access
        title = with_roles(title, write={'owner', 'editor'})

        # `with_roles` can be used as a decorator on methods, in which case
        # access is controlled with the 'call' action.

        @with_roles(call={'all'})
        def hello(self):
            return "Hello!"

        # `RoleMixin` will grant roles by examining relationships specified in the
        # `granted_by` list under each role in `__roles__`. The `actor` parameter
        # to `roles_for` must be present in the relationship. You can augment this
        # by providing a custom `roles_for` method:

        def roles_for(self, actor=None, anchors=()):
            # Calling super gives us a LazyRoleSet with the standard roles
            # and with lazy evaluation of of other roles from `granted_by`
            roles = super(RoleModel, self).roles_for(actor, anchors)

            # We can manually add a role to override lazy evaluation
            if 'owner-secret' in anchors:
                roles.add('owner')
            return roles
"""

from __future__ import absolute_import
import six.moves.collections_abc as abc

from copy import deepcopy
from functools import wraps
import warnings

from sqlalchemy import event
from sqlalchemy.orm import mapper
from sqlalchemy.orm.attributes import InstrumentedAttribute, QueryableAttribute
from sqlalchemy.orm.collections import (
    InstrumentedDict,
    InstrumentedList,
    InstrumentedSet,
    MappedCollection,
)
from sqlalchemy.orm.dynamic import AppenderMixin

from flask import _request_ctx_stack

from ..auth import current_auth
from ..utils import InspectableSet, is_collection, nary_op

__all__ = [
    'LazyRoleSet',
    'RoleAccessProxy',
    'DynamicAssociationProxy',
    'RoleMixin',
    'with_roles',
    'declared_attr_roles',
]

# Global dictionary for temporary storage of roles until the mapper_configured events
__cache__ = {}


def _actor_in_relationship(actor, relationship):
    """Test whether the given actor is present in the given attribute"""
    if actor == relationship:
        return True
    elif isinstance(relationship, (AppenderMixin, abc.Container)):
        return actor in relationship
    return False


class LazyRoleSet(abc.MutableSet):
    """
    Set that provides lazy evaluations for whether a role is present
    """

    def __init__(self, obj, actor, initial=()):
        self.obj = obj
        self.actor = actor
        self._present = set(initial)  # Make a copy if it's already a set
        self._not_present = set()

    def __repr__(self):  # pragma: no cover
        return 'LazyRoleSet({obj}, {actor})'.format(obj=self.obj, actor=self.actor)

    # This is required by the `MutableSet` base class
    def _from_iterable(self, iterable):
        return LazyRoleSet(self.obj, self.actor, iterable)

    def _role_is_present(self, role):
        """Test whether a role has been granted to the bound actor"""
        if role in self._present:
            return True
        elif role in self._not_present:
            return False
        elif self.actor is not None:
            if role not in self.obj.__roles__:
                self._not_present.add(role)
                return False
            for relattr in self.obj.__roles__[role].get('granted_by', ()):
                is_present = _actor_in_relationship(
                    self.actor, getattr(self.obj, relattr)
                )
                if is_present:
                    self._present.add(role)
                    return True
        self._not_present.add(role)
        return False

    def _contents(self):
        """Return all available roles"""
        # Populate cache
        [  # skipcq: PYL-W0106
            self._role_is_present(role) for role in self.obj.__roles__
        ]
        return self._present

    def __contains__(self, key):
        return self._role_is_present(key)

    def __iter__(self):
        return iter(self._contents())

    def __len__(self):
        return len(self._contents())

    def __bool__(self):
        # Make bool() faster than len() by using the cache first
        return bool(self._present) or bool(self._contents())

    __nonzero__ = __bool__  # For Python 2.7 compatibility

    def __eq__(self, other):
        if isinstance(other, LazyRoleSet):
            return (
                self.obj == other.obj
                and self.actor == other.actor
                and self._contents() == other._contents()
            )
        else:
            return self._contents() == other

    def __ne__(self, other):
        return not self.__eq__(other)

    def add(self, elem):
        """Add role `elem` to the set."""
        self._present.add(elem)
        self._not_present.discard(elem)

    def discard(self, elem):
        """Remove role `elem` from the set if it is present."""
        self._present.discard(elem)
        self._not_present.add(elem)

    # The following are for transparent compatibility with sets,
    # with the most commonly used methods

    def copy(self):
        """Return a shallow copy of the :class:`LazyRoleSet`."""
        result = LazyRoleSet(self.obj, self.actor, self._present)
        result._not_present = set(self._not_present)
        return result

    # Set operators take a single `other` parameter while these methods
    # are required to take multiple `others` to be API-compatible with sets.
    # The `nary_op` decorator does that
    issubset = nary_op(abc.MutableSet.__le__)
    issuperset = nary_op(abc.MutableSet.__ge__)
    union = nary_op(abc.MutableSet.__or__)
    intersection = nary_op(abc.MutableSet.__and__)
    difference = nary_op(abc.MutableSet.__sub__)
    symmetric_difference = nary_op(abc.MutableSet.__xor__)
    update = nary_op(abc.MutableSet.__ior__)
    intersection_update = nary_op(abc.MutableSet.__iand__)
    difference_update = nary_op(abc.MutableSet.__isub__)
    symmetric_difference_update = nary_op(abc.MutableSet.__ixor__)


class DynamicAssociationProxy(object):
    """
    Association proxy for dynamic relationships. Use this instead of SQLAlchemy's
    `association_proxy` when the underlying relationship uses `lazy='dynamic'`.

    Usage::

        # Assuming a relationship like this:
        Document.child_relationship = db.relationship(ChildDocument, lazy='dynamic')

        # Proxy to an attribute on the target of the relationship:
        Document.child_attributes = DynamicAssociationProxy(
            'child_relationship', 'attribute')

    This proxy does not provide access to the query capabilities of dynamic
    relationships. It merely optimises for containment queries. A query like this::

        Document.child_relationship.filter_by(attribute=value).exists()

    Can be reduced to this::

        value in Document.child_attributes

    :param str rel: Relationship name (must use ``lazy='dynamic'``)
    :param str attr: Attribute on the target of the relationship
    """

    def __init__(self, rel, attr):
        self.rel = rel
        self.attr = attr

    def __repr__(self):
        return 'DynamicAssociationProxy(%s, %s)' % (repr(self.rel), repr(self.attr))

    def __get__(self, obj, cls=None):
        if obj is None:
            return self
        return DynamicAssociationProxyWrapper(obj, self.rel, self.attr)


class DynamicAssociationProxyWrapper(abc.Set):
    """:class:`DynamicAssociationProxy` wrapped around an instance"""

    def __init__(self, obj, rel, attr):
        self.obj = obj
        self.rel = rel
        self.attr = attr

    def __repr__(self):
        return 'DynamicAssociationProxyWrapper(%s, %s, %s)' % (
            repr(self.obj),
            repr(self.rel),
            repr(self.attr),
        )

    def __contains__(self, member):
        rel = getattr(self.obj, self.rel)
        return rel.session.query(rel.filter_by(**{self.attr: member}).exists()).scalar()

    def __iter__(self):
        for obj in getattr(self.obj, self.rel):
            yield getattr(obj, self.attr)

    def __len__(self):
        return getattr(self.obj, self.rel).count()

    def __bool__(self):
        rel = getattr(self.obj, self.rel)
        return rel.session.query(rel.exists()).scalar()

    __nonzero__ = __bool__  # For Python 2.7 compatibility

    def __eq__(self, other):
        return (
            isinstance(other, DynamicAssociationProxyWrapper)
            and self.obj == other.obj
            and self.rel == other.rel
            and self.attr == other.attr
        )

    def __ne__(self, other):
        # This method is required as abc.Set provides a less efficient version
        return not self.__eq__(other)


class RoleAccessProxy(abc.Mapping):
    """
    A proxy interface that wraps an object and provides pass-through read and
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
    :param actor: The actor this proxy has been constructed for
    :param anchors: The anchors this proxy has been constructed with
    :param datasets: Datasets to limit attribute enumeration to

    The `actor` and `anchors` parameters are not used by the proxy, but are used to
    construct proxies for objects accessed via relationships.
    """

    def __init__(self, obj, roles, actor, anchors, datasets):
        object.__setattr__(self, '_obj', obj)
        object.__setattr__(self, 'current_roles', InspectableSet(roles))
        object.__setattr__(self, '_actor', actor)
        object.__setattr__(self, '_anchors', anchors)
        if datasets is None:
            dataset_attrs = None
            object.__setattr__(self, '_datasets', None)
        else:
            if datasets:
                dataset_attrs = set(obj.__datasets__[datasets[0]])
            else:
                # Got an empty list, so turn off enumeration
                dataset_attrs = set()
            object.__setattr__(self, '_datasets', datasets[1:])
        object.__setattr__(self, '_dataset_attrs', dataset_attrs)

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

    def __repr__(self):
        return 'RoleAccessProxy(obj={obj}, roles={roles})'.format(
            obj=repr(self._obj), roles=repr(self.current_roles)
        )

    def __get_processed_attr(self, name):
        attr = getattr(self._obj, name)
        # TODO: Implement 'write' permission control for collection relationships.
        # A proper take will require custom dict and list subclasses, similar to the
        # role access proxy itself.
        if isinstance(attr, RoleMixin):
            return attr.access_for(
                actor=self._actor, anchors=self._anchors, datasets=self._datasets
            )
        elif isinstance(attr, (InstrumentedDict, MappedCollection)):
            return {
                k: v.access_for(
                    actor=self._actor, anchors=self._anchors, datasets=self._datasets
                )
                for k, v in attr.items()
            }
        elif isinstance(attr, (InstrumentedList, InstrumentedSet, AppenderMixin)):
            # InstrumentedSet is converted into a tuple because the role access proxy
            # isn't hashable and can't be placed in a set. This is a side-effect of
            # subclassing abc.Mapping: dicts are also not hashable.
            return tuple(
                m.access_for(
                    actor=self._actor, anchors=self._anchors, datasets=self._datasets
                )
                for m in attr
            )
        else:
            return attr

    def __getattr__(self, attr):
        # See also __getitem__, which doesn't consult _call
        if attr in self._read or attr in self._call:
            return self.__get_processed_attr(attr)
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
            return self.__get_processed_attr(key)
        else:
            raise KeyError(key)

    def __len__(self):
        if self._dataset_attrs is not None:
            return len(self._read & self._dataset_attrs)
        else:
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
        if self._dataset_attrs is not None:
            source = self._read & self._dataset_attrs
        else:
            source = self._read
        for key in source:
            yield key


def with_roles(obj=None, rw=None, call=None, read=None, write=None, grants=None):
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
    :param set grants: The decorated attribute contains actors with the given roles
    """
    # Convert lists and None values to sets
    rw = set(rw) if rw else set()
    call = set(call) if call else set()
    read = set(read) if read else set()
    write = set(write) if write else set()
    grants = set(grants) if grants else set()
    # `rw` is shorthand for read+write
    read.update(rw)
    write.update(rw)

    def inner(attr):
        __cache__[attr] = {'call': call, 'read': read, 'write': write, 'grants': grants}
        try:
            attr._coaster_roles = {
                'call': call,
                'read': read,
                'write': write,
                'grants': grants,
            }
            # If the attr has a restrictive __slots__, we'll get an attribute error.
            # Unfortunately, because of the way SQLAlchemy works, by copying objects
            # into subclasses, the cache alone is not a reliable mechanism. We need both
        except AttributeError:
            pass
        return attr

    if is_collection(obj):
        # Protect against accidental specification of roles instead of an object
        raise TypeError('Roles must be specified as named parameters')
    if obj is not None:
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
                'grant': {'rel1', 'rel2'},
                },
            }

    The ``grant`` key works in reverse: if the actor is present in any of the
    attributes in the set, they are granted that role via :meth:`roles_for`.
    Attributes must be SQLAlchemy relationships and can be scalar, a collection
    or dynamic.

    The :func:`with_roles` decorator is recommended over :attr:`__roles__`.
    """

    # This empty dictionary is necessary for the configure step below to work
    __roles__ = {}
    # Datasets for limited access to attributes
    __datasets__ = {}

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
            result = LazyRoleSet(self, actor, {'all', 'anon'})
        else:
            result = LazyRoleSet(self, actor, {'all', 'auth'})
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

        .. warning::
            `current_roles` maintains a cache for efficient use in a template where
            it may be consulted multiple times. It is therefore not safe to use
            before *and* after code that modifies role assignment. Use
            :meth:`roles_for` instead, or use `current_roles` only after roles are
            changed.
        """
        cache = getattr(_request_ctx_stack.top, '_role_cache', None)
        if cache is None:
            cache = {}
            setattr(_request_ctx_stack.top, '_role_cache', cache)
        cache_key = (self, current_auth.actor, current_auth.anchors)
        if cache_key not in cache:
            cache[cache_key] = InspectableSet(
                self.roles_for(actor=current_auth.actor, anchors=current_auth.anchors)
            )
        return cache[cache_key]

    def actors_with(self, roles):
        """
        Return actors who have the specified roles on this object.

        Uses ``__roles__[role]['granted_by']`` to discover actors via relationships.
        """
        if not is_collection(roles):
            raise ValueError("`roles` parameter must be a set")
        actors = set()
        for role in roles:
            for relattr in self.__roles__.get(role, {}).get('granted_by', []):
                attr = getattr(self, relattr)
                if isinstance(attr, (AppenderMixin, abc.Iterable)):
                    actors.update(attr)
                elif isinstance(getattr(type(self), relattr), InstrumentedAttribute):
                    actors.add(attr)
        return actors

    def access_for(self, roles=None, actor=None, anchors=(), datasets=None):
        """
        Return a proxy object that limits read and write access to attributes
        based on the actor's roles.

        .. warning::
            If the `roles` parameter is provided, it overrides discovery of the actor's
            roles in both the current object and related objects. It should only be
            used when roles are pre-determined and related objects are not required.

        :param set roles: Roles to limit access to (not recommended)
        :param actor: Limit access to this actor's roles
        :param anchors: Retrieve additional roles from anchors
        :param tuple datasets: Limit enumeration to the attributes in the dataset

        If a `datasets` sequence is provided, the first dataset is applied to the
        current object and subsequent datasets are applied to objects accessed via
        relationships. Datasets limit the attributes available via enumeration when the
        proxy is cast into a dict or JSON. This can be used to remove unnecessary data
        or bi-directional relationships, which JSON can't handle.

        Attributes must be specified in a ``__datasets__`` dictionary on the object::

            __datasets__ = {
                'primary': {'uuid', 'name', 'title', 'children', 'parent'},
                'related': {'uuid', 'name', 'title'}
            }

        Objects and related objects can be safely enumerated like this::

            proxy = obj.access_for(user, datasets=('primary', 'related'))
            proxydict = dict(proxy)
            proxyjson = json.dumps(proxy)  # This needs a custom JSON encoder

        If a dataset includes an attribute the role doesn't have access to, it will be
        skipped. If it includes a relationship for which no dataset is specified, it
        will be rendered as an empty object.
        """
        if roles is None:
            roles = self.roles_for(actor=actor, anchors=anchors)
        elif actor is not None or anchors:
            raise TypeError(
                'If roles are specified, actor/anchors must not be specified'
            )
        return RoleAccessProxy(
            self, roles=roles, actor=actor, anchors=anchors, datasets=datasets
        )

    def current_access(self, datasets=None):
        """
        Wraps :meth:`access_for` with :obj:`~coaster.auth.current_auth` to
        return a proxy for the currently authenticated user.

        :param tuple datasets: Datasets to limit enumeration to
        """
        return self.access_for(
            actor=current_auth.actor, anchors=current_auth.anchors, datasets=datasets
        )


@event.listens_for(RoleMixin, 'mapper_configured', propagate=True)
def _configure_roles(mapper_, cls):
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

            if isinstance(attr, abc.Hashable) and attr in __cache__:
                data = __cache__[attr]
                del __cache__[attr]
            elif isinstance(attr, QueryableAttribute) and hasattr(
                attr, 'original_property'
            ):
                if hasattr(attr.original_property, '_coaster_roles'):
                    data = attr.original_property._coaster_roles
                else:
                    data = None
            elif isinstance(attr, InstrumentedAttribute) and attr.property in __cache__:
                data = __cache__[attr.property]
                del __cache__[attr.property]
            elif hasattr(attr, '_coaster_roles'):
                data = attr._coaster_roles
            else:
                data = None
            if data is not None:
                for role in data.get('call', []):
                    cls.__roles__.setdefault(role, {}).setdefault('call', set()).add(
                        name
                    )
                for role in data.get('read', []):
                    cls.__roles__.setdefault(role, {}).setdefault('read', set()).add(
                        name
                    )
                for role in data.get('write', []):
                    cls.__roles__.setdefault(role, {}).setdefault('write', set()).add(
                        name
                    )
                for role in data.get('grants', ()):
                    granted_by = cls.__roles__.setdefault(role, {}).setdefault(
                        'granted_by', []
                    )
                    if name not in granted_by:
                        granted_by.append(name)
                processed.add(name)


@event.listens_for(mapper, 'after_configured')
def _clear_cache():
    for key in tuple(__cache__):
        del __cache__[key]
