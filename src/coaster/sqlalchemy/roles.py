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
    from sqlalchemy.orm import declarative_mixin

    app = Flask(__name__)
    db = SQLAlchemy(app)

    @declarative_mixin
    class ColumnMixin:
        '''
        Mixin class that offers some columns to the RoleModel class below,
        demonstrating two ways to use `with_roles`.
        '''
        @with_roles(rw={'owner'})
        def mixed_in1(cls) -> Mapped[str]:
            return sa.orm.mapped_column(sa.Unicode(250))

        @declared_attr
        def mixed_in2(cls) -> Mapped[str]:
            return with_roles(sa.orm.mapped_column(sa.Unicode(250)), rw={'owner'})


    class RoleModel(ColumnMixin, RoleMixin, Model):
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

        id: Mapped[int] = sa.orm.mapped_column(sa.Integer, primary_key=True)
        name: Mapped[str] = with_roles(  # Specify read+write access
            sa.orm.mapped_column(sa.Unicode(250)),
            rw={'owner'}
        )

        user_id: Mapped[int] = sa.orm.mapped_column(
            sa.ForeignKey('user.id'),
            nullable=False
        )
        user: Mapped[User] = with_roles(
            relationship(User),
            grants={'owner'},  # Use `grants` here or `granted_by` in `__roles__`
            )

        # `with_roles` can also be called later. This is required for
        # properties, where roles must be assigned after the property is
        # fully described:

        _title: Mapped[str] = sa.orm.mapped_column('title', sa.Unicode(250))

        @property
        def title(self) -> str:
            return self._title

        @title.setter
        def title(self, value: str) -> None:
            self._title = value

        # This grants 'owner' and 'editor' write but not read access
        title = with_roles(title, write={'owner', 'editor'})

        # `with_roles` can be used as a decorator on methods, in which case
        # access is controlled with the 'call' action.

        @with_roles(call={'all'})
        def hello(self) -> str:
            return "Hello!"

        # `RoleMixin` will grant roles by examining relationships specified in the
        # `granted_by` list under each role in `__roles__`. The `actor` parameter
        # to `roles_for` must be present in the relationship. You can augment this
        # by providing a custom `roles_for` method:

        def roles_for(
            self, actor: Optional[User] = None, anchors: Sequence = ()
        ) -> LazyRoleSet:
            # Calling super gives us a LazyRoleSet with the standard roles
            # and with lazy evaluation of of other roles from `granted_by`
            roles = super().roles_for(actor, anchors)

            # We can manually add a role to override lazy evaluation
            if 'owner-secret' in anchors:
                roles.add('owner')
            return roles
