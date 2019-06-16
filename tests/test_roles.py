# -*- coding: utf-8 -*-

from __future__ import unicode_literals
import unittest
from flask import Flask
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm.collections import mapped_collection, attribute_mapped_collection, column_mapped_collection
from coaster.sqlalchemy import (RoleMixin, RoleAccessProxy, with_roles, declared_attr_roles,
    BaseMixin, BaseNameMixin, UuidMixin)
from coaster.db import db

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)


# --- Models ------------------------------------------------------------------

class DeclaredAttrMixin(object):
    # with_roles can be used within a declared attr
    @declared_attr
    def mixed_in1(cls):
        return with_roles(db.Column(db.Unicode(250)),
            rw={'owner'})

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

    __roles__ = {
        'all': {
            'read': {'id', 'name', 'title'}
            }
        }

    # Approach two, annotate roles on the attributes.
    # These annotations always add to anything specified in __roles__

    id = db.Column(db.Integer, primary_key=True)
    name = with_roles(db.Column(db.Unicode(250)),
        rw={'owner'})  # Specify read+write access

    title = with_roles(db.Column(db.Unicode(250)),
        write={'owner', 'editor'})  # Grant 'owner' and 'editor' write but not read access

    defval = with_roles(db.deferred(db.Column(db.Unicode(250))),
        rw={'owner'})

    @with_roles(call={'all'})  # 'call' grants call access to the decorated method
    def hello(self):
        return "Hello!"

    # Your model is responsible for granting roles given an actor or anchors
    # (an iterable). The format for anchors is not specified by RoleMixin.

    def roles_for(self, actor=None, anchors=()):
        # Calling super give us a result set with the standard roles
        result = super(RoleModel, self).roles_for(actor, anchors)
        if 'owner-secret' in anchors:
            result.add('owner')  # Grant owner role
        return result


class AutoRoleModel(RoleMixin, db.Model):
    __tablename__ = 'auto_role_model'

    # This model doesn't specify __roles__. It only uses with_roles.
    # It should still work
    id = db.Column(db.Integer, primary_key=True)
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

    __roles__ = {
        'all': {
            'read': {'name', 'title', 'parent'},
            }
        }


class RelationshipParent(BaseNameMixin, db.Model):
    __tablename__ = 'relationship_parent'

    children_list = db.relationship(RelationshipChild, backref='parent')
    children_set = db.relationship(RelationshipChild, collection_class=set)
    children_dict_attr = db.relationship(RelationshipChild,
        collection_class=attribute_mapped_collection('name'))
    children_dict_column = db.relationship(RelationshipChild,
        collection_class=column_mapped_collection(RelationshipChild.name))

    __roles__ = {
        'all': {
            'read': {'name', 'title', 'children_list', 'children_set',
                'children_dict_attr', 'children_dict_column'},
            }
        }


# --- Tests -------------------------------------------------------------------

class TestCoasterRoles(unittest.TestCase):
    app = app

    def setUp(self):
        self.ctx = self.app.test_request_context()
        self.ctx.push()
        db.create_all()
        self.session = db.session
        # SQLAlchemy doesn't fire mapper_configured events until the first time a mapping is used,
        # or configuration is explicitly requested
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
        self.assertEqual(RoleModel.__roles__, {
            'all': {
                'call': {'hello', },
                'read': {'id', 'name', 'title', 'mixed_in2'},
                },
            'editor': {
                'read': {'mixed_in2'},
                'write': {'title', 'mixed_in2'},
                },
            'owner': {
                'read': {'name', 'defval', 'mixed_in1', 'mixed_in2', 'mixed_in3', 'mixed_in4'},
                'write': {'name', 'title', 'defval', 'mixed_in1', 'mixed_in2', 'mixed_in3', 'mixed_in4'},
                },
            })

    def test_autorole_dict(self):
        """A model without __roles__, using only with_roles, also works as expected"""
        self.assertEqual(AutoRoleModel.__roles__, {
            'all': {
                'read': {'id', 'name'},
                },
            'owner': {
                'read': {'name'},
                'write': {'name'},
                },
            })

    def test_basemixin_roles(self):
        """A model with BaseMixin by default exposes nothing to the 'all' role"""
        self.assertEqual(BaseModel.__roles__.get('all', {}).get('read', set()), set())

    def test_uuidmixin_roles(self):
        """A model with UuidMixin provides 'all' read access to uuid, huuid, buid and suuid"""
        self.assertLessEqual({'uuid', 'huuid', 'buid', 'suuid'}, UuidModel.__roles__['all']['read'])

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
        self.assertEqual(set(proxy2), {'name', 'defval', 'mixed_in1', 'mixed_in2', 'mixed_in3', 'mixed_in4'})
        self.assertEqual(set(proxy3),
            {'id', 'name', 'title', 'defval', 'mixed_in1', 'mixed_in2', 'mixed_in3', 'mixed_in4'})

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
        self.assertEqual(proxy,
            {'id': None, 'name': 'test', 'title': 'Test', 'mixed_in2': None}
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
