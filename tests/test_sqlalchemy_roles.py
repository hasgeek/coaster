from __future__ import annotations

import json
import typing as t
import unittest
import uuid as uuid_  # noqa: F401  # pylint: disable=unused-import

from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import declarative_mixin  # type: ignore[attr-defined]
from sqlalchemy.orm.collections import (
    attribute_mapped_collection,
    column_mapped_collection,
)
import sqlalchemy as sa

from flask import Flask

import pytest

from coaster.sqlalchemy import (
    BaseMixin,
    BaseNameMixin,
    DynamicAssociationProxy,
    LazyRoleSet,
    RoleAccessProxy,
    RoleGrantABC,
    RoleMixin,
    UuidMixin,
    with_roles,
)
from coaster.utils import InspectableSet

from .test_sqlalchemy_models import db

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)


# --- Models ---------------------------------------------------------------------------


@declarative_mixin
class DeclaredAttrMixin:
    # with_roles can be used within a declared attr
    @declared_attr
    def mixed_in1(cls) -> sa.Column[sa.Unicode]:  # pylint: disable=no-self-argument
        return with_roles(db.Column(db.Unicode(250)), rw={'owner'})

    # This previously used the declared_attr_roles decorator, now deprecated and removed
    @with_roles(rw={'owner', 'editor'}, read={'all'})
    @declared_attr
    def mixed_in2(cls) -> sa.Column[sa.Unicode]:  # pylint: disable=no-self-argument
        return db.Column(db.Unicode(250))

    # with_roles can also be used outside a declared attr
    @with_roles(rw={'owner'})
    @declared_attr
    def mixed_in3(cls) -> sa.Column[sa.Unicode]:  # pylint: disable=no-self-argument
        return db.Column(db.Unicode(250))

    # A regular column from the mixin
    mixed_in4 = db.Column(db.Unicode(250))
    mixed_in4 = with_roles(mixed_in4, rw={'owner'})


class RoleModel(DeclaredAttrMixin, RoleMixin, db.Model):  # type: ignore[name-defined]
    __tablename__ = 'role_model'

    # Approach one, declare roles in advance.
    # 'all' is a special role that is always granted from the base class

    __roles__ = {'all': {'read': {'id', 'name', 'title'}}}

    __datasets__ = {'minimal': {'id', 'name'}, 'extra': {'id', 'name', 'mixed_in1'}}
    # Additional dataset members are defined using with_roles

    # Approach two, annotate roles on the attributes.
    # These annotations always add to anything specified in __roles__

    id = db.Column(db.Integer, primary_key=True)  # noqa: A003
    name = with_roles(
        db.Column(db.Unicode(250)), rw={'owner'}
    )  # Specify read+write access

    title = with_roles(
        db.Column(db.Unicode(250)),
        write={'owner', 'editor'},
        datasets={'minimal', 'extra', 'third'},  # 'third' is unique here
    )  # Grant 'owner' and 'editor' write but not read access

    defval = with_roles(db.deferred(db.Column(db.Unicode(250))), rw={'owner'})

    @with_roles(call={'all'})  # 'call' grants call access to the decorated method
    def hello(self):
        return "Hello!"

    # RoleMixin provides a `roles_for` that automatically grants roles from
    # `granted_by` declarations. See the RoleGrant models below for examples.
    # This is optional however, and your model can take independent responsibility
    # for granting roles given an actor and anchors (an iterable). The format for
    # anchors is not specified by RoleMixin.

    def roles_for(self, actor=None, anchors=()):
        # Calling super gives us a set with the standard roles
        roles = super().roles_for(actor, anchors)
        if 'owner-secret' in anchors:
            roles.add('owner')  # Grant owner role
        return roles


class AutoRoleModel(RoleMixin, db.Model):  # type: ignore[name-defined]
    __tablename__ = 'auto_role_model'

    # This model doesn't specify __roles__. It only uses with_roles.
    # It should still work
    id = db.Column(db.Integer, primary_key=True)  # noqa: A003
    with_roles(id, read={'all'})

    name = db.Column(db.Unicode(250))
    with_roles(name, rw={'owner'}, read={'all'})

    __datasets__ = {'default': {'name'}}
    __json_datasets__ = ('default',)


class BaseModel(BaseMixin, db.Model):  # type: ignore[name-defined]
    __tablename__ = 'base_model'


class UuidModel(UuidMixin, BaseMixin, db.Model):  # type: ignore[name-defined]
    __tablename__ = 'uuid_model'


class RelationshipChild(BaseNameMixin, db.Model):  # type: ignore[name-defined]
    __tablename__ = 'relationship_child'

    parent_id = db.Column(None, db.ForeignKey('relationship_parent.id'), nullable=False)

    __roles__ = {'all': {'read': {'name', 'title', 'parent'}}}
    __datasets__ = {
        'primary': {'name', 'title', 'parent'},
        'related': {'name', 'title'},
    }


class RelationshipParent(BaseNameMixin, db.Model):  # type: ignore[name-defined]
    __tablename__ = 'relationship_parent'

    children_list = db.relationship(RelationshipChild, backref='parent')
    children_list_lazy = db.relationship(RelationshipChild, lazy='dynamic')
    children_set = db.relationship(RelationshipChild, collection_class=set)
    children_dict_attr = db.relationship(
        RelationshipChild, collection_class=attribute_mapped_collection('name')
    )
    children_dict_column = db.relationship(
        RelationshipChild,
        collection_class=column_mapped_collection(RelationshipChild.name),
    )

    __roles__ = {
        'all': {
            'read': {
                'name',
                'title',
                'children_list',
                'children_set',
                'children_dict_attr',
                'children_dict_column',
            }
        }
    }
    __datasets__ = {
        'primary': {
            'name',
            'title',
            'children_list',
            'children_set',
            'children_dict_attr',
            'children_dict_column',
        },
        'related': {'name', 'title'},
    }


granted_users = db.Table(
    'granted_users',
    db.Model.metadata,
    db.Column('role_grant_many_id', None, db.ForeignKey('role_grant_many.id')),
    db.Column('role_user_id', None, db.ForeignKey('role_user.id')),
)


RelationshipParent.children_names = DynamicAssociationProxy(
    'children_list_lazy', 'name'
)