"""

from __future__ import annotations

import dataclasses
import typing as t
import typing_extensions as te
from abc import ABCMeta, abstractmethod
from collections import abc
from copy import deepcopy
from itertools import chain
from typing import cast, overload

import sqlalchemy as sa
from flask import g
from sqlalchemy import event, select
from sqlalchemy.ext.orderinglist import OrderingList
from sqlalchemy.orm import (
    ColumnProperty,
    KeyFuncDict,
    MappedColumn,
    MapperProperty,
    Query as QueryBase,
    RelationshipProperty,
    SynonymProperty,
    declarative_mixin,
)
from sqlalchemy.orm.attributes import QueryableAttribute
from sqlalchemy.orm.collections import (
    InstrumentedDict,
    InstrumentedList,
    InstrumentedSet,
)
from sqlalchemy.schema import SchemaItem

from ..auth import current_auth
from ..utils import InspectableSet, is_collection, nary_op
from .functions import idfilters
from .model import AppenderQuery

__all__ = [
    'RoleGrantABC',
    'LazyRoleSet',
    'RoleAccessProxy',
    'DynamicAssociationProxy',
    'RoleMixin',
    'with_roles',
]

# Global dictionary for temporary storage of roles until the mapper_configured events
__cache__: t.Dict[t.Any, WithRoles] = {}


#: Mapping of a role in first object to one or more roles in second object
#: (for parent->child role mappings)
RoleOfferMap: te.TypeAlias = t.Dict[str, t.Set[str]]
#: A relationship to an actor can be specified via the name of the attribute, or
#: directly as the relationship object
ActorAttrType: te.TypeAlias = t.Union[str, QueryableAttribute]
# FIXME: Drop support for non-str actor attrs as the implementation is unreadable.
# The model should supply a property or virtual set (like DynamicAssociationProxy)
# pointing directly at the attr

RoleMixinType = t.TypeVar('RoleMixinType', bound='RoleMixin')
_T = t.TypeVar('_T')
_V = t.TypeVar('_V')


class RoleAttrs(te.TypedDict, total=False):
    """Type definition for values in :attr:`RoleMixin.__roles__`."""

    rw: t.Set[str]
    read: t.Set[str]
    write: t.Set[str]
    call: t.Set[str]
    grants: t.Set[str]
    granted_by: t.List[str]
    granted_via: t.Dict[str, t.Optional[ActorAttrType]]


@dataclasses.dataclass
class WithRoles:
    """Role annotations for an attribute."""

    read: t.Set[str] = dataclasses.field(default_factory=set)
    write: t.Set[str] = dataclasses.field(default_factory=set)
    call: t.Set[str] = dataclasses.field(default_factory=set)
    grants: t.Set[str] = dataclasses.field(default_factory=set)
    grants_via: t.Dict[
        t.Optional[ActorAttrType], t.Union[t.Set[str], t.Dict[str, str], RoleOfferMap]
    ] = dataclasses.field(default_factory=dict)
    datasets: t.Set[str] = dataclasses.field(default_factory=set)
    rw: dataclasses.InitVar[t.Optional[t.Set[str]]] = None

    def __post_init__(self, rw: t.Optional[t.Set[str]] = None) -> None:
        if rw is not None:
            self.read.update(rw)
            self.write.update(rw)

    def __or__(self, other: WithRoles) -> WithRoles:
        """Merge two instances of WithRoles into a new instance."""
        return WithRoles(
            read=self.read | other.read,
            write=self.write | other.write,
            call=self.call | other.call,
            grants=self.grants | other.grants,
            grants_via={**self.grants_via, **other.grants_via},
            datasets=self.datasets | other.datasets,
        )


def _attrs_equal(
    lhs: t.Optional[ActorAttrType], rhs: t.Optional[ActorAttrType]
) -> bool:
    """
    Compare two strings or two attributes.

    QueryableAttributes can't be compared with `==` to confirm both are same object.
    But strings can't be compared with `is` to confirm they are the same string.
    We have to change the operator based on types being compared. The data sources are
    typed as Optional, so we also accept that and regard None as not matching.
    """
    if lhs is None or rhs is None:
        return False
    if isinstance(lhs, str) and isinstance(rhs, str):
        return lhs == rhs
    return lhs is rhs


def _actor_in_relationship(actor: t.Any, relationship: t.Any) -> bool:
    """Test whether the given actor is present in the given attribute."""
    if actor == relationship:
        return True
    if isinstance(relationship, QueryBase):
        filters = idfilters(actor)
        if filters is not None:
            return (
                relationship.session.scalar(
                    select(relationship.filter(*filters).exists())
                )
                or False  # The or clause is needed as .scalar is typed Optional
            )
        # If actor does not have an identity yet, check in the session's collection
        return actor in relationship
    if isinstance(relationship, abc.Container):
        # Regular Python container
        return actor in relationship
    return False


def _roles_via_relationship(
    actor: t.Any,
    relationship: t.Any,
    actor_attr: t.Optional[ActorAttrType],
    wanted_roles: t.Set[str],
    offer_map: t.Optional[RoleOfferMap],
) -> t.Set[str]:
    """Find roles granted via a relationship."""
    relobj = None  # Role-granting object found via the relationship

    # If there is no actor_attr, check if the relationship is a RoleMixin and call
    # roles_for to get offered roles, then remap using the offer map, subsetting the
    # offer map to the wanted roles. The offer map may be larger than currently wanted,
    # and lookups in the offered roles could be expensive.
    if actor_attr is None:
        if isinstance(relationship, RoleMixin):
            offered_roles: t.Union[t.Set[str], LazyRoleSet]
            # TODO: Cache this as we'll get a different LazyRoleSet each time
            offered_roles = relationship.roles_for(actor)
            if offer_map is not None:
                offer_map_subset = {
                    original_role
                    for original_role, remapped_roles in offer_map.items()
                    if remapped_roles & wanted_roles
                }
                return set(
                    chain.from_iterable(
                        offer_map[role] for role in offered_roles & offer_map_subset
                    )
                )
            return offered_roles & wanted_roles
        raise TypeError(
            f"{relationship!r} is not a RoleMixin and no actor attribute was specified"
        )

    # We have a relationship and an actor attribute on the relationship. If the
    # relationship is a collection, find the item in it that relates to the actor.

    # TODO: Support WriteOnlyCollection
    if isinstance(relationship, QueryBase):
        # Query-like relationship. Run a query. It is possible to have multiple matches
        # for the actor, so use .first()
        # TODO: Consider retrieving all and consolidating roles from across them in case
        # the objects are RoleGrantABC. This is not a current requirement and so is not
        # currently supported; using the .first() object is sufficient
        if isinstance(actor_attr, QueryableAttribute):
            relobj = relationship.filter(actor_attr == actor).first()
        else:
            relobj = relationship.filter_by(**{actor_attr: actor}).first()
    elif isinstance(actor_attr, str):
        if isinstance(relationship, abc.Iterable):
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
        return set()

    # We have a related object. Get roles from it
    if isinstance(relobj, RoleGrantABC):
        # If this object grants roles, get them
        offered_roles = relobj.offered_roles
        if offer_map:
            # If we have an offer_map, remap the roles and only keep the ones
            # specified in the map
            offer_map_subset = {
                original_role
                for original_role, remapped_roles in offer_map.items()
                if remapped_roles & wanted_roles
            }
            return set(
                chain.from_iterable(
                    offer_map[role] for role in offered_roles & offer_map_subset
                )
            )
        # Without an offer map, return the subset of offered roles and wanted roles
        return offered_roles & wanted_roles
    # Not a role granting object. Implies that the default roles are granted
    # by its very existence.
    return wanted_roles


class RoleGrantABC(metaclass=ABCMeta):
    """Base class for an object that grants roles to a subject."""

    @property
    @abstractmethod
    def offered_roles(self) -> t.Set[str]:  # pragma: no cover
        """Roles offered by this object."""
        return set()

    @classmethod
    def __subclasshook__(cls, c: t.Type) -> bool:
        """Check if a class implements the RoleGrantABC protocol."""
        if cls is RoleGrantABC:
            if any('offered_roles' in b.__dict__ for b in c.__mro__):
                return True
            return False
        return NotImplemented  # pragma: no cover


class LazyRoleSet(abc.MutableSet):
    """Set that provides lazy evaluations for whether a role is present."""

    __slots__ = (
        'obj',
        'actor',
        '_present',
        '_not_present',
        '_scanned_granted_by',
    )

    def __init__(
        self, obj: RoleMixin, actor: t.Any, initial: t.Iterable[str] = ()
    ) -> None:
        self.obj = obj
        self.actor = actor
        #: Roles that the actor has (make a copy of initial set as it will be mutated)
        self._present: t.Set[str] = set(initial)
        #: Roles the actor does not have
        self._not_present: t.Set[str] = set()
        # Relationships that have been scanned already
        self._scanned_granted_by: t.Set[str] = set()  # Contains relattr

    def __repr__(self) -> str:  # pragma: no cover
        return f'LazyRoleSet({self.obj!r}, {self.actor!r}, {self._present!r})'

    def _from_iterable(  # pylint: disable=arguments-differ
        self, it: t.Iterator[str]
    ) -> LazyRoleSet:
        """Make a copy, as required by the `MutableSet` base class."""
        # MutableSet defines this as a classmethod. We need an instance method to get
        # self.obj and self.actor. Pylint doesn't like it and must be silenced
        return LazyRoleSet(self.obj, self.actor, it)

    def _role_is_present(self, role: str) -> bool:
        """Test whether a role has been granted to the bound actor."""
        if role in self._present:
            return True
        if role in self._not_present:
            return False
        if self.actor is not None:
            if role not in self.obj.__roles__:
                self._not_present.add(role)
                return False

            # `granted_via` says a role may be granted by a secondary object that sits
            # in a relationship between the current object and the actor. The secondary
            # could be a direct attribute of the current object, or could be inside a
            # list or query relationship. `_roles_via_relationship` will check.
            # The related object may grant roles in one of three ways:
            # 1. By its mere existence (default).
            # 2. By offering roles via an `offered_roles` property (see `RoleGrantABC`).
            # 3. By being a `RoleMixin` instance that has a `roles_for` method.

            # pylint: disable=protected-access
            for relattr, actor_attr in (
                self.obj.__roles__[role].get('granted_via', {}).items()
            ):
                offer_map = self.obj.__relationship_role_offer_map__.get(relattr)
                relationship = self.obj._get_relationship(relattr)
                if relationship is not None:
                    possibly_granted_roles = {role}
                    # Optimization: does the same relationship grant other roles via
                    # the same non-None `actor_attr`? Gather those roles and check
                    # all of them together. However, we will use a single role offer
                    # map and not consult the one specified on the other roles. They
                    # are expected to be identical. This is guaranteed if the offer
                    # map was specified using `with_roles(grants_via=)` but not if
                    # specified directly in `__roles__[role]['granted_via']`. If
                    # `actor_attr` is None, the relationship must be a `RoleMixin`
                    # instance that implements `roles_for` and returns a
                    # `LazyRoleSet` that does expensive lookups. That's no longer an
                    # optimization and the greedy grab should not be attempted.
                    if actor_attr is not None:
                        for arole, actions in self.obj.__roles__.items():
                            if (
                                arole != role
                                and 'granted_via' in actions
                                and relattr in actions['granted_via']
                                and _attrs_equal(
                                    actions['granted_via'][relattr], actor_attr
                                )
                            ):
                                possibly_granted_roles.add(arole)

                    granted_roles = _roles_via_relationship(
                        self.actor,
                        relationship,
                        actor_attr,
                        possibly_granted_roles,
                        offer_map,
                    )
                    self._present.update(granted_roles)
                    if role in granted_roles:
                        return True
            # granted_by says a role is granted by the actor being present in a
            # relationship
            for relattr in self.obj.__roles__[role].get('granted_by', ()):
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

    def _contents(self) -> t.Set[str]:
        """Return all available roles."""
        # Populate cache (TODO: cache this step to avoid repeat checks)
        for role in self.obj.__roles__:
            self._role_is_present(role)
        # self._present may have roles that are not specified in self.obj.__roles__,
        # notably implicit roles like `all` and `auth`. Therefore we must return the
        # cache instead of capturing available roles in the loop above
        return self._present

    def __contains__(self, key: t.Any) -> bool:
        return self._role_is_present(key)

    def __iter__(self) -> t.Iterator[str]:
        return iter(self._contents())

    def __len__(self) -> int:
        return len(self._contents())

    def __bool__(self) -> bool:
        # Make bool() faster than len() by using the cache first
        return (
            True
            if bool(self._present)
            else any(self._role_is_present(role) for role in self.obj.__roles__)
        )

    def __eq__(self, other: t.Any) -> bool:
        if isinstance(other, LazyRoleSet):
            return self.obj == other.obj and self.actor == other.actor
        return self._contents() == other

    def __ne__(self, other: t.Any) -> bool:
        return not self.__eq__(other)

    def __and__(self, other: t.Iterable[str]) -> t.Set[str]:
        """Faster implementation that avoids lazy lookups where not needed."""
        return {role for role in other if self._role_is_present(role)}

    def add(self, value: str) -> None:
        """Add role `value` to the set."""
        self._present.add(value)
        self._not_present.discard(value)

    def discard(self, value: str) -> None:
        """Remove role `value` from the set if it is present."""
        self._present.discard(value)
        self._not_present.add(value)

    def has_any(self, roles: t.Iterable[str]) -> bool:
        """
        Check if any of the given roles is present in the set.

        Convenience method, equivalent of evaluating using either of these approaches:

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

    def copy(self) -> LazyRoleSet:
        """Return a shallow copy of the :class:`LazyRoleSet`."""
        result = LazyRoleSet(self.obj, self.actor, self._present)
        result._not_present = set(self._not_present)  # pylint: disable=protected-access
        return result

    # Set operators take a single `other` parameter while these methods
    # are required to take multiple `others` to be API-compatible with sets.
    # `nary_op` converts a binary operator to an n-ary operator
    issubset = nary_op(abc.MutableSet.__le__)
    issuperset = nary_op(abc.MutableSet.__ge__)
    union = nary_op(abc.MutableSet.__or__)
    intersection = nary_op(__and__)
    difference = nary_op(abc.MutableSet.__sub__)
    symmetric_difference = nary_op(abc.MutableSet.__xor__)
    update = nary_op(abc.MutableSet.__ior__)
    intersection_update = nary_op(abc.MutableSet.__iand__)
    difference_update = nary_op(abc.MutableSet.__isub__)
    symmetric_difference_update = nary_op(abc.MutableSet.__ixor__)


