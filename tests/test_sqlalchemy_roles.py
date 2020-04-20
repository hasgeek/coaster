# -*- coding: utf-8 -*-

from __future__ import unicode_literals

import json
import unittest

from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm.collections import (
    attribute_mapped_collection,
    column_mapped_collection,
)

from flask import Flask

from coaster.db import db
from coaster.sqlalchemy import (
    BaseMixin,
    BaseNameMixin,
    DynamicAssociationProxy,
    LazyRoleSet,
    RoleAccessProxy,
    RoleMixin,
    UuidMixin,
    declared_attr_roles,
    with_roles,
)
from coaster.utils import InspectableSet

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)


# --- Models ------------------------------------------------------------------


class DeclaredAttrMixin(object):
    # with_roles can be used within a declared attr
    @declared_attr
    def mixed_in1(cls):
        return with_roles(db.Column(db.Unicode(250)), rw={'owner'})

    # declared_attr_roles is deprecated since 0.6.1. Use with_roles
    # as the outer decorator now. It remains here for the test case.
    @declared_attr
    @declared_attr_roles(rw={'owner', 'editor'}, read={'all'})
    def mixed_in2(cls):
        return db.Column(db.Unicode(250))

    # with_roles can also be used outside a declared attr
    @with_roles(rw={'owner'})
    @declared_attr
    def mixed_in3(cls):
        return db.Column(db.Unicode(250))

    # A regular column from the mixin
    mixed_in4 = db.Column(db.Unicode(250))
    mixed_in4 = with_roles(mixed_in4, rw={'owner'})


class RoleModel(DeclaredAttrMixin, RoleMixin, db.Model):
    __tablename__ = 'role_model'

    # Approach one, declare roles in advance.
    # 'all' is a special role that is always granted from the base class

    __roles__ = {'all': {'read': {'id', 'name', 'title'}}}

    __datasets__ = {
        'minimal': {'id', 'name', 'title'},
        'extra': {'id', 'name', 'title', 'mixed_in1'},
    }

    # Approach two, annotate roles on the attributes.
    # These annotations always add to anything specified in __roles__

    id = db.Column(db.Integer, primary_key=True)  # NOQA: A003
    name = with_roles(
        db.Column(db.Unicode(250)), rw={'owner'}
    )  # Specify read+write access

    title = with_roles(
        db.Column(db.Unicode(250)), write={'owner', 'editor'}
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
        roles = super(RoleModel, self).roles_for(actor, anchors)
        if 'owner-secret' in anchors:
            roles.add('owner')  # Grant owner role
        return roles


class AutoRoleModel(RoleMixin, db.Model):
    __tablename__ = 'auto_role_model'

    # This model doesn't specify __roles__. It only uses with_roles.
    # It should still work
    id = db.Column(db.Integer, primary_key=True)  # NOQA: A003
    with_roles(id, read={'all'})

    name = db.Column(db.Unicode(250))
    with_roles(name, rw={'owner'}, read={'all'})


class BaseModel(BaseMixin, db.Model):
    __tablename__ = 'base_model'


class UuidModel(UuidMixin, BaseMixin, db.Model):
    __tablename__ = 'uuid_model'


class RelationshipChild(BaseNameMixin, db.Model):
    __tablename__ = 'relationship_child'

    parent_id = db.Column(None, db.ForeignKey('relationship_parent.id'), nullable=False)

    __roles__ = {'all': {'read': {'name', 'title', 'parent'}}}
    __datasets__ = {
        'primary': {'name', 'title', 'parent'},
        'related': {'name', 'title'},
    }


class RelationshipParent(BaseNameMixin, db.Model):
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


class RoleGrantMany(BaseMixin, db.Model):
    """Test model for granting roles to users in many-to-one and many-to-many relationships"""

    __tablename__ = 'role_grant_many'

    __roles__ = {
        'primary_role': {'granted_by': ['primary_users']},
        'secondary_role': {'granted_by': ['secondary_users']},
    }


class RoleUser(BaseMixin, db.Model):
    """Test model represent a user who has roles"""

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


class RoleGrantOne(BaseMixin, db.Model):
    """Test model for granting roles to users in a one-to-many relationship"""

    __tablename__ = 'role_grant_one'

    user_id = db.Column(None, db.ForeignKey('role_user.id'))
    user = with_roles(db.relationship(RoleUser), grants={'creator'})


class RoleGrantSynonym(BaseMixin, db.Model):
    """Test model for granting roles to synonyms"""

    __tablename__ = 'role_grant_synonym'

    # Base column has roles defined
    datacol = with_roles(db.Column(db.UnicodeText()), rw={'owner'})
    # Synonym has no roles defined, so it acquires from the target
    altcol_unroled = db.synonym('datacol')
    # However, when the synonym has roles defined, these override the target's
    altcol_roled = with_roles(db.synonym('datacol'), read={'all'})


# --- Utilities ---------------------------------------------------------------


class JsonEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, RoleAccessProxy):
            return dict(o)
        return super(JsonEncoder, self).default(o)


