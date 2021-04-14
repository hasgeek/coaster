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

    class ColumnMixin:
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
            roles = super().roles_for(actor, anchors)

            # We can manually add a role to override lazy evaluation
            if 'owner-secret' in anchors:
                roles.add('owner')
            return roles
"""

from abc import ABCMeta
from copy import deepcopy
from functools import wraps
from itertools import chain
from typing import Dict, List, Optional, Set, Union
import collections.abc as abc
import operator
import warnings

from sqlalchemy import event, inspect
from sqlalchemy.ext.orderinglist import OrderingList
from sqlalchemy.orm import ColumnProperty, Query, RelationshipProperty, SynonymProperty
from sqlalchemy.orm.attributes import QueryableAttribute
from sqlalchemy.orm.collections import (
    InstrumentedDict,
    InstrumentedList,
    InstrumentedSet,
    MappedCollection,
)
from sqlalchemy.orm.dynamic import AppenderMixin
from sqlalchemy.schema import SchemaItem

# mypy can't find _request_ctx_stack in flask
from flask import _request_ctx_stack  # type: ignore[attr-defined]

from ..auth import current_auth
from ..utils import InspectableSet, is_collection, nary_op

try:  # SQLAlchemy >= 1.4
    from sqlalchemy.orm import MapperProperty  # type: ignore[attr-defined]
except ImportError:  # SQLAlchemy < 1.4
    from sqlalchemy.orm.interfaces import MapperProperty


__all__ = [
    'RoleGrantABC',
    'LazyRoleSet',
    'RoleAccessProxy',
    'DynamicAssociationProxy',
    'RoleMixin',
    'with_roles',
    'declared_attr_roles',
]

# Global dictionary for temporary storage of roles until the mapper_configured events
__cache__ = {}


def _attrs_equal(lhs, rhs):
    """
    Helper function to compare two strings or two QueryableAttributes.
    QueryableAttributes can't be compared with `==` to confirm both are same object.
    But strings can't be compared with `is` to confirm they are the same string.
    We have to change the operator based on types being compared.
    """
    if isinstance(lhs, str) and isinstance(rhs, str):
        return lhs == rhs
    return lhs is rhs


def _actor_in_relationship(actor, relationship):
    """Test whether the given actor is present in the given attribute"""
    if actor == relationship:
        return True
    if isinstance(relationship, (AppenderMixin, Query, abc.Container)):
        return actor in relationship
    return False


def _roles_via_relationship(actor, relationship, actor_attr, roles, offer_map):
    """Find roles granted via a relationship"""
    relobj = None  # Role-granting object found via the relationship

    # There is no actor_attr. Check if the relationship is a RoleMixin and call
    # roles_for to get offered roles, then remap using the offer map.
    if actor_attr is None:
        if isinstance(relationship, RoleMixin):
            offered_roles = relationship.roles_for(actor)
            if offer_map:
                offered_roles = set(
                    chain.from_iterable(
                        offer_map[role] for role in offered_roles if role in offer_map
                    )
                )
            return offered_roles
        raise TypeError(
            "{0!r} is not a RoleMixin and no actor attribute was specified".format(
                relationship
            )
        )

    # We have a relationship. If it's a collection, find the item in it that relates
    # to the actor.
    if isinstance(relationship, (AppenderMixin, Query)):
        # Query-like relationship. Run a query. It is possible to have multiple matches
        # for the actor, so use .first()
        # TODO: Consider retrieving all and consolidating roles from across them in case
        # the objects are RoleGrantABC. This is not a current requirement and so is not
        # currently supported; using the .first() object is sufficient
        if isinstance(actor_attr, QueryableAttribute):
            relobj = relationship.filter(operator.eq(actor_attr, actor)).first()
        else:
            relobj = relationship.filter_by(**{actor_attr: actor}).first()
    elif isinstance(relationship, abc.Iterable):
        # List-like object. Scan through it looking for item related to actor.
        # Note: strings are also collections. Checking for abc.Iterable is only safe
        # here because of the unlikeliness of a string relationship. If that becomes
        # necessary in future, add `and not isinstance(relationship, str)`
        for relitem in relationship:
            if getattr(relitem, actor_attr) == actor:
                relobj = relitem
                break

    # Not any sort of collection. May be a scalar relationship
    elif getattr(relationship, actor_attr) == actor:
        relobj = relationship
    if not relobj:
        # Didn't find a relationship object. Actor gets no roles
        return ()

    # We have a related object. Get roles from it
    if isinstance(relobj, RoleGrantABC):
        # If this object grants roles, get them. It may not grant the one we're looking
        # for and that's okay. Grab the others
        offered_roles = relobj.offered_roles
        # But if we have an offer_map, remap the roles and only keep the ones
        # specified in the map
        if offer_map:
            offered_roles = set(
                chain.from_iterable(
                    offer_map[role] for role in offered_roles if role in offer_map
                )
            )
        return offered_roles
    # Not a role granting object. Implies that the default roles are granted
    # by its very existence.
    return roles


class RoleGrantABC(metaclass=ABCMeta):
    """Base class for an object that grants roles to an actor"""

    @property
    def offered_roles(self):  # pragma: no cover
        """Roles offered by this object"""
        return ()

    @classmethod
    def __subclasshook__(cls, c):
        if cls is RoleGrantABC:
            if any('offered_roles' in b.__dict__ for b in c.__mro__):
                return True
            return False
        return NotImplemented  # pragma: no cover


class LazyRoleSet(abc.MutableSet):
    """
    Set that provides lazy evaluations for whether a role is present
    """

    def __init__(self, obj, actor, initial=()):
        self.obj = obj
        self.actor = actor
        #: Roles that the actor has (make a copy of initial set as it will be mutated)
        self._present = set(initial)
        #: Roles the actor does not have
        self._not_present = set()
        # Relationships that have been scanned already
        self._scanned_granted_via = set()  # Contains (relattr, actor_attr)
        self._scanned_granted_by = set()  # Contains relattr

    def __repr__(self):  # pragma: no cover
        return 'LazyRoleSet({obj}, {actor})'.format(obj=self.obj, actor=self.actor)

    # This is required by the `MutableSet` base class
    def _from_iterable(self, it):
        return LazyRoleSet(self.obj, self.actor, it)

    def _role_is_present(self, role):
        """Test whether a role has been granted to the bound actor"""
        if role in self._present:
            return True
        if role in self._not_present:
            return False
        if self.actor is not None:
            if role not in self.obj.__roles__:
                self._not_present.add(role)
                return False
            # granted_via says a role may be granted by a secondary object that sits
            # in a relationship between the current object and the actor. The secondary
            # could be a direct attribute of the current object, or could be inside a
            # list or query relationship. _roles_via_relationship will check.
            # The related object may grant roles in one of three ways:
            # 1. By its mere existence (default).
            # 2. By offering roles via an `offered_roles` property (see `RoleGrantABC`).
            # 3. By being a `RoleMixin` instance that has a `roles_for` method.
            if 'granted_via' in self.obj.__roles__[role]:
                for relattr, actor_attr in self.obj.__roles__[role][
                    'granted_via'
                ].items():
                    offer_map = self.obj.__relationship_role_offer_map__.get(relattr)
                    if (relattr, actor_attr) not in self._scanned_granted_via:
                        relationship = self.obj._get_relationship(relattr)
                        if relationship is not None:
                            # Optimization: does the same relationship grant other roles
                            # via the same actor_attr? Gather those roles and check all
                            # of them together. However, we will use a single role
                            # offer map and not consult the one specified on the other
                            # roles. They are expected to be identical. This is
                            # guaranteed if the offer map was specified using
                            # `with_roles(grants_via=)` but not if specified directly
                            # in `__roles__[role]['granted_via']`.
                            possible_roles = {role}
                            for arole, actions in self.obj.__roles__.items():
                                if (
                                    arole != role
                                    and 'granted_via' in actions
                                    and relattr in actions['granted_via']
                                    and _attrs_equal(
                                        actions['granted_via'][relattr], actor_attr
                                    )
                                ):
                                    possible_roles.add(arole)

                            granted_roles = _roles_via_relationship(
                                self.actor,
                                relationship,
                                actor_attr,
                                possible_roles,
                                offer_map,
                            )
                            self._present.update(granted_roles)
                            self._scanned_granted_via.add((relattr, actor_attr))
                            if role in granted_roles:
                                return True
            # granted_by says a role is granted by the actor being present in a
            # relationship
            if 'granted_by' in self.obj.__roles__[role]:
                for relattr in self.obj.__roles__[role]['granted_by']:
                    if relattr not in self._scanned_granted_by:
                        relationship = self.obj._get_relationship(relattr)
                        is_present = _actor_in_relationship(self.actor, relationship)
                        if is_present:
                            self._present.add(role)
                            # Optimization: does this relationship grant other roles?
                            # Get them rightaway. Don't query again later.
                            for arole, actions in self.obj.__roles__.items():
                                if (
                                    arole != role
                                    and 'granted_by' in actions
                                    and relattr in actions['granted_by']
                                ):
                                    self._present.add(arole)
                            return True
                        self._scanned_granted_by.add(relattr)
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
        return self._contents() == other

    def __ne__(self, other):
        return not self.__eq__(other)

    def add(self, value):
        """Add role `value` to the set."""
        self._present.add(value)
        self._not_present.discard(value)

    def discard(self, value):
        """Remove role `value` from the set if it is present."""
        self._present.discard(value)
        self._not_present.add(value)

    def has_any(self, roles):
        """
        Convenience method for checking if any of the given roles is present in the set.

        Equivalent of evaluating using either of these approaches:

        1. ``not roles.isdisjoint(lazy_role_set)``
        2. ``any(role in lazy_role_set for role in roles)``

        This implementation optimizes for cached roles before evaluating role granting
        sources that may cause a database hit.
        """
        if not self._present.isdisjoint(roles):
            return True
        return any(role in self for role in roles)

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


class DynamicAssociationProxy:
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
                try:
                    dataset_attrs = set(obj.__datasets__[datasets[0]])
                except KeyError:
                    raise KeyError(
                        "Object of type %r is missing dataset %s"
                        % (type(obj), datasets[0])
                    )
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
        if isinstance(attr, (InstrumentedDict, MappedCollection)):
            return {
                k: v.access_for(
                    actor=self._actor, anchors=self._anchors, datasets=self._datasets
                )
                for k, v in attr.items()
            }
        if isinstance(
            attr,
            (InstrumentedList, InstrumentedSet, AppenderMixin, OrderingList, Query),
        ):
            # InstrumentedSet is converted into a tuple because the role access proxy
            # isn't hashable and can't be placed in a set. This is a side-effect of
            # subclassing abc.Mapping: dicts are also not hashable.
            return tuple(
                m.access_for(
                    actor=self._actor, anchors=self._anchors, datasets=self._datasets
                )
                for m in attr
            )
        return attr

    def __getattr__(self, attr):
        # See also __getitem__, which doesn't consult _call
        if attr in self._read or attr in self._call:
            return self.__get_processed_attr(attr)
        raise AttributeError(attr)

    def __setattr__(self, attr, value):
        # See also __setitem__
        if attr in self._write:
            return setattr(self._obj, attr, value)
        raise AttributeError(attr)

    def __getitem__(self, key):
        # See also __getattr__, which also looks in _call
        if key in self._read:
            return self.__get_processed_attr(key)
        raise KeyError(key)

    def __len__(self):
        if self._dataset_attrs is not None:
            return len(self._read & self._dataset_attrs)
        return len(self._read)

    def __contains__(self, key):
        return key in self._read or key in self._call

    def __setitem__(self, key, value):
        # See also __setattr__
        if key in self._write:
            return setattr(self._obj, key, value)
        raise KeyError(key)

    def __iter__(self):
        if self._dataset_attrs is not None:
            source = self._read & self._dataset_attrs
        else:
            source = self._read
        for key in source:
            yield key


def with_roles(
    obj=None,
    rw=None,
    call=None,
    read=None,
    write=None,
    grants=None,
    grants_via=None,
    datasets=None,
):
    """
    Convenience function and decorator to define roles on an attribute. Only
    works with :class:`RoleMixin`, which reads the annotations made by this
    function and populates :attr:`~RoleMixin.__roles__`.

    Examples::

        id = db.Column(Integer, primary_key=True)
        with_roles(id, read={'all'})

        title = with_roles(db.Column(db.UnicodeText), read={'all'})

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

        title = with_roles(title, read={'all'}, write={'owner', 'editor'})
        with_roles(title, read={'all'}, write={'owner', 'editor'})

    :param set rw: Roles which get read and write access to the decorated
        attribute
    :param set call: Roles which get call access to the decorated method
    :param set read: Roles which get read access to the decorated attribute
    :param set write: Roles which get write access to the decorated attribute
    :param set grants: The decorated attribute contains actors with the given roles
    :param dict grants_via: The decorated attribute is a relationship to another
        object type which contains one or more actors who are granted roles here
    :param set datasets: Datasets to include the attribute in

    ``grants_via`` is typically used like this::

        class RoleModel(db.Model):
            user_id = db.Column(None, db.ForeignKey('user.id'))
            user = db.relationship(UserModel)

            document_id = db.Column(None, db.ForeignKey('document.id'))
            document = db.relationship(DocumentModel)

        DocumentModel.rolemodels = with_roles(db.relationship(RoleModel),
            grants_via={'user': {'role1', 'role2'}})

    In this example, a user gets roles 'role1' and 'role2' on DocumentModel via the
    secondary RoleModel. Grants are recorded in ``__roles__['role1']['granted_via']``
    and are honoured by the :class:`LazyRoleSet` used in :meth:`~RoleMixin.roles_for`.

    ``grants_via`` supports an additional advanced definition for when the role granting
    model has variable roles and offers them via a property named ``offered_roles``::

        class RoleModel(db.Model):
            user_id = db.Column(None, db.ForeignKey('user.id'))
            user = db.relationship(UserModel)

            has_role1 = db.Column(db.Boolean)
            has_role2 = db.Column(db.Boolean)

            document_id = db.Column(None, db.ForeignKey('document.id'))
            document = db.relationship(DocumentModel)

            @property
            def offered_roles(self):
                roles = set()
                if self.has_role1:
                    roles.add('role1')
                if self.has_role2:
                    roles.add('role2')
                return roles

        DocumentModel.rolemodels = with_roles(db.relationship(RoleModel),
            grants_via={'user': {
                'role1': 'renamed_role1,
                'role2': {'renamed_role2', 'also_role2'}
            }}
        )
    """
    # Convert lists and None values to sets
    rw = set(rw) if rw else set()
    call = set(call) if call else set()
    read = set(read) if read else set()
    write = set(write) if write else set()
    grants = set(grants) if grants else set()
    if not grants_via:
        grants_via = {}
    if not datasets:
        datasets = {}
    # `rw` is shorthand for read+write
    read.update(rw)
    write.update(rw)

    def inner(attr):
        if isinstance(attr, SynonymProperty):
            raise TypeError(
                "Synonyms cannot have roles as they acquire from the underlying entity"
            )
        data = {
            'call': call,
            'read': read,
            'write': write,
            'grants': grants,
            'grants_via': grants_via,
            'datasets': datasets,
        }
        if attr in __cache__:
            raise TypeError("Duplicate use of with_roles for this attribute")
        __cache__[attr] = data
        if isinstance(attr, (SchemaItem, ColumnProperty, MapperProperty)):
            if '_coaster_roles' in attr.info:
                raise TypeError("Duplicate use of with_roles for this attribute")
            attr.info['_coaster_roles'] = data
        else:
            try:
                if hasattr(attr, '_coaster_roles'):
                    raise TypeError("Duplicate use of with_roles for this attribute")
                attr._coaster_roles = data
                # If the attr has a restrictive __slots__, we'll get an attribute error.
                # Unfortunately, because of the way SQLAlchemy works, by copying objects
                # into subclasses, the cache alone is not a reliable mechanism. We need
                # both
            except AttributeError:
                pass
        return attr

    if is_collection(obj):
        # Protect against accidental specification of roles instead of an object
        raise TypeError('Roles must be specified as named parameters')
    if obj is not None:
        return inner(obj)
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

    warnings.warn(
        "declared_attr_roles is deprecated; use with_roles",
        DeprecationWarning,
        stacklevel=2,
    )
    return inner


class RoleMixin:
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
    __roles__: Dict[
        str, Dict[str, Union[Set[str], List[str], Dict[str, Optional[str]]]]
    ] = {}
    # Datasets for limited access to attributes
    __datasets__: Dict[str, Set[str]] = {}
    # Relationship role offer map (used by LazyRoleSet)
    __relationship_role_offer_map__: Dict[str, Set[str]] = {}
    # Relationship reversed role offer map (used by actors_with)
    __relationship_reversed_role_offer_map__: Dict[str, Set[str]] = {}

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
                roles = super().roles_for(actor, anchors)
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

    def _get_relationship(self, relattr):
        if '.' in relattr:
            # Did we get a 'relationship.attr'? Find the referred item
            relationship = self
            for part in relattr.split('.'):
                if relationship is None:
                    return
                relationship = getattr(relationship, part)
        else:
            relationship = getattr(self, relattr)
        return relationship

    def actors_with(self, roles, with_role=False):
        """
        Return actors who have the specified roles on this object, as an iterator.

        Uses:
        1. ``__roles__[role]['granted_by']``
        2. ``__roles__[role]['granted_via']``

        Subclasses of :class:`RoleMixin` that have custom role granting logic in
        :meth:`roles_for` must provide a matching :meth:`actors_with` implementation.

        :param set roles: Iterable specifying roles to find actors with. May be an
            ordered type if ordering is important
        :param bool with_role: If True, yields a tuple of the actor and the role they
            were found with. The actor may have more roles, but only the first match
            is returned
        """
        if not is_collection(roles):
            raise ValueError("`roles` parameter must be a set")

        # Don't yield the same actor twice. Use a set to keep track of what has already
        # been returned
        actor_ids = set()

        def is_new(actor):
            if not actor:
                return False
            # Use identity_key, NOT identity:
            # identity_key is a tuple of (cls, id, token), while identity is just id.
            # identity_key will be None for transient objects, so use the object
            # itself as a backup identifier. More at:
            # <https://docs.sqlalchemy.org/en/13/orm/mapping_api.html
            # #sqlalchemy.orm.util.identity_key>
            aid = inspect(actor).identity_key or actor
            if aid not in actor_ids:
                actor_ids.add(aid)
                return True
            return False

        for role in roles:
            # Scan granted_by declarations
            for relattr in self.__roles__.get(role, {}).get('granted_by', []):
                relationship = getattr(self, relattr)
                if isinstance(relationship, (AppenderMixin, Query, abc.Iterable)):
                    for actor in relationship:
                        if is_new(actor):
                            yield (actor, role) if with_role else actor
                elif is_new(relationship):
                    yield (relationship, role) if with_role else relationship
            # Scan granted_via declarations
            for relattr, actor_attr in (
                self.__roles__.get(role, {}).get('granted_via', {}).items()
            ):
                reverse_offer_map = self.__relationship_reversed_role_offer_map__.get(
                    relattr
                )
                relationship = self._get_relationship(relattr)
                # What kind of relationship is this?
                # 1. It's a collection of some sort
                # 2. It's scalar item (either the 1 side of 1:n, or a property)
                if isinstance(relationship, (AppenderMixin, Query, abc.Iterable)):
                    iterable = relationship
                else:
                    iterable = [relationship]
                for obj in iterable:
                    if obj is not None:
                        # What kind of object is this related item?
                        # 1. Declaration said it has an actor attribute
                        if actor_attr:
                            # 1a. Does this have offered_roles? Re-confirm it actually
                            #     offers the role we're looking for
                            if isinstance(obj, RoleGrantABC):
                                # Has the dev asked for role remapping? Find the correct
                                # role name to check for
                                if (
                                    reverse_offer_map is None
                                    and role in obj.offered_roles
                                ) or (
                                    reverse_offer_map is not None
                                    and role in reverse_offer_map
                                    and reverse_offer_map[role].intersection(
                                        obj.offered_roles
                                    )
                                ):
                                    actor = getattr(
                                        obj,
                                        actor_attr.key
                                        if isinstance(actor_attr, QueryableAttribute)
                                        else actor_attr,
                                    )
                                    if is_new(actor):
                                        yield (actor, role) if with_role else actor
                            # 1b. Doesn't have offered_roles? Accept it as is
                            else:
                                actor = getattr(
                                    obj,
                                    actor_attr.key
                                    if isinstance(actor_attr, QueryableAttribute)
                                    else actor_attr,
                                )
                                if is_new(actor):
                                    yield (actor, role) if with_role else actor
                        # 2. No actor attribute? If it's a RoleMixin, we can call its
                        #    actors_with method and pass on whatever we get
                        elif isinstance(obj, RoleMixin):
                            # Once again, if roles are remapped, use the correct role
                            # name for this relationship
                            rel_roles = (
                                {role}
                                if reverse_offer_map is None
                                else reverse_offer_map.get(role)
                            )
                            if rel_roles:
                                for actor in obj.actors_with(rel_roles):
                                    if is_new(actor):
                                        yield (actor, role) if with_role else actor
                        # 3. No actor attribute and it's not a RoleMixin. This must be
                        #    an error
                        else:
                            raise TypeError("Unknown type of related object", obj)

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
        will be rendered as an empty dict.
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

    if '__relationship_role_offer_map__' not in cls.__dict__:
        cls.__relationship_role_offer_map__ = deepcopy(
            cls.__relationship_role_offer_map__
        )
    if '__relationship_reversed_role_offer_map__' not in cls.__dict__:
        cls.__relationship_reversed_role_offer_map__ = deepcopy(
            cls.__relationship_reversed_role_offer_map__
        )

    if '__datasets__' not in cls.__dict__:
        cls.__datasets__ = deepcopy(cls.__datasets__)

    # An attribute may be defined more than once in base classes. Only handle the first
    processed = set()

    # Loop through all attributes in this and base classes, looking for role annotations
    for base in cls.__mro__:
        for name, attr in base.__dict__.items():
            if name in processed or name.startswith('__'):
                continue

            while isinstance(attr, QueryableAttribute) and isinstance(
                getattr(attr, 'original_property', None), SynonymProperty
            ):
                # If we have a synonym, replace the attr with the referred attr, but
                # process it under the synonym name
                attr = getattr(cls, attr.original_property.name)

            if isinstance(attr, abc.Hashable) and attr in __cache__:
                data = __cache__[attr]
            elif isinstance(
                attr, (QueryableAttribute, RelationshipProperty, MapperProperty)
            ):
                if attr.property in __cache__:
                    data = __cache__[attr.property]
                elif '_coaster_roles' in attr.info:
                    data = attr.info['_coaster_roles']
                elif hasattr(attr.property, '_coaster_roles'):
                    data = getattr(attr.property, '_coaster_roles')
                else:
                    data = None
            elif hasattr(attr, '_coaster_roles'):
                data = attr._coaster_roles
            else:
                data = None
            if data is not None:
                for role in data.get('call', ()):
                    cls.__roles__.setdefault(role, {}).setdefault('call', set()).add(
                        name
                    )
                for role in data.get('read', ()):
                    cls.__roles__.setdefault(role, {}).setdefault('read', set()).add(
                        name
                    )
                for role in data.get('write', ()):
                    cls.__roles__.setdefault(role, {}).setdefault('write', set()).add(
                        name
                    )
                for role in data.get('grants', ()):
                    granted_by = cls.__roles__.setdefault(role, {}).setdefault(
                        'granted_by', []  # List as it needs to be ordered
                    )
                    if name not in granted_by:
                        granted_by.append(name)
                for actor_attr, roles in data.get('grants_via', {}).items():
                    if isinstance(roles, dict):
                        offer_map = {
                            k: {v} if isinstance(v, str) else set(v)
                            for k, v in roles.items()
                        }
                        reverse_offer_map = {}
                        for lhs, rhs in offer_map.items():
                            for role in rhs:
                                reverse_offer_map.setdefault(role, set()).add(lhs)
                        roles = set(reverse_offer_map.keys())
                    elif isinstance(roles, str):
                        raise TypeError(
                            "grants_via declaration {{{actor_attr!r}: {roles!r}}} on"
                            " {cls}.{name} is using a string but needs to be a set or"
                            " dict".format(
                                actor_attr=actor_attr,
                                roles=roles,
                                cls=cls.__name__,
                                name=name,
                            )
                        )
                    else:
                        offer_map = None
                        reverse_offer_map = None
                    if actor_attr and isinstance(actor_attr, str) and '.' in actor_attr:
                        parts = actor_attr.split('.')
                        dotted_name = '.'.join([name] + parts[:-1])
                        actor_attr = parts[-1]
                    else:
                        dotted_name = name
                    cls.__relationship_role_offer_map__[dotted_name] = offer_map
                    cls.__relationship_reversed_role_offer_map__[
                        dotted_name
                    ] = reverse_offer_map
                    for role in roles:
                        granted_via = cls.__roles__.setdefault(role, {}).setdefault(
                            'granted_via', {}
                        )
                        if dotted_name not in granted_via:
                            granted_via[dotted_name] = actor_attr
                for dataset in data.get('datasets', ()):
                    cls.__datasets__.setdefault(dataset, set()).add(name)
                processed.add(name)