class RoleGrantMany(BaseMixin, db.Model):  # type: ignore[name-defined]
    """Test model for granting roles to users in many-to-one and many-to-many relationships"""

    __tablename__ = 'role_grant_many'

    __roles__ = {
        'primary_role': {'granted_by': ['primary_users']},
        'secondary_role': {'granted_by': ['secondary_users']},
    }


class RoleUser(BaseMixin, db.Model):  # type: ignore[name-defined]
    """Test model to represent a user who has roles"""

    __tablename__ = 'role_user'

    doc_id = db.Column(None, db.ForeignKey('role_grant_many.id'))
    doc = db.relationship(
        RoleGrantMany,
        foreign_keys=[doc_id],
        backref=db.backref('primary_users', lazy='dynamic'),
    )
    secondary_docs = db.relationship(
        RoleGrantMany, secondary=granted_users, backref='secondary_users'
    )


class RoleGrantOne(BaseMixin, db.Model):  # type: ignore[name-defined]
    """Test model for granting roles to users in a one-to-many relationship"""

    __tablename__ = 'role_grant_one'

    user_id = db.Column(None, db.ForeignKey('role_user.id'))
    user = with_roles(db.relationship(RoleUser), grants={'creator'})


class RoleGrantSynonym(BaseMixin, db.Model):  # type: ignore[name-defined]
    """Test model for granting roles to synonyms"""

    __tablename__ = 'role_grant_synonym'

    # Base column has roles defined
    datacol = with_roles(db.Column(db.Unicode()), rw={'owner'})
    # Synonym cannot have independent roles and will mirror the target
    altcol = db.synonym('datacol')


class RoleMembership(BaseMixin, db.Model):  # type: ignore[name-defined]
    """Test model that grants multiple roles"""

    __tablename__ = 'role_membership'

    user_id = db.Column(None, db.ForeignKey('role_user.id'))
    user = db.relationship(RoleUser)

    doc_id = db.Column(None, db.ForeignKey('multirole_document.id'))
    doc = db.relationship('MultiroleDocument')

    role1 = db.Column(db.Boolean, default=False)
    role2 = db.Column(db.Boolean, default=False)
    role3 = db.Column(db.Boolean, default=False)

    @property
    def offered_roles(self):
        roles = set()
        if self.role1:
            roles.add('role1')
        if self.role2:
            roles.add('role2')
        if self.role3:
            roles.add('role3')
        return roles


class MultiroleParent(BaseMixin, db.Model):  # type: ignore[name-defined]
    """Test model to serve as a role granter to the child model"""

    __tablename__ = 'multirole_parent'
    user_id = db.Column(None, db.ForeignKey('role_user.id'))
    user = with_roles(db.relationship(RoleUser), grants={'prole1', 'prole2'})


class MultiroleDocument(BaseMixin, db.Model):  # type: ignore[name-defined]
    """Test model that grants multiple roles via RoleMembership"""

    __tablename__ = 'multirole_document'

    parent_id = db.Column(None, db.ForeignKey('multirole_parent.id'))
    parent = with_roles(
        db.relationship(MultiroleParent),
        # grants_via[None] implies that these roles are granted by parent.roles_for(),
        # and not via parent.`actor_attr`. While other roles may also be granted by
        # parent.roles_for(), we only want one, and we want to give it a different name
        # here. The dict maps source role to destination role.
        grants_via={None: {'prole1': 'parent_prole1'}},
    )

    not_a_relationship = "This is not a relationship"

    # Acquire parent_role through parent.user (a scalar relationship)
    # Acquire parent_other_role too (will be cached alongside parent_role)
    # Acquire role1 through both relationships (query and list relationships)
    # Acquire role2 and role3 via only one relationship each
    # This contrived setup is only to test that it works via all relationship types
    __roles__ = {
        'parent_role': {'granted_via': {'parent': 'user'}},
        'parent_other_role': {'granted_via': {'parent': 'user'}},
        'role1': {'granted_via': {'rel_lazy': 'user', 'rel_list': 'user'}},
        'incorrectly_specified_role': {'granted_via': {'rel_list': None}},
        'also_incorrect_role': {'granted_via': {'not_a_relationship': None}},
    }

    # Grant via a query relationship
    rel_lazy = with_roles(
        db.relationship(RoleMembership, lazy='dynamic'),
        grants_via={RoleMembership.user: {'role2'}},
    )
    # Grant via a list-like relationship
    rel_list = with_roles(
        db.relationship(RoleMembership), grants_via={'user': {'role3'}}
    )

    # Role grants can be specified via:
    # 1. with_roles(grants_via={actor_attr_or_name: {role} or {offered_role: role}})
    # 2. __roles__[role]['granted_via'] = {'rel_name': 'actor_attr_name'}
    # Offered role maps are specified in an internal __relationship_role_offer_map__.
    # The only way to make an entry there is via with_roles.


class MultiroleChild(BaseMixin, db.Model):  # type: ignore[name-defined]
    """Model that inherits roles from its parent"""

    __tablename__ = 'multirole_child'
    parent_id = db.Column(None, db.ForeignKey('multirole_document.id'))
    parent = with_roles(
        db.relationship(MultiroleDocument),
        grants_via={
            'parent.user': {'super_parent_role'},  # Maps to parent.parent.user
            'rel_lazy.user': {  # Maps to parent.rel_lazy[item].user
                # Map role2 and role3, but explicitly ignore role1.
                # Demonstrate mapping to multiple roles
                'role2': {'parent_role2', 'parent_role2b', 'parent_role_shared'},
                'role3': {'parent_role3', 'parent_role3b', 'parent_role_shared'},
            },
        },
    )


# --- Utilities ------------------------------------------------------------------------


class JsonTestEncoder(json.JSONEncoder):
    """Encode to JSON."""

    def default(self, o):
        if isinstance(o, RoleAccessProxy):
            return dict(o)
        return super().default(o)


class JsonProtocolEncoder(json.JSONEncoder):
    """Encode to JSON."""

    def default(self, o):
        if hasattr(o, '__json__'):
            return o.__json__()
        return super().default(o)


# --- Tests ----------------------------------------------------------------------------