# --- Tests -------------------------------------------------------------------


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
        self.assertEqual(RoleMixin.__roles__, {})

    def test_role_dict(self):
        """Roles may be declared multiple ways and they all work"""
        self.assertEqual(
            RoleModel.__roles__,
            {
                'all': {
                    'call': {'hello'},
                    'read': {'id', 'name', 'title', 'mixed_in2'},
                },
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
            },
        )

    def test_autorole_dict(self):
        """A model without __roles__, using only with_roles, also works as expected"""
        self.assertEqual(
            AutoRoleModel.__roles__,
            {
                'all': {'read': {'id', 'name'}},
                'owner': {'read': {'name'}, 'write': {'name'}},
            },
        )

    def test_basemixin_roles(self):
        """A model with BaseMixin by default exposes nothing to the 'all' role"""
        self.assertEqual(BaseModel.__roles__.get('all', {}).get('read', set()), set())

    def test_uuidmixin_roles(self):
        """
        A model with UuidMixin provides 'all' read access to uuid, uuid_hex, buid and suuid
        """
        self.assertLessEqual(
            {'uuid', 'uuid_hex', 'buid', 'suuid'}, UuidModel.__roles__['all']['read']
        )

    def test_roles_for_anon(self):
        """An anonymous actor should have 'all' and 'anon' roles"""
        rm = RoleModel(name='test', title='Test')
        roles = rm.roles_for(actor=None)
        self.assertEqual(roles, {'all', 'anon'})

    def test_roles_for_actor(self):
        """An actor (but anchors) must have 'all' and 'auth' roles"""
        rm = RoleModel(name='test', title='Test')
        roles = rm.roles_for(actor=1)
        self.assertEqual(roles, {'all', 'auth'})
        roles = rm.roles_for(anchors=(1,))
        self.assertEqual(roles, {'all', 'anon'})

    def test_roles_for_owner(self):
        """Presenting the correct anchor grants 'owner' role"""
        rm = RoleModel(name='test', title='Test')
        roles = rm.roles_for(anchors=('owner-secret',))
        self.assertEqual(roles, {'all', 'anon', 'owner'})

    def test_current_roles(self):
        """Current roles are available"""
        rm = RoleModel(name='test', title='Test')
        roles = rm.current_roles
        self.assertEqual(roles, {'all', 'anon'})
        self.assertTrue(roles.all)
        self.assertTrue(roles.anon)
        self.assertFalse(roles.owner)

    def test_access_for_syntax(self):
        """access_for can be called with either roles or actor for identical outcomes"""
        rm = RoleModel(name='test', title='Test')
        proxy1 = rm.access_for(roles=rm.roles_for(actor=None))
        proxy2 = rm.access_for(actor=None)
        self.assertEqual(proxy1, proxy2)

    def test_access_for_all(self):
        """All actors should be able to read some fields"""
        arm = AutoRoleModel(name='test')
        proxy = arm.access_for(actor=None)
        self.assertEqual(len(proxy), 2)
        self.assertEqual(set(proxy.keys()), {'id', 'name'})

    def test_current_access(self):
        """Current access is available"""
        arm = AutoRoleModel(name='test')
        proxy = arm.current_access()
        self.assertEqual(len(proxy), 2)
        self.assertEqual(set(proxy.keys()), {'id', 'name'})

        roles = proxy.current_roles
        self.assertEqual(roles, {'all', 'anon'})
        self.assertTrue(roles.all)
        self.assertTrue(roles.anon)
        self.assertFalse(roles.owner)

    def test_attr_dict_access(self):
        """Proxies support identical attribute and dictionary access"""
        rm = RoleModel(name='test', title='Test')
        proxy = rm.access_for(actor=None)
        self.assertIn('name', proxy)
        self.assertEqual(proxy.name, 'test')
        self.assertEqual(proxy['name'], 'test')

    def test_diff_roles(self):
        """Different roles get different access"""
        rm = RoleModel(name='test', title='Test')
        proxy1 = rm.access_for(roles={'all'})
        proxy2 = rm.access_for(roles={'owner'})
        proxy3 = rm.access_for(roles={'all', 'owner'})
        self.assertEqual(set(proxy1), {'id', 'name', 'title', 'mixed_in2'})
        self.assertEqual(
            set(proxy2),
            {'name', 'defval', 'mixed_in1', 'mixed_in2', 'mixed_in3', 'mixed_in4'},
        )
        self.assertEqual(
            set(proxy3),
            {
                'id',
                'name',
                'title',
                'defval',
                'mixed_in1',
                'mixed_in2',
                'mixed_in3',
                'mixed_in4',
            },
        )

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

    def test_write_without_read(self):
        """A proxy may allow writes without allowing reads"""
        rm = RoleModel(name='test', title='Test')
        proxy = rm.access_for(roles={'owner'})
        self.assertEqual(rm.title, 'Test')
        proxy.title = 'Changed'
        self.assertEqual(rm.title, 'Changed')
        proxy['title'] = 'Changed again'
        self.assertEqual(rm.title, 'Changed again')
        with self.assertRaises(AttributeError):
            proxy.title
        with self.assertRaises(KeyError):
            proxy['title']

    def test_no_write(self):
        """A proxy will disallow writes if the role doesn't permit it"""
        rm = RoleModel(name='test', title='Test')
        proxy = rm.access_for(roles={'editor'})
        self.assertEqual(rm.title, 'Test')
        # 'editor' has permission to write to 'title'
        proxy.title = 'Changed'
        self.assertEqual(rm.title, 'Changed')
        # 'editor' does not have permission to write to 'name'
        self.assertEqual(rm.name, 'test')
        with self.assertRaises(AttributeError):
            proxy.name = 'changed'
        with self.assertRaises(KeyError):
            proxy['name'] = 'changed'
        self.assertEqual(rm.name, 'test')

    def test_method_call(self):
        """Method calls are allowed as calling is just an alias for reading"""
        rm = RoleModel(name='test', title='Test')
        proxy1 = rm.access_for(roles={'all'})
        proxy2 = rm.access_for(roles={'owner'})
        self.assertEqual(proxy1.hello(), "Hello!")
        with self.assertRaises(AttributeError):
            proxy2.hello()
        with self.assertRaises(KeyError):
            proxy2['hello']()

    def test_dictionary_comparison(self):
        """A proxy can be compared with a dictionary"""
        rm = RoleModel(name='test', title='Test')
        proxy = rm.access_for(roles={'all'})
        self.assertEqual(
            proxy, {'id': None, 'name': 'test', 'title': 'Test', 'mixed_in2': None}
        )

    def test_bad_decorator(self):
        """Prevent with_roles from being used with a positional parameter"""
        with self.assertRaises(TypeError):

            @with_roles({'all'})
            def f():
                pass

    def test_access_for_roles_and_actor_or_anchors(self):
        """access_for accepts roles or actor/anchors, not both/all"""
        rm = RoleModel(name='test', title='Test')
        with self.assertRaises(TypeError):
            rm.access_for(roles={'all'}, actor=1)
        with self.assertRaises(TypeError):
            rm.access_for(roles={'all'}, anchors=('owner-secret',))
        with self.assertRaises(TypeError):
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
        assert json.loads(json.dumps(pchild, cls=JsonEncoder)) == {
            'name': "child",
            'title': "Child",
            'parent': {'name': "parent", 'title': "Parent"},
        }

        pparent = parent.access_for(roles={'all'}, datasets=('primary', 'related'))
        assert json.loads(json.dumps(pparent, cls=JsonEncoder)) == {
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

        assert o1.actors_with({'creator'}) == {u1}
        assert o2.actors_with({'creator'}) == {u2}

        assert m1.actors_with({'primary_role'}) == {u1}
        assert m2.actors_with({'primary_role'}) == {u2}
        assert m1.actors_with({'secondary_role'}) == {u1, u2}
        assert m2.actors_with({'secondary_role'}) == set()
        assert m1.actors_with({'primary_role', 'secondary_role'}) == {u1, u2}
        assert m2.actors_with({'primary_role', 'secondary_role'}) == {u2}

    def test_actors_with_invalid(self):
        m1 = RoleGrantMany()
        with self.assertRaises(ValueError):
            # Parameter can't be a string
            m1.actors_with('owner')

    def test_role_grant_synonyms(self):
        """Test that synonyms get independent access control"""
        rgs = RoleGrantSynonym(datacol='abc')
        assert rgs.datacol == 'abc'
        assert rgs.altcol_unroled == 'abc'
        assert rgs.altcol_roled == 'abc'

        owner_proxy = rgs.access_for(roles={'owner'})
        # datacol is present as it has owner read access defined
        assert 'datacol' in owner_proxy
        # altcol_unroled is not present as no roles were defined for it
        assert 'altcol_unroled' not in owner_proxy
        # altcol_roled had its own roles defined, and owner access was not in them
        assert 'altcol_roled' not in owner_proxy

        assert owner_proxy.datacol == 'abc'
        assert owner_proxy['datacol'] == 'abc'

        # The datacol column gives write access to the owner role
        owner_proxy.datacol = 'xyz'
        assert owner_proxy.datacol == 'xyz'

        # Confirm the unroled synonym isn't available in the proxy
        with self.assertRaises(AttributeError):
            owner_proxy.altcol_unroled = 'uvw'

        all_proxy = rgs.access_for(roles={'all'})
        assert 'datacol' not in all_proxy
        assert 'altcol_unroled' not in all_proxy
        assert 'altcol_roled' in all_proxy
        assert all_proxy.altcol_roled == 'xyz'

        # The altcol_roled synonym has only read access to the all role
        with self.assertRaises(AttributeError):
            all_proxy.altcol_roled = 'pqr'

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


class TestLazyRoleSet(unittest.TestCase):
    """Tests for LazyRoleSet, isolated from RoleMixin"""

    class EmptyDocument(RoleMixin):
        # Test LazyRoleSet without the side effects of roles defined in the document
        pass

    class Document(RoleMixin):
        _user = None
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

    class User(object):
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
        # Confirm we support common set operations
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
        assert d.accessed_userlist is False

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
        assert d.accessed_userlist is False

        # Reset and try the other relationship
        d.user = None
        d.userlist = [u2]
        r2 = InspectableSet(d.roles_for(u2))
        assert d.accessed_user is False
        assert d.accessed_userlist is False
        assert r2.owner is True
        assert d.accessed_user is True
        assert d.accessed_userlist is True