class DynamicAssociationProxy(t.Generic[_V]):
    """
    Association proxy for dynamic relationships.

    Use this instead of SQLAlchemy's `association_proxy` when the underlying
    relationship uses `lazy='dynamic'`. This is not compatible with SQLAlchemy 2.0's
    recommended `lazy='write_only'`.

    Usage::

        # Assuming a relationship like this:
        Document.child_relationship = relationship(ChildDocument, lazy='dynamic')

        # Proxy to an attribute on the target of the relationship (specifying the type):
        Document.child_attributes = DynamicAssociationProxy[attribute_type](
            'child_relationship', 'attribute')

    This proxy does not provide access to the query capabilities of dynamic
    relationships. It merely optimizes for containment queries. A query like this::

        document.child_relationship.filter_by(attribute=value).exists()

    Can be reduced to this::

        value in document.child_attributes

    The proxy can also be iterated, and the return type is set to the generic type
    specified in the constructor::

        list(document.child_attributes)  # type: list[attribute_type]

    :param str rel: Relationship name (must use ``lazy='dynamic'``)
    :param str attr: Attribute on the target of the relationship
    """

    __slots__ = ('rel', 'attr')

    def __init__(self, rel: str, attr: str) -> None:
        self.rel = rel
        self.attr = attr

    def __repr__(self) -> str:
        return f'DynamicAssociationProxy({self.rel!r}, {self.attr!r})'

    @overload
    def __get__(self, obj: None, cls: t.Type) -> te.Self:
        ...

    @overload
    def __get__(
        self, obj: _T, cls: t.Type[_T]
    ) -> DynamicAssociationProxyWrapper[_V, _T]:
        ...

    def __get__(
        self, obj: t.Optional[_T], cls: t.Type[_T]
    ) -> t.Union[te.Self, DynamicAssociationProxyWrapper[_V, _T]]:
        if obj is None:
            return self
        return DynamicAssociationProxyWrapper(obj, self.rel, self.attr)