class TestCoasterRoles(unittest.TestCase):
    app = app

    def setUp(self):
        self.ctx = self.app.test_request_context()
        self.ctx.push()
        db.create_all()
        self.session = db.session
        # SQLAlchemy doesn't fire mapper_configured events until the first time a
        # mapping is used, or configuration is explicitly requested
        db.configure_mappers()

    def tearDown(self):
        self.session.rollback()
        db.drop_all()
        self.ctx.pop()

    def test_base_is_clean(self):
        """Specifying roles never mutates RoleMixin.__roles__"""
        assert RoleMixin.__roles__ == {}

    def test_role_dict(self):
        """Roles may be declared multiple ways and they all work"""
        assert RoleModel.__roles__ == {
            'all': {'call': {'hello'}, 'read': {'id', 'name', 'title', 'mixed_in2'}},
            'editor': {'read': {'mixed_in2'}, 'write': {'title', 'mixed_in2'}},
            'owner': {
                'read': {
                    'name',
                    'defval',
                    'mixed_in1',
                    'mixed_in2',
                    'mixed_in3',
                    'mixed_in4',
                },
                'write': {
                    'name',
                    'title',
                    'defval',
                    'mixed_in1',
                    'mixed_in2',
                    'mixed_in3',
                    'mixed_in4',
                },
            },
        }

    def test_autorole_dict(self):
        """A model without __roles__, using only with_roles, also works as expected"""
        assert AutoRoleModel.__roles__ == {
            'all': {'read': {'id', 'name'}},
            'owner': {'read': {'name'}, 'write': {'name'}},
        }

    def test_basemixin_roles(self):
        """A model with BaseMixin by default exposes nothing to the 'all' role"""
        assert BaseModel.__roles__.get('all', {}).get('read', set()) == set()

    def test_uuidmixin_roles(self):
        """
        A model with UuidMixin provides 'all' read access to uuid, uuid_b58 and uuid_b64
        among others.
        """
        assert {'uuid', 'buid', 'uuid_b58', 'uuid_b64'} <= UuidModel.__roles__['all'][
            'read'
        ]

    def test_roles_for_anon(self):
        """An anonymous actor should have 'all' and 'anon' roles"""
        rm = RoleModel(name='test', title='Test')
        roles = rm.roles_for(actor=None)
        assert roles == {'all', 'anon'}

    def test_roles_for_actor(self):
        """An actor (but anchors) must have 'all' and 'auth' roles"""
        rm = RoleModel(name='test', title='Test')
        roles = rm.roles_for(actor=1)
        assert roles == {'all', 'auth'}
        roles = rm.roles_for(anchors=(1,))
        assert roles == {'all', 'anon'}

    def test_roles_for_owner(self):
        """Presenting the correct anchor grants 'owner' role"""
        rm = RoleModel(name='test', title='Test')
        roles = rm.roles_for(anchors=('owner-secret',))
        assert roles == {'all', 'anon', 'owner'}

    def test_current_roles(self):
        """Current roles are available"""
        rm = RoleModel(name='test', title='Test')
        roles = rm.current_roles
        assert roles == {'all', 'anon'}
        assert roles.all
        assert roles.anon
        assert not roles.owner

    def test_access_for_syntax(self):
        """access_for can be called with either roles or actor for identical outcomes"""
        rm = RoleModel(name='test', title='Test')
        proxy1 = rm.access_for(roles=rm.roles_for(actor=None))
        proxy2 = rm.access_for(actor=None)
        assert proxy1 == proxy2

    def test_access_for_all(self):
        """All actors should be able to read some fields"""
        arm = AutoRoleModel(name='test')
        proxy = arm.access_for(actor=None)
        assert len(proxy) == 2
        assert set(proxy.keys()) == {'id', 'name'}

    def test_current_access(self):
        """Current access is available"""
        arm = AutoRoleModel(name='test')
        proxy = arm.current_access()
        assert len(proxy) == 2
        assert set(proxy.keys()) == {'id', 'name'}

        roles = proxy.current_roles
        assert roles == {'all', 'anon'}
        assert roles.all
        assert roles.anon
        assert not roles.owner

    def test_json_protocol(self):
        """Cast to JSON happens with __json__"""
        arm = AutoRoleModel(name='test')
        json_str = json.dumps(arm, cls=JsonProtocolEncoder)
        data = json.loads(json_str)
        assert data == {'name': 'test'}
        # We know what the JSON contains because it's specified in the model
        assert AutoRoleModel.__datasets__[AutoRoleModel.__json_datasets__[0]] == {
            'name'
        }

    def test_attr_dict_access(self):
        """Proxies support identical attribute and dictionary access"""
        rm = RoleModel(name='test', title='Test')
        proxy = rm.access_for(actor=None)
        assert 'name' in proxy
        assert proxy.name == 'test'
        assert proxy['name'] == 'test'

    def test_diff_roles(self):
        """Different roles get different access"""
        rm = RoleModel(name='test', title='Test')
        proxy1 = rm.access_for(roles={'all'})
        proxy2 = rm.access_for(roles={'owner'})
        proxy3 = rm.access_for(roles={'all', 'owner'})
        assert set(proxy1) == {'id', 'name', 'title', 'mixed_in2'}
        assert set(proxy2) == {
            'name',
            'defval',
            'mixed_in1',
            'mixed_in2',
            'mixed_in3',
            'mixed_in4',
        }
        assert set(proxy3) == {
            'id',
            'name',
            'title',
            'defval',
            'mixed_in1',
            'mixed_in2',
            'mixed_in3',
            'mixed_in4',
        }

    def test_diff_roles_single_model_dataset(self):
        """Data profiles constrain the attributes available via enumeration"""
        rm = RoleModel(name='test', title='Test')
        proxy1a = rm.access_for(roles={'all'}, datasets=('minimal',))
        proxy2a = rm.access_for(roles={'owner'}, datasets=('minimal',))
        proxy3a = rm.access_for(roles={'all', 'owner'}, datasets=('minimal',))
        assert set(proxy1a) == {'id', 'name', 'title'}
        assert len(proxy1a) == 3
        assert set(proxy2a) == {'name'}
        assert len(proxy2a) == 1
        assert set(proxy3a) == {'id', 'name', 'title'}
        assert len(proxy3a) == 3

        proxy1b = rm.access_for(roles={'all'}, datasets=('extra',))
        proxy2b = rm.access_for(roles={'owner'}, datasets=('extra',))
        proxy3b = rm.access_for(roles={'all', 'owner'}, datasets=('extra',))
        assert set(proxy1b) == {'id', 'name', 'title'}
        assert len(proxy1b) == 3
        assert set(proxy2b) == {'name', 'mixed_in1'}
        assert len(proxy2b) == 2
        assert set(proxy3b) == {'id', 'name', 'title', 'mixed_in1'}
        assert len(proxy3b) == 4

        # Dataset was created from with_roles
        assert RoleModel.__datasets__['third'] == {'title'}

    def test_write_without_read(self):
        """A proxy may allow writes without allowing reads"""
        rm = RoleModel(name='test', title='Test')
        proxy = rm.access_for(roles={'owner'})
        assert rm.title == 'Test'
        proxy.title = 'Changed'
        assert rm.title == 'Changed'
        proxy['title'] = 'Changed again'
        assert rm.title == 'Changed again'
        with pytest.raises(AttributeError):
            proxy.title
        with pytest.raises(KeyError):
            proxy['title']

    def test_no_write(self):
        """A proxy will disallow writes if the role doesn't permit it"""
        rm = RoleModel(name='test', title='Test')
        proxy = rm.access_for(roles={'editor'})
        assert rm.title == 'Test'
        # 'editor' has permission to write to 'title'
        proxy.title = 'Changed'
        assert rm.title == 'Changed'
        # 'editor' does not have permission to write to 'name'
        assert rm.name == 'test'
        with pytest.raises(AttributeError):
            proxy.name = 'changed'
        with pytest.raises(KeyError):
            proxy['name'] = 'changed'
        assert rm.name == 'test'

    def test_method_call(self):
        """Method calls are allowed as calling is just an alias for reading"""
        rm = RoleModel(name='test', title='Test')
        proxy1 = rm.access_for(roles={'all'})
        proxy2 = rm.access_for(roles={'owner'})
        assert proxy1.hello() == "Hello!"
        with pytest.raises(AttributeError):
            proxy2.hello()
        with pytest.raises(KeyError):
            proxy2['hello']()

    def test_dictionary_comparison(self):
        """A proxy can be compared with a dictionary"""
        rm = RoleModel(name='test', title='Test')
        proxy = rm.access_for(roles={'all'})
        assert proxy == {'id': None, 'name': 'test', 'title': 'Test', 'mixed_in2': None}

    def test_bad_decorator(self):
        """Prevent with_roles from being used with a positional parameter"""
        with pytest.raises(TypeError):

            @with_roles({'all'})
            def f():
                pass

    def test_access_for_roles_and_actor_or_anchors(self):
        """access_for accepts roles or actor/anchors, not both/all"""
        rm = RoleModel(name='test', title='Test')
        with pytest.raises(TypeError):
            rm.access_for(roles={'all'}, actor=1)
        with pytest.raises(TypeError):
            rm.access_for(roles={'all'}, anchors=('owner-secret',))
        with pytest.raises(TypeError):
            rm.access_for(roles={'all'}, actor=1, anchors=('owner-secret',))

    def test_scalar_relationship(self):
        """Scalar relationships are automatically wrapped in an access proxy"""
        parent = RelationshipParent(title="Parent")
        child = RelationshipChild(title="Child", parent=parent)
        self.session.add_all([parent, child])
        self.session.commit()

        proxy = child.access_for(roles={'all'})
        assert proxy.title == child.title
        assert isinstance(proxy.parent, RoleAccessProxy)
        assert proxy.parent.title == parent.title

        # TODO: Test for other roles using the actor parameter

    def test_collection_relationship(self):
        """Collection relationships are automatically wrapped in an access proxy"""
        parent = RelationshipParent(title="Parent")
        child = RelationshipChild(title="Child", parent=parent)
        self.session.add_all([parent, child])
        self.session.commit()

        # These tests use ``access_for(roles={'all'})`` even though the `roles`
        # parameter is not suitable for accessing relationships, as roles are specific
        # to an object. This is okay here only because the 'all' role is automatically
        # granted on all objects. Production use should be with `actor` and `anchors`.

        proxy = parent.access_for(roles={'all'})
        assert proxy.title == parent.title

        assert isinstance(proxy.children_list[0], RoleAccessProxy)
        assert proxy.children_list[0].title == child.title

        # Set relationships are mapped into a list in the proxy
        assert isinstance(proxy.children_set, tuple)
        assert isinstance(proxy.children_set[0], RoleAccessProxy)
        assert proxy.children_set[0].title == child.title

        assert isinstance(proxy.children_dict_attr, dict)
        assert isinstance(proxy.children_dict_attr['child'], RoleAccessProxy)
        assert proxy.children_dict_attr['child'].title == child.title

        assert isinstance(proxy.children_dict_column, dict)
        assert isinstance(proxy.children_dict_column['child'], RoleAccessProxy)
        assert proxy.children_dict_column['child'].title == child.title

    def test_cascading_datasets(self):
        """Test data profile cascades"""
        parent = RelationshipParent(title="Parent")
        child = RelationshipChild(title="Child", parent=parent)
        self.session.add_all([parent, child])
        self.session.commit()

        # These tests use ``access_for(roles={'all'})`` even though the `roles`
        # parameter is not suitable for accessing relationships, as roles are specific
        # to an object. This is okay here only because the 'all' role is automatically
        # granted on all objects. Production use should be with `actor` and `anchors`.

        pchild = child.access_for(roles={'all'}, datasets=('primary',))
        assert set(pchild) == {'name', 'title', 'parent'}

        # pchild's 'primary' profile includes 'parent', but we haven't specified a
        # profile for the parent so it will be empty
        assert pchild.parent == {}

        pchild = child.access_for(roles={'all'}, datasets=('primary', 'primary'))
        pparent = pchild.parent
        assert set(pparent) == {
            'name',
            'title',
            'children_list',
            'children_set',
            'children_dict_attr',
            'children_dict_column',
        }
        # Same blank object when we recursively access the child
        assert pparent.children_list[0] == {}

        # Using a well crafted set of profiles will result in a clean containment
        pchild = child.access_for(roles={'all'}, datasets=('primary', 'related'))
        assert json.loads(json.dumps(pchild, cls=JsonTestEncoder)) == {
            'name': "child",
            'title': "Child",
            'parent': {'name': "parent", 'title': "Parent"},
        }

        pparent = parent.access_for(roles={'all'}, datasets=('primary', 'related'))
        assert json.loads(json.dumps(pparent, cls=JsonTestEncoder)) == {
            'name': "parent",
            'title': "Parent",
            'children_list': [{'name': "child", 'title': "Child"}],
            'children_set': [{'name': "child", 'title': "Child"}],
            'children_dict_attr': {'child': {'name': "child", 'title': "Child"}},
            'children_dict_column': {'child': {'name': "child", 'title': "Child"}},
        }

        # Data profiles only affect enumeration
        # Actual availability is determined by role access

        pchild = child.access_for(roles={'all'}, datasets=('related', 'related'))
        assert 'parent' not in set(pchild)  # Enumerate and test for containment
        assert 'parent' in pchild  # Test for containment directly
        assert pchild['parent'] is not None
        assert pchild.parent is not None

    def test_missing_dataset(self):
        """A missing dataset will raise a KeyError indicating what is missing where"""
        parent = RelationshipParent(title="Parent")
        self.session.add(parent)
        self.session.commit()
        with pytest.raises(KeyError, match='bogus'):
            json.dumps(
                parent.access_for(roles={'all'}, datasets=('bogus',)),
                cls=JsonTestEncoder,
            )

    def test_role_grant(self):
        m1 = RoleGrantMany()
        m2 = RoleGrantMany()
        u1 = RoleUser(doc=m1)
        u2 = RoleUser(doc=m2)

        m1.secondary_users.extend([u1, u2])

        rm1u1 = m1.roles_for(u1)
        rm1u2 = m1.roles_for(u2)
        rm2u1 = m2.roles_for(u1)
        rm2u2 = m2.roles_for(u2)

        # Test that roles are discovered from lazy=dynamic relationships
        assert 'primary_role' in rm1u1
        assert 'primary_role' not in rm1u2
        assert 'primary_role' not in rm2u1
        assert 'primary_role' in rm2u2

        # Test that roles are discovered from list/set collection relationships
        assert 'secondary_role' in rm1u1
        assert 'secondary_role' in rm1u1
        assert 'secondary_role' not in rm2u1
        assert 'secondary_role' not in rm2u2

        o1 = RoleGrantOne(user=u1)
        o2 = RoleGrantOne(user=u2)

        ro1u1 = o1.roles_for(u1)
        ro1u2 = o1.roles_for(u2)
        ro2u1 = o2.roles_for(u1)
        ro2u2 = o2.roles_for(u2)

        assert 'creator' in ro1u1
        assert 'creator' not in ro1u2
        assert 'creator' not in ro2u1
        assert 'creator' in ro2u2

    def test_actors_with(self):
        m1 = RoleGrantMany()
        m2 = RoleGrantMany()
        u1 = RoleUser(doc=m1)
        u2 = RoleUser(doc=m2)
        o1 = RoleGrantOne(user=u1)
        o2 = RoleGrantOne(user=u2)
        m1.secondary_users.extend([u1, u2])

        assert set(o1.actors_with({'creator'})) == {u1}
        assert set(o2.actors_with({'creator'})) == {u2}

        assert set(m1.actors_with({'primary_role'})) == {u1}
        assert set(m2.actors_with({'primary_role'})) == {u2}
        assert set(m1.actors_with({'secondary_role'})) == {u1, u2}
        assert set(m2.actors_with({'secondary_role'})) == set()
        assert set(m1.actors_with({'primary_role', 'secondary_role'})) == {u1, u2}
        assert set(m2.actors_with({'primary_role', 'secondary_role'})) == {u2}

        # Ask for role when returning a user
        assert set(o1.actors_with(['creator'], with_role=True)) == {(u1, 'creator')}
        assert set(o2.actors_with(['creator'], with_role=True)) == {(u2, 'creator')}

        assert set(m1.actors_with(['primary_role'], with_role=True)) == {
            (u1, 'primary_role')
        }
        assert set(m2.actors_with(['primary_role'], with_role=True)) == {
            (u2, 'primary_role')
        }
        assert set(m1.actors_with(['secondary_role'], with_role=True)) == {
            (u1, 'secondary_role'),
            (u2, 'secondary_role'),
        }
        assert set(m2.actors_with(['secondary_role'], with_role=True)) == set()
        assert set(
            m1.actors_with(['primary_role', 'secondary_role'], with_role=True)
        ) == {(u1, 'primary_role'), (u2, 'secondary_role')}
        assert set(
            m2.actors_with(['primary_role', 'secondary_role'], with_role=True)
        ) == {(u2, 'primary_role')}

    def test_actors_with_invalid(self):
        m1 = RoleGrantMany()
        with pytest.raises(ValueError):
            # Parameter can't be a string. Because actors_with is a generator,
            # we have to extract a value from it to trigger the exception
            next(m1.actors_with('owner'))

    def test_role_grant_synonyms(self):
        """Test that synonyms reflect the underlying attribute"""
        rgs = RoleGrantSynonym(datacol='abc')
        assert rgs.datacol == 'abc'
        assert rgs.altcol == 'abc'

        owner_proxy = rgs.access_for(roles={'owner'})
        # datacol is present as it has owner read access defined
        assert 'datacol' in owner_proxy
        # altcol mirrors datacol
        assert 'altcol' in owner_proxy

        assert owner_proxy.datacol == 'abc'
        assert owner_proxy['datacol'] == 'abc'

        # The datacol column gives write access to the owner role
        owner_proxy.datacol = 'xyz'
        assert owner_proxy.datacol == 'xyz'

        owner_proxy.altcol = 'uvw'
        assert owner_proxy.datacol == 'uvw'

        all_proxy = rgs.access_for(roles={'all'})
        assert 'datacol' not in all_proxy
        assert 'altcol' not in all_proxy

    def test_dynamic_association_proxy(self):
        parent1 = RelationshipParent(title="Proxy Parent 1")
        parent2 = RelationshipParent(title="Proxy Parent 2")
        parent3 = RelationshipParent(title="Proxy Parent 3")
        child1 = RelationshipChild(name='child1', title="Proxy Child 1", parent=parent1)
        child2 = RelationshipChild(name='child2', title="Proxy Child 2", parent=parent1)
        child3 = RelationshipChild(name='child3', title="Proxy Child 3", parent=parent2)
        self.session.add_all([parent1, parent2, parent3, child1, child2, child3])
        self.session.commit()

        assert isinstance(RelationshipParent.children_names, DynamicAssociationProxy)

        assert child1.name in parent1.children_names
        assert child2.name in parent1.children_names
        assert child3.name not in parent1.children_names

        assert child1.name not in parent2.children_names
        assert child2.name not in parent2.children_names
        assert child3.name in parent2.children_names

        assert child1.name not in parent3.children_names
        assert child2.name not in parent3.children_names
        assert child3.name not in parent3.children_names

        assert len(parent1.children_names) == 2
        assert set(parent1.children_names) == {child1.name, child2.name}

        assert len(parent2.children_names) == 1
        assert set(parent2.children_names) == {child3.name}

        assert len(parent3.children_names) == 0
        assert set(parent3.children_names) == set()

        assert bool(parent1.children_names) is True
        assert bool(parent2.children_names) is True
        assert bool(parent3.children_names) is False

        # Each access constructs a separate wrapper. Assert they are equal
        p1a = parent1.children_names
        p1b = parent1.children_names
        assert p1a is not p1b
        assert p1a == p1b  # Test __eq__
        assert not (p1a != p1b)  # Test __ne__
        assert p1a != parent2.children_names  # Cross-check with an unrelated proxy

    def test_granted_via(self):
        """
        Roles can be granted via related objects
        """
        u1 = RoleUser()
        u2 = RoleUser()
        u3 = RoleUser()
        u4 = RoleUser()
        parent = MultiroleParent(user=u1)
        document = MultiroleDocument(parent=parent)
        document_no_parent = MultiroleDocument(parent=None)
        child = MultiroleChild(parent=document)
        m1 = RoleMembership(doc=document, user=u1, role1=True, role2=False, role3=False)
        m2 = RoleMembership(doc=document, user=u2, role1=True, role2=True, role3=False)
        m3 = RoleMembership(doc=document, user=u3, role1=True, role2=False, role3=True)
        m4 = RoleMembership(doc=document, user=u4, role1=False, role2=True, role3=True)
        self.session.add_all([u1, u2, u3, u4, parent, document, child, m1, m2, m3, m4])
        self.session.commit()

        # All three memberships appear in both relationships
        assert m1 in document.rel_lazy
        assert m1 in document.rel_list
        assert m2 in document.rel_lazy
        assert m2 in document.rel_list
        assert m3 in document.rel_lazy
        assert m3 in document.rel_list

        # u1 gets 'parent_role' via parent, but u2 and u3 don't
        assert 'parent_role' in document.roles_for(u1)
        assert 'parent_role' not in document.roles_for(u2)
        assert 'parent_role' not in document.roles_for(u3)

        assert 'parent_role' not in document_no_parent.roles_for(u1)

        # parent grants prole1 and prole2. Testing for one auto-loads the other
        proles = parent.roles_for(u1)
        assert 'prole1' not in proles._present
        assert 'prole2' not in proles._present
        assert 'prole1' in proles
        assert 'prole2' in proles._present
        assert 'prole2' in proles

        # u1 also gets 'parent_prole1' remapped from 'prole1' in parent.roles_for(),
        # but not 'prole1' itself or 'prole2'
        assert 'parent_prole1' in document.roles_for(u1)
        assert 'parent_prole2' not in document.roles_for(u1)
        assert 'prole1' not in document.roles_for(u1)
        assert 'prole2' not in document.roles_for(u2)
        assert 'parent_prole1' not in document.roles_for(u2)
        assert 'parent_prole2' not in document.roles_for(u2)

        # Start over for document roles
        roles1 = document.roles_for(u1)
        roles2 = document.roles_for(u2)
        roles3 = document.roles_for(u3)

        # Check for parent_role again. parent_other_role is auto-discovered
        assert 'parent_role' not in roles1._present
        assert 'parent_other_role' not in roles1._present
        assert 'parent_role' in roles1
        # parent_other_role was automatically discovered and cached
        assert 'parent_other_role' in roles1._present
        assert 'parent_other_role' in roles1

        # Confirm these lazyrolesets are not already populated with the test roles
        # by looking at their internal data structure
        assert 'role1' not in roles1._present
        assert 'role2' not in roles1._present
        assert 'role3' not in roles1._present
        assert 'role1' not in roles2._present
        assert 'role2' not in roles2._present
        assert 'role3' not in roles2._present
        assert 'role1' not in roles3._present
        assert 'role2' not in roles3._present
        assert 'role3' not in roles3._present

        # Now test for roles and observe the other roles are also discovered
        # From m1, roles1 has role1 but not role2, role3
        assert 'role1' in roles1  # Granted in m1
        assert 'role2' not in roles1._present  # Not granted in m1, not discovered
        assert 'role2' not in roles1._not_present  # Not rejected either
        assert 'role3' not in roles1._present  # Not granted in m1, not discovered
        assert 'role3' not in roles1._not_present  # Not rejected either
        assert 'role2' not in roles1  # Not granted in m1
        assert 'role2' not in roles1._present  # Still not granted
        assert 'role2' in roles1._not_present  # But now known not present
        assert 'role2' not in roles1  # Confirm via public API

        # From m2, roles2 has role1, role2 but not role3
        assert 'role2' in roles2  # Granted in m2 via rel_lazy (only)
        assert 'role1' in roles2._present  # Granted in m2, auto discovered
        assert 'role3' not in roles2._present  # Not granted in m2, not discovered
        assert 'role3' not in roles2._not_present  # Not rejected either

        # From m3, roles3 has role1, role3 but not role2
        assert 'role3' in roles3  # Granted in m3 via rel_list (only)
        assert 'role1' in roles3._present  # Granted in m3, auto discovered
        assert 'role2' not in roles3._present  # Not granted in m3, not discovered
        assert 'role2' not in roles3._not_present  # Not rejected either

        # Can a relationship grant roles that were supposed to be available via
        # another relationship? Yes
        roles4a = document.roles_for(u4)
        # No roles cached yet
        assert 'role2' not in roles4a._present
        assert 'role3' not in roles4a._present
        # role1 = False, role2 = True, role3 = True
        assert 'role2' in roles4a  # Discovered via rel_lazy
        assert 'role3' in roles4a._present  # This got cached despite not being rel_lazy

        roles4b = document.roles_for(u4)
        # No roles cached yet
        assert 'role2' not in roles4b._present
        assert 'role3' not in roles4b._present
        # role1 = False, role2 = True, role3 = True
        assert 'role3' in roles4b  # Discovered via rel_list
        assert 'role2' in roles4b._present  # This got cached despite not being rel_list

        # The child model inherits remapped roles from document
        # role1 is skipped even if present, while role2 and role3 are remapped
        croles1 = child.roles_for(u1)
        croles2 = child.roles_for(u2)
        croles3 = child.roles_for(u3)
        for roleset in (croles1, croles2, croles3):
            assert 'role1' not in roleset
            assert 'role2' not in roleset
            assert 'role3' not in roleset
            assert 'parent_role1' not in roleset
        # u1 gets super_parent_role via parent.parent
        assert 'super_parent_role' in croles1
        # u1 has neither role2 nor role3 in m1
        assert 'parent_role2' not in croles1
        assert 'parent_role3' not in croles1
        assert 'parent_role2b' not in croles1
        assert 'parent_role3b' not in croles1
        assert 'parent_role_shared' not in croles1
        # u2 has role2 but not role3 in m2
        assert 'parent_role2' in croles2
        assert 'parent_role3' not in croles2
        assert 'parent_role2b' in croles2
        assert 'parent_role3b' not in croles2
        assert 'parent_role_shared' in croles2
        # u2 has role3 but not role2 in m3
        assert 'parent_role2' not in croles3
        assert 'parent_role3' in croles3
        assert 'parent_role2b' not in croles3
        assert 'parent_role3b' in croles3
        assert 'parent_role_shared' in croles3

    def test_granted_via_error(self):
        """A misconfigured granted_via declaration will raise an error"""
        user = RoleUser()
        document = MultiroleDocument()
        membership = RoleMembership(doc=document, user=user)
        self.session.add_all([user, document, membership])
        roles = document.roles_for(user)
        with pytest.raises(TypeError):
            'incorrectly_specified_role' in roles

    def test_actors_from_granted_via(self):
        """
        actors_with will find actors whose roles are declared in granted_via
        """
        u1 = RoleUser()
        u2 = RoleUser()
        u3 = RoleUser()
        u4 = RoleUser()
        parent = MultiroleParent(user=u1)
        document = MultiroleDocument(parent=parent)
        document_no_parent = MultiroleDocument(parent=None)
        child = MultiroleChild(parent=document)
        child2 = MultiroleChild()
        m1 = RoleMembership(doc=document, user=u1, role1=True, role2=False, role3=False)
        m2 = RoleMembership(doc=document, user=u2, role1=True, role2=True, role3=False)
        m3 = RoleMembership(doc=document, user=u3, role1=True, role2=False, role3=True)
        m4 = RoleMembership(doc=document, user=u4, role1=False, role2=True, role3=True)
        m5 = RoleMembership(doc=document, role1=True, role2=True, role3=True)  # No user
        self.session.add_all(
            [u1, u2, u3, u4, parent, document, child, m1, m2, m3, m4, m5]
        )
        self.session.commit()

        assert list(parent.actors_with({'prole1'})) == [u1]
        assert list(parent.actors_with({'prole2'})) == [u1]
        assert list(parent.actors_with({'prole1', 'prole2'})) == [u1]
        assert list(parent.actors_with({'random'})) == []

        assert list(document.actors_with({'prole1'})) == []
        assert list(document.actors_with({'parent_prole1'})) == [u1]
        assert list(document.actors_with({'parent_role'})) == [u1]
        assert list(document.actors_with({'parent_other_role'})) == [u1]
        assert list(document.actors_with({'parent_role', 'parent_other_role'})) == [u1]
        assert list(document.actors_with({'role1'})) == [u1, u2, u3]
        assert list(document.actors_with({'role2'})) == [u2, u4]
        assert list(document.actors_with({'role3'})) == [u3, u4]
        assert list(document.actors_with({'incorrectly_specified_role'})) == []
        with pytest.raises(TypeError):
            list(document.actors_with({'also_incorrect_role'}))

        assert list(document_no_parent.actors_with({'prole1'})) == []
        assert list(document_no_parent.actors_with({'parent_prole1'})) == []
        assert list(document_no_parent.actors_with({'parent_role'})) == []
        assert list(document_no_parent.actors_with({'parent_other_role'})) == []
        assert (
            list(document_no_parent.actors_with({'parent_role', 'parent_other_role'}))
            == []
        )
        assert list(document_no_parent.actors_with({'role1'})) == []
        assert list(document_no_parent.actors_with({'role2'})) == []
        assert list(document_no_parent.actors_with({'role3'})) == []

        assert list(child.actors_with({'super_parent_role'})) == [u1]
        assert list(child.actors_with({'parent_role1'})) == []
        assert list(child.actors_with({'parent_role2'})) == [u2, u4]
        assert list(child.actors_with({'parent_role2b'})) == [u2, u4]
        assert list(child.actors_with({'parent_role3'})) == [u3, u4]
        assert list(child.actors_with({'parent_role3b'})) == [u3, u4]
        assert list(child.actors_with({'parent_role_shared'})) == [u2, u3, u4]

        assert list(child2.actors_with({'super_parent_role'})) == []
        assert list(child2.actors_with({'parent_role1'})) == []
        assert list(child2.actors_with({'parent_role2'})) == []
        assert list(child2.actors_with({'parent_role2b'})) == []
        assert list(child2.actors_with({'parent_role3'})) == []
        assert list(child2.actors_with({'parent_role3b'})) == []
        assert list(child2.actors_with({'parent_role_shared'})) == []