class DynamicAssociationProxyWrapper(abc.Set, t.Generic[_V, _T]):
    """:class:`DynamicAssociationProxy` wrapped around an instance."""

    __slots__ = ('obj', 'rel', 'relattr', 'attr')
    relattr: AppenderQuery

    def __init__(
        self,
        obj: _T,
        rel: str,
        attr: str,
    ) -> None:
        self.obj = obj
        self.rel = rel
        self.relattr = getattr(obj, rel)
        self.attr = attr

    def __repr__(self) -> str:
        return (
            f'DynamicAssociationProxyWrapper({self.obj!r}, {self.rel!r}, {self.attr!r})'
        )

    def __contains__(self, value: t.Any) -> bool:
        relattr = self.relattr
        if t.TYPE_CHECKING:
            assert relattr.session is not None  # nosec B101
        return relattr.session.query(
            relattr.filter_by(**{self.attr: value}).exists()
        ).scalar()

    def __iter__(self) -> t.Iterator[_V]:
        for obj in self.relattr:
            yield getattr(obj, self.attr)

    def __len__(self) -> int:
        return self.relattr.count()

    def __bool__(self) -> bool:
        relattr = self.relattr
        if t.TYPE_CHECKING:
            assert relattr.session is not None  # nosec B101
        return relattr.session.query(relattr.exists()).scalar()

    def __eq__(self, other: t.Any) -> bool:
        return (
            isinstance(other, DynamicAssociationProxyWrapper)
            and self.obj == other.obj
            and self.rel == other.rel
            and self.attr == other.attr
        )

    def __ne__(self, other: t.Any) -> bool:
        # This method is required as abc.Set provides a less efficient version
        return not self.__eq__(other)


class RoleAccessProxy(abc.Mapping, t.Generic[RoleMixinType]):
    """
    Provide restricted access to a wrapped object based on available roles.

    RoleAccessProxy consults the ``__roles__`` dictionary on the object to determine
    which roles have read, write or call access, and the ``__datasets__`` dictionary
    to limit enumeration when casting to a Python dictionary or JSON rendering.

    RoleAccessProxy offers both attribute and dictionary access to contents, except
    when an attribute is specified to have ``call`` but not ``read`` access, in which
    case it is only available via attribute access.

    Example::

        proxy = RoleAccessProxy(obj, roles={'writer'})
        proxy.attr1
        proxy.attr1 = 'new value'
        proxy['attr2'] = 'new value'
        dict(proxy)

    The :class:`RoleAccessProxy` wrapper is typically constructed from the target
    object via :meth:`~RoleMixin.access_for` (from :class:`RoleMixin`).

    :param obj: The object that should be wrapped with the proxy
    :param roles: A set of roles to determine what attributes are accessible
    :param actor: The actor this proxy has been constructed for
    :param anchors: The anchors this proxy has been constructed with
    :param datasets: Datasets to limit attribute enumeration to

    The `actor` and `anchors` parameters are not used by the proxy, but are used to
    construct proxies for objects accessed via relationships.
    """

    __slots__ = (
        '_obj',
        'current_roles',
        '_roles',
        '_actor',
        '_anchors',
        '_datasets',
        '_dataset_attrs',
        '_call',
        '_read',
        '_write',
        '_no_call',
        '_no_read',
        '_no_write',
        '_all_read_cache',
    )
    _obj: RoleMixinType
    current_roles: InspectableSet[t.Union[LazyRoleSet, t.Set[str]]]
    _roles: t.Union[LazyRoleSet, t.Set[str]]
    _actor: t.Any
    _anchors: t.Sequence[t.Any]
    _datasets: t.Optional[t.Sequence[str]]
    _dataset_attrs: t.Optional[t.Set[str]]
    _call: t.Set[str]
    _read: t.Set[str]
    _write: t.Set[str]
    _no_call: t.Set[str]
    _no_read: t.Set[str]
    _no_write: t.Set[str]
    _all_read_cache: t.Optional[t.Set[str]]

    @property  # type: ignore[override]
    def __class__(self) -> t.Type[RoleMixinType]:
        return self._obj.__class__

    @__class__.setter
    def __class__(self, value: t.Any) -> t.NoReturn:  # noqa: F811
        raise TypeError("__class__ cannot be set")

    def __init__(
        self,
        obj: RoleMixinType,
        roles: t.Union[LazyRoleSet, t.Set[str]],
        actor: t.Optional[t.Any],
        anchors: t.Sequence[t.Any],
        datasets: t.Optional[t.Sequence[str]],
    ) -> None:
        object.__setattr__(self, '_obj', obj)
        object.__setattr__(self, 'current_roles', InspectableSet(roles))
        object.__setattr__(self, '_roles', roles)
        object.__setattr__(self, '_actor', actor)
        object.__setattr__(self, '_anchors', anchors)
        if datasets is None:
            dataset_attrs = None
            object.__setattr__(self, '_datasets', None)
        else:
            if datasets:
                try:
                    dataset_attrs = set(obj.__datasets__[datasets[0]])
                except KeyError as exc:
                    raise KeyError(
                        f"Object of type {type(obj)!r} is missing dataset {datasets[0]}"
                    ) from exc
            else:
                # Got an empty list, so turn off enumeration
                dataset_attrs = set()
            object.__setattr__(self, '_datasets', datasets[1:])
        object.__setattr__(self, '_dataset_attrs', dataset_attrs)

        object.__setattr__(self, '_call', set())
        object.__setattr__(self, '_read', set())
        object.__setattr__(self, '_write', set())
        object.__setattr__(self, '_no_call', set())
        object.__setattr__(self, '_no_read', set())
        object.__setattr__(self, '_no_write', set())
        object.__setattr__(self, '_all_read_cache', None)

    def __repr__(self) -> str:
        return f'RoleAccessProxy(obj={self._obj!r}, roles={self.current_roles!r})'

    def current_access(self, datasets: t.Optional[t.Sequence[str]] = None) -> te.Self:
        """Mimic :meth:`RoleMixin.current_access`, but simply return self."""
        return self

    def __get_processed_attr(self, name: str) -> t.Any:
        attr = getattr(self._obj, name)
        # TODO: Implement 'write' permission control for collection relationships.
        # A proper take will require custom dict and list subclasses, similar to the
        # role access proxy itself.
        if type(attr) is RoleAccessProxy:  # pylint: disable=unidiomatic-typecheck
            return attr
        if isinstance(attr, RoleMixin):
            return attr.access_for(
                actor=self._actor, anchors=self._anchors, datasets=self._datasets
            )
        if isinstance(attr, (InstrumentedDict, KeyFuncDict)):
            return {
                k: v.access_for(
                    actor=self._actor, anchors=self._anchors, datasets=self._datasets
                )
                for k, v in attr.items()
            }
        if isinstance(
            attr,
            (InstrumentedList, InstrumentedSet, OrderingList, QueryBase),
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

    def __attr_available(
        self, attr: str, action: te.Literal['call', 'read', 'write']
    ) -> bool:
        """Check for attr availability using a cache."""
        if action == 'read':
            present, absent = self._read, self._no_read
        elif action == 'call':
            present, absent = self._call, self._no_call
        elif action == 'write':
            present, absent = self._write, self._no_write

        if attr in present:
            return True
        if attr in absent:
            return False
        # Not cached. Check for roles that grant access, then check for role
        # availability
        granting_roles = {
            role
            for role, roledict in self._obj.__roles__.items()
            if attr in roledict.get(action, ())
        }
        if not granting_roles:
            # No role grants access to this attribute for the given action
            absent.add(attr)
            return False
        if isinstance(self._roles, LazyRoleSet):
            # If we have a LazyRoleSet, use its `has_any` method for lazy testing
            # (test for overlap in present roles, then test for grant of other roles)
            if self._roles.has_any(granting_roles):
                present.add(attr)
                return True
        elif self._roles & granting_roles:
            present.add(attr)
            return True
        absent.add(attr)
        return False

    @property
    def _all_read(self) -> t.Set[str]:
        """All readable attributes."""
        if self._all_read_cache is not None:
            return self._all_read_cache
        all_read_attrs = {
            attr
            for roledict in self._obj.__roles__.values()
            for attr in roledict.get('read', ())
        }
        if self._dataset_attrs is not None:
            # If a dataset is specified, drop all attrs that don't appear in the dataset
            all_read_attrs = all_read_attrs & self._dataset_attrs
        # Next, filter for attr availability
        available_read_attrs = {
            attr for attr in all_read_attrs if self.__attr_available(attr, 'read')
        }
        # Save to cache and return
        object.__setattr__(self, '_all_read_cache', available_read_attrs)
        return available_read_attrs

    def __getattr__(self, attr: str) -> t.Any:
        # See also __getitem__, which doesn't consult _call
        if self.__attr_available(attr, 'read') or self.__attr_available(attr, 'call'):
            return self.__get_processed_attr(attr)
        raise AttributeError(
            f"{self._obj.__class__.__qualname__}.{attr};"
            f" current roles {self.current_roles!r}"
        )

    def __setattr__(self, attr: str, value: t.Any) -> None:
        # See also __setitem__
        if self.__attr_available(attr, 'write'):
            return setattr(self._obj, attr, value)
        raise AttributeError(
            f"{self._obj.__class__.__qualname__}.{attr};"
            f" current roles {self.current_roles!r}"
        )

    def __getitem__(self, key: str) -> t.Any:
        # See also __getattr__, which also looks in _call
        if self.__attr_available(key, 'read'):
            return self.__get_processed_attr(key)
        raise KeyError(
            f"{self._obj.__class__.__qualname__}.{key};"
            f" current roles {self.current_roles!r}"
        )

    def __len__(self) -> int:
        return len(self._all_read)

    def __contains__(self, key: t.Any) -> bool:
        return self.__attr_available(key, 'read') or self.__attr_available(key, 'call')

    def __setitem__(self, key: str, value: str) -> None:
        # See also __setattr__
        if self.__attr_available(key, 'write'):
            return setattr(self._obj, key, value)
        raise KeyError(
            f"{self._obj.__class__.__qualname__}.{key};"
            f" current roles {self.current_roles!r}"
        )

    def __iter__(self) -> t.Iterator[str]:
        yield from self._all_read

    def __json__(self) -> t.Dict[str, t.Any]:
        return dict(self)

    def __eq__(self, other: t.Any) -> bool:
        if other == self._obj:
            return True
        if (
            type(other) is RoleAccessProxy  # pylint: disable=unidiomatic-typecheck
            and other._obj == self._obj
        ):
            return True
        return super().__eq__(other)

    def __ne__(self, other: t.Any) -> bool:
        # Don't call __eq__ directly, it may return NotImplemented
        return not self == other

    def __bool__(self) -> bool:
        return bool(self._obj)


_DA = t.TypeVar('_DA')  # Decorated attr


@overload
def with_roles(
    *,
    rw: t.Optional[t.Set[str]] = None,
    call: t.Optional[t.Set[str]] = None,
    read: t.Optional[t.Set[str]] = None,
    write: t.Optional[t.Set[str]] = None,
    grants: t.Optional[t.Set[str]] = None,
    grants_via: t.Optional[
        t.Dict[
            t.Optional[ActorAttrType],
            t.Union[t.Set[str], t.Dict[str, str], t.Dict[str, t.Set[str]]],
        ]
    ] = None,
    datasets: t.Optional[t.Set[str]] = None,
) -> t.Callable[[_DA], _DA]:
    ...


@overload
def with_roles(
    __obj: _DA,
    /,
    rw: t.Optional[t.Set[str]] = None,
    call: t.Optional[t.Set[str]] = None,
    read: t.Optional[t.Set[str]] = None,
    write: t.Optional[t.Set[str]] = None,
    grants: t.Optional[t.Set[str]] = None,
    grants_via: t.Optional[
        t.Dict[
            t.Optional[ActorAttrType],
            t.Union[t.Set[str], t.Dict[str, str], t.Dict[str, t.Set[str]]],
        ]
    ] = None,
    datasets: t.Optional[t.Set[str]] = None,
) -> _DA:
    ...


def with_roles(
    __obj: t.Optional[_DA] = None,
    /,
    rw: t.Optional[t.Set[str]] = None,
    call: t.Optional[t.Set[str]] = None,
    read: t.Optional[t.Set[str]] = None,
    write: t.Optional[t.Set[str]] = None,
    grants: t.Optional[t.Set[str]] = None,
    grants_via: t.Optional[
        t.Dict[
            t.Optional[ActorAttrType],
            t.Union[t.Set[str], t.Dict[str, str], RoleOfferMap],
        ]
    ] = None,
    datasets: t.Optional[t.Set[str]] = None,
) -> t.Union[_DA, t.Callable[[_DA], _DA]]:
    """
    Define roles on an attribute and return the attribute.

    :func:`with_roles` can be used as a decorator or as a function. It creates
    annotations directly on the attribute, for later discovery by the
    :class:`RoleMixin` base class (during SQLAlchemy init) which transfers the
    annotations to the subclass's :attr:`~RoleMixin.__roles__` dictionary. Because of
    this dependency, :func:`with_roles` only works in :class:`RoleMixin` subclasses.

    Examples::

        id: Mapped[int] = sa.orm.mapped_column(sa.Integer, primary_key=True)
        with_roles(id, read={'all'})

        title: Mapped[str] = with_roles(sa.orm.mapped_column(sa.Unicode), read={'all'})

        @with_roles(read={'all'})
        @hybrid_property
        def url_id(self) -> str:
            return str(self.id)

    When used with properties, with_roles must always be applied after the
    property is fully described::

        @property
        def title(self) -> str:
            return self._title

        @title.setter
        def title(self, value: str) -> None:
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

        class RoleModel(Model):
            user_id: Mapped[int] = sa.orm.mapped_column(sa.ForeignKey('user.id'))
            user: Mapped[UserModel] = relationship(UserModel)

            document_id: Mapped[int] = sa.orm.mapped_column(sa.ForeignKey(
                'document.id'
            ))
            document: Mapped[DocumentModel] = relationship(DocumentModel)

        DocumentModel.rolemodels = with_roles(
            relationship(RoleModel), grants_via={'user': {'role1', 'role2'}}
        )

    In this example, a user gets roles 'role1' and 'role2' on DocumentModel via the
    secondary RoleModel. Grants are recorded in ``__roles__['role1']['granted_via']``
    and are honoured by the :class:`LazyRoleSet` used in :meth:`~RoleMixin.roles_for`.

    ``grants_via`` supports an additional advanced definition for when the role granting
    model has variable roles and offers them via a property named ``offered_roles``::

        class RoleModel(Model):
            user_id: Mapped[int] = sa.orm.mapped_column(sa.ForeignKey('user.id'))
            user: Mapped[UserModel] = relationship(UserModel)

            has_role1: Mapped[bool] = sa.orm.mapped_column(sa.Boolean)
            has_role2: Mapped[bool] = sa.orm.mapped_column(sa.Boolean)

            document_id: Mapped[int] = sa.orm.mapped_column(sa.ForeignKey(
                'document.id'
            ))
            document: Mapped[DocumentModel] = relationship(DocumentModel)

            @property
            def offered_roles(self):
                roles = set()
                if self.has_role1:
                    roles.add('role1')
                if self.has_role2:
                    roles.add('role2')
                return roles

        DocumentModel.rolemodels = with_roles(
            relationship(RoleModel),
            grants_via={'user': {
                'role1': 'renamed_role1,
                'role2': {'renamed_role2', 'also_role2'}
            }}
        )
    """

    def decorator(attr: _DA) -> _DA:
        if isinstance(attr, SynonymProperty):
            raise TypeError(
                "Synonyms cannot have roles as they acquire from the underlying entity"
            )
        data = WithRoles(
            rw=set(rw) if rw is not None else set(),
            call=set(call) if call is not None else set(),
            read=set(read) if read is not None else set(),
            write=set(write) if write is not None else set(),
            grants=set(grants) if grants is not None else set(),
            grants_via=dict(grants_via) if grants_via is not None else {},
            datasets=set(datasets) if datasets is not None else set(),
        )

        if attr in __cache__:
            raise TypeError("Duplicate use of with_roles for this attribute")
        __cache__[attr] = data
        if isinstance(attr, MappedColumn):
            if hasattr(attr.column, '_coaster_roles'):
                raise TypeError("Duplicate use of with_roles for this attribute")
            # pylint: disable=protected-access
            attr.column._coaster_roles = data  # type: ignore[attr-defined]
        elif isinstance(attr, (SchemaItem, ColumnProperty, MapperProperty)):
            if '_coaster_roles' in attr.info:
                raise TypeError("Duplicate use of with_roles for this attribute")
            attr.info['_coaster_roles'] = data
        else:
            try:
                if hasattr(attr, '_coaster_roles'):
                    raise TypeError("Duplicate use of with_roles for this attribute")
                # pylint: disable=protected-access
                attr._coaster_roles = data  # type: ignore[attr-defined]
                # If the attr has a restrictive __slots__, we'll get an attribute error.
                # Unfortunately, because of the way SQLAlchemy works by copying objects
                # into subclasses, the cache alone is not a reliable mechanism. We need
                # both
            except AttributeError:
                pass
        return attr

    if __obj is not None:
        if isinstance(__obj, (str, bytes, int, float, bool, tuple)):
            raise TypeError(
                f"with_roles needs an object as parameter, not {type(__obj)}"
            )
        return decorator(__obj)
    return decorator


@declarative_mixin
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
    __roles__: t.Dict[str, RoleAttrs] = {}
    # Datasets for limited access to attributes
    __datasets__: t.Dict[str, t.Set[str]] = {}
    # Datasets to use when rendering to JSON
    __json_datasets__: t.Sequence[str] = ()
    # Relationship role offer map (used by LazyRoleSet)
    __relationship_role_offer_map__: t.Dict[str, RoleOfferMap] = {}
    # Relationship reversed role offer map (used by actors_with)
    __relationship_reversed_role_offer_map__: t.Dict[str, RoleOfferMap] = {}

    def roles_for(
        self, actor: t.Optional[t.Any] = None, anchors: t.Sequence[t.Any] = ()
    ) -> LazyRoleSet:
        """
        Return roles available to the given ``actor`` or ``anchors`` on this object.

        The data type for both parameters are intentionally undefined here. Subclasses
        are free to define them in any way appropriate. Actors and anchors are assumed
        to be valid.

        The role ``all`` is always granted. If ``actor`` is specified, the role
        ``auth`` is granted. If not, ``anon`` is granted.

        Subclasses overriding :meth:`roles_for` must always call :func:`super` to
        ensure they receive a lazy role set that includes the standard roles and
        evaluates for declarative roles when they are first accessed. Recommended
        boilerplate::

            def roles_for(
                self, actor: t.Optional[User] = None, anchors: t.Sequence[t.Any] = ()
            ) -> LazyRoleSet:
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
    def current_roles(self) -> InspectableSet[LazyRoleSet]:
        """
        Roles currently available on this object.

        Uses :obj:`~coaster.auth.current_auth` to get the current actor, and returns an
        :class:`~coaster.utils.classes.InspectableSet`. Use in the view layer to
        inspect for a role being present:

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
        cache = getattr(g, '_coaster_role_cache', None)
        if cache is None:
            cache = {}
            g._coaster_role_cache = cache  # pylint: disable=protected-access
        cache_key = (self, current_auth.actor, current_auth.anchors)
        if cache_key not in cache:
            cache[cache_key] = InspectableSet(
                self.roles_for(actor=current_auth.actor, anchors=current_auth.anchors)
            )
        return cache[cache_key]

    def _get_relationship(self, relattr: str) -> t.Optional[t.Any]:
        if '.' in relattr:
            # Did we get a 'relationship.attr'? Find the referred item
            relationship: t.Any = self
            for part in relattr.split('.'):
                if relationship is None:
                    return None
                relationship = getattr(relationship, part)
        else:
            relationship = getattr(self, relattr)
        return relationship

    @overload
    def actors_with(
        self, roles: t.Iterable[str], with_role: te.Literal[False] = False
    ) -> t.Iterator[t.Any]:
        ...

    @overload
    def actors_with(
        self, roles: t.Iterable[str], with_role: te.Literal[True] = True
    ) -> t.Iterator[t.Tuple[t.Any, str]]:
        ...

    def actors_with(
        self, roles: t.Iterable[str], with_role: bool = False
    ) -> t.Iterator[t.Union[t.Any, t.Tuple[str, t.Any]]]:
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
            raise ValueError("`roles` parameter must be a list or set")

        # Don't yield the same actor twice. Use a set to keep track of what has already
        # been returned
        actor_ids = set()

        def is_new(actor: t.Optional[t.Any]) -> bool:
            if not actor:
                return False
            # Use identity_key, NOT identity:
            # identity_key is a tuple of (cls, id, token), while identity is just id.
            # identity_key will be None for transient objects, so use the object
            # itself as a backup identifier. More at:
            # <https://docs.sqlalchemy.org/en/13/orm/mapping_api.html
            # #sqlalchemy.orm.util.identity_key>
            aid = sa.inspect(actor).identity_key or actor
            if aid not in actor_ids:
                actor_ids.add(aid)
                return True
            return False

        for role in roles:
            # Scan granted_by declarations
            for relattr in self.__roles__.get(role, {}).get('granted_by', []):
                relationship = getattr(self, relattr)
                if isinstance(relationship, (QueryBase, abc.Iterable)):
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
                if isinstance(relationship, (QueryBase, abc.Iterable)):
                    iterable = relationship
                else:
                    iterable = [relationship]
                for obj in iterable:
                    if obj is not None:
                        # What kind of object is this related item?
                        # 1. Declaration said it has an actor attribute
                        if actor_attr is not None:
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

    def access_for(
        self,
        roles: t.Optional[t.Union[LazyRoleSet, t.Set[str]]] = None,
        actor: t.Optional[t.Any] = None,
        anchors: t.Sequence[t.Any] = (),
        datasets: t.Optional[t.Sequence[str]] = None,
    ) -> RoleAccessProxy:
        """
        Return an access control proxy for this instance.

        Read, write and call access will be limited based on the specified roles, or on
        the roles available to the specified actor and the given anchors.

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

    def current_access(
        self, datasets: t.Optional[t.Sequence[str]] = None
    ) -> RoleAccessProxy:
        """
        Return an access control proxy for this instance for the current actor.

        Calls :meth:`access_for` with :obj:`~coaster.auth.current_auth`.

        :param tuple datasets: Datasets to limit enumeration to
        """
        return self.access_for(
            actor=current_auth.actor, anchors=current_auth.anchors, datasets=datasets
        )

    def __json__(self) -> t.Dict[str, t.Any]:
        """Render to a JSON-compatible data structure."""
        return dict(self.current_access(self.__json_datasets__))


@event.listens_for(RoleMixin, 'mapper_configured', propagate=True)
def _configure_roles(_mapper: t.Any, cls: t.Type[RoleMixin]) -> None:
    """
    Configure roles on all models when configuring SQLAlchemy mappers.

    Run through attribute of the class looking for role decorations from
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
            # pylint: disable=protected-access
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
            elif isinstance(attr, MappedColumn) and hasattr(
                attr.column, '_coaster_roles'
            ):
                data = cast(WithRoles, attr.column._coaster_roles)
            elif hasattr(attr, '_coaster_roles'):
                # pylint: disable=protected-access
                data = cast(WithRoles, attr._coaster_roles)
            elif isinstance(
                attr, (QueryableAttribute, RelationshipProperty, MapperProperty)
            ):
                if attr.property in __cache__:
                    data = cast(WithRoles, __cache__[attr.property])
                elif '_coaster_roles' in attr.info:
                    data = cast(WithRoles, attr.info['_coaster_roles'])
                elif hasattr(attr.property, '_coaster_roles'):
                    # pylint: disable=protected-access
                    data = cast(WithRoles, attr.property._coaster_roles)
                else:
                    data = None
            else:
                data = None
            if data is not None:
                for role in data.call:
                    cls.__roles__.setdefault(role, {}).setdefault('call', set()).add(
                        name
                    )
                for role in data.read:
                    cls.__roles__.setdefault(role, {}).setdefault('read', set()).add(
                        name
                    )
                for role in data.write:
                    cls.__roles__.setdefault(role, {}).setdefault('write', set()).add(
                        name
                    )
                for role in data.grants:
                    granted_by = cls.__roles__.setdefault(role, {}).setdefault(
                        'granted_by', []  # List as it needs to be ordered
                    )
                    if name not in granted_by:
                        granted_by.append(name)
                for actor_attr, roles in data.grants_via.items():
                    offer_map: t.Optional[RoleOfferMap]
                    reverse_offer_map: t.Optional[RoleOfferMap]
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
                    elif isinstance(roles, set):
                        offer_map = None
                        reverse_offer_map = None
                    elif isinstance(roles, str):  # type: ignore[unreachable]
                        # Safety check
                        _decl = {actor_attr: roles}
                        raise TypeError(
                            f"grants_via declaration {_decl!r} on {cls.__name__}.{name}"
                            f" is using a string but needs to be a set or dict"
                        )
                    else:
                        raise TypeError(
                            f"Unrecognised value for roles in with_roles[grants_via] on"
                            f" {cls!r}.{name}: {roles!r}"
                        )
                    # Rewrite the pair of attr name and actor_attr for dotted access:
                    # Example: for (attr_name, actor_attr) -> (dotted_name, attr)
                    # ('project', 'membership.user') -> ('project.membership', 'user')
                    if (
                        actor_attr is not None
                        and isinstance(actor_attr, str)
                        and '.' in actor_attr
                    ):
                        dotted_name, actor_attr = actor_attr.rsplit('.', 1)
                        dotted_name = name + '.' + dotted_name
                    else:
                        dotted_name = name
                    if offer_map is not None:
                        cls.__relationship_role_offer_map__[dotted_name] = offer_map
                    if reverse_offer_map is not None:
                        cls.__relationship_reversed_role_offer_map__[
                            dotted_name
                        ] = reverse_offer_map
                    for role in roles:
                        granted_via = cls.__roles__.setdefault(role, {}).setdefault(
                            'granted_via', {}
                        )
                        if dotted_name not in granted_via:
                            granted_via[dotted_name] = actor_attr
                for dataset in data.datasets:
                    cls.__datasets__.setdefault(dataset, set()).add(name)
                processed.add(name)