class TestLazyRoleSet(unittest.TestCase):
    """Tests for LazyRoleSet, isolated from RoleMixin"""

    class EmptyDocument(RoleMixin):
        # Test LazyRoleSet without the side effects of roles defined in the document
        pass

    class Document(RoleMixin):
        _user: t.Optional[TestLazyRoleSet.User] = None
        _userlist = ()
        __roles__ = {'owner': {'granted_by': ['user', 'userlist']}}

        # Test flags
        accessed_user = False
        accessed_userlist = False

        @property
        def user(self):
            self.accessed_user = True
            return self._user

        @user.setter
        def user(self, value):
            self._user = value
            self.accessed_user = False

        @property
        def userlist(self):
            self.accessed_userlist = True
            return self._userlist

        @userlist.setter
        def userlist(self, value):
            self._userlist = value
            self.accessed_userlist = False

    class User:
        pass

    def test_initial(self):
        r1 = LazyRoleSet(self.EmptyDocument(), self.User(), {'all', 'auth'})
        assert r1._present == {'all', 'auth'}
        assert r1._not_present == set()

        r2 = LazyRoleSet(self.EmptyDocument(), self.User())
        assert r2._present == set()
        assert r2._not_present == set()

    def test_set_add_remove_discard(self):
        r = LazyRoleSet(self.EmptyDocument(), self.User())

        assert r._present == set()
        assert r._not_present == set()
        assert not r

        r.add('role1')
        assert r._present == {'role1'}
        assert r._not_present == set()
        assert r

        r.discard('role1')
        assert r._present == set()
        assert r._not_present == {'role1'}
        assert not r

        r.update({'role2', 'role3'})
        assert r._present == {'role2', 'role3'}
        assert r._not_present == {'role1'}
        assert r

        r.add('role1')
        assert r._present == {'role1', 'role2', 'role3'}
        assert r._not_present == set()
        assert r

        r.remove('role2')
        assert r._present == {'role1', 'role3'}
        assert r._not_present == {'role2'}
        assert r

    def test_set_operations(self):
        """Confirm we support common set operations."""
        doc = self.Document()
        user = self.User()
        r = LazyRoleSet(doc, user, {'all', 'auth'})
        assert r == {'all', 'auth'}
        assert r == LazyRoleSet(doc, user, {'all', 'auth'})
        assert r != LazyRoleSet(doc, None, {'all', 'auth'})
        assert len(r) == 2
        assert 'all' in r
        assert 'random' not in r
        assert r != {'all', 'anon'}
        assert r.isdisjoint({'random'})
        assert r.issubset({'all', 'auth', 'owner'})
        assert r <= {'all', 'auth', 'owner'}
        assert r < {'all', 'auth', 'owner'}
        assert not r < {'all', 'auth'}
        assert r.issuperset({'all'})
        assert r >= {'all'}
        assert r > {'all'}
        assert not r > {'all', 'auth'}
        assert r.union({'owner'}) == LazyRoleSet(doc, user, {'all', 'auth', 'owner'})
        assert r | {'owner'} == LazyRoleSet(doc, user, {'all', 'auth', 'owner'})
        assert r.union({'owner'}) == {'all', 'auth', 'owner'}
        assert r | {'owner'} == {'all', 'auth', 'owner'}
        assert r.intersection({'all'}) == LazyRoleSet(doc, user, {'all'})
        assert r & {'all'} == LazyRoleSet(doc, user, {'all'})
        assert r.intersection({'all'}) == {'all'}
        assert r & {'all'} == {'all'}

        r2 = r.copy()
        assert r is not r2
        assert r2 is not r
        assert r == r2
        assert r2 == r

    def test_has_any(self):
        """Test the has_any method"""
        doc = self.Document()
        user = self.User()
        doc.user = user
        r = LazyRoleSet(doc, user, {'all', 'auth'})

        # At the start, the access flag is false and the cache sets are not populated
        assert r._present == {'all', 'auth'}
        assert not r._not_present

        # has_any accepts any iterable. We'll be using a different type in each call

        # has_any works with pre-cached roles
        assert r.has_any({'all'}) is True

        # Bogus roles are not present and get populated into the internal cache
        assert r.has_any(['bogus1', 'bogus2']) is False
        assert r._not_present == {'bogus1', 'bogus2'}

        # While `owner` is present, it's not yet in the cache. The cache is scanned
        # first, before lazy sources are evaluated. Use frozenset just to demonstrate
        # that it's accepted; it has no impact on the test.
        assert r.has_any(frozenset(('owner', 'all'))) is True
        assert 'owner' not in r._present

        # When non-cached roles are asked for, lazy sources are evaluated
        # This test requires an ordered iterable ('owner' must be first)
        assert r.has_any(('owner', 'also-bogus')) is True
        assert 'owner' in r._present
        # After a match none of the other options are evaluated (needs ordered sequence)
        assert 'also-bogus' not in r._not_present
        # Until it comes up for an actual scan
        assert r.has_any({'also-bogus'}) is False
        assert 'also-bogus' in r._not_present

    def test_lazyroleset(self):
        d = self.Document()
        u1 = self.User()
        u2 = self.User()
        d.user = u1

        # At the start, the access flags are false
        assert d.accessed_user is False
        assert d.accessed_userlist is False

        # Standard roles work
        assert 'all' in d.roles_for(u1)
        assert 'all' in d.roles_for(u2)

        # 'owner' relationships are untouched when testing for standard roles
        assert d.accessed_user is False
        assert d.accessed_userlist is False

        # The 'owner' role is granted for the user present in d.user
        assert 'owner' in d.roles_for(u1)

        # Confirm which relationship was examined
        assert d.accessed_user is True
        assert d.accessed_userlist is False  # type: ignore[unreachable]

        # The 'owner' role is not granted for a user not present in
        # both relationships.
        assert 'owner' not in d.roles_for(u2)

        # Both relationships have been examined this time
        assert d.accessed_user is True
        assert d.accessed_userlist is True

        # Now test the other relationship for granting a role
        d.user = None
        d.userlist = [u2]

        # Confirm flags were reset
        assert d.accessed_user is False
        assert d.accessed_userlist is False

        # The 'owner' role is granted for the user present in d.userlist
        assert 'owner' not in d.roles_for(u1)
        assert 'owner' in d.roles_for(u2)

        # We know it's via 'userlist' because the flag is set. Further,
        # 'user' was also examined because it has prority (`granted_by` is ordered)
        assert d.accessed_user is True
        assert d.accessed_userlist is True

    def test_inspectable_lazyroleset(self):
        d = self.Document()
        u1 = self.User()
        u2 = self.User()
        d.user = u1

        # At the start, the access flags are false
        assert d.accessed_user is False
        assert d.accessed_userlist is False

        # Constructing an inspectable set does not enumerate roles
        r1 = InspectableSet(d.roles_for(u1))
        assert d.accessed_user is False
        assert d.accessed_userlist is False

        # However, accessing the role does
        assert r1.owner is True
        assert d.accessed_user is True
        assert d.accessed_userlist is False  # type: ignore[unreachable]

        # Reset and try the other relationship
        d.user = None
        d.userlist = [u2]
        r2 = InspectableSet(d.roles_for(u2))
        assert d.accessed_user is False
        assert d.accessed_userlist is False
        assert r2.owner is True
        assert d.accessed_user is True
        assert d.accessed_userlist is True

    def test_offered_roles(self):
        """
        Test that an object with an `offered_roles` method is a RoleGrantABC type
        """
        role_membership = RoleMembership()
        assert issubclass(RoleMembership, RoleGrantABC)
        assert isinstance(role_membership, RoleGrantABC)
