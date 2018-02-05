# -*- coding: utf-8 -*-

import unittest
from flask import Flask
from sqlalchemy.ext.declarative import declared_attr
from coaster.sqlalchemy import RoleMixin, with_roles, declared_attr_roles, BaseMixin, UuidMixin
from coaster.db import db

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)


# --- Models ------------------------------------------------------------------

class DeclaredAttrMixin(object):
    # The ugly way to work with declared_attr
    @declared_attr
    def mixed_in1(cls):
        return with_roles(db.Column(db.Unicode(250)),
            rw={'owner'})

    # The clean way to work with declared_attr
    @declared_attr
    @declared_attr_roles(rw={'owner', 'editor'}, read={'all'})
    def mixed_in2(cls):
        return db.Column(db.Unicode(250))

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

    @with_roles(call={'all'})  # 'call' is an alias for 'read', to be used for clarity
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


# --- Tests -------------------------------------------------------------------

class TestCoasterRoles(unittest.TestCase):
    app = app

    def setUp(self):
        self.ctx = self.app.test_request_context()
        self.ctx.push()
        db.create_all()
        self.session = db.session
        # SQLAlchemy doesn't fire mapper_configured events until the first time a mapping is used
        RoleModel()

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
        """A model with UuidMixin provides 'all' read access to uuid, url_id, buid and suuid"""
        self.assertLessEqual({'uuid', 'url_id', 'buid', 'suuid'}, UuidModel.__roles__['all']['read'])

    def test_roles_for_anon(self):
        """An anonymous user should have 'all' and 'anon' roles"""
        rm = RoleModel(name=u'test', title=u'Test')
        roles = rm.roles_for(user=None)
        self.assertEqual(roles, {'all', 'anon'})

    def test_roles_for_user(self):
        """A user or token must have 'all' and 'user' roles"""
        rm = RoleModel(name=u'test', title=u'Test')
        roles = rm.roles_for(user=1)
        self.assertEqual(roles, {'all', 'user'})
        roles = rm.roles_for(token=1)
        self.assertEqual(roles, {'all', 'user'})

    def test_roles_for_owner(self):
        """Presenting the correct owner token grants 'owner' role"""
        rm = RoleModel(name=u'test', title=u'Test')
        roles = rm.roles_for(token='owner-secret')
        self.assertEqual(roles, {'all', 'user', 'owner'})

    def test_access_for_syntax(self):
        """access_for can be called with either roles or user for identical outcomes"""
        rm = RoleModel(name=u'test', title=u'Test')
        proxy1 = rm.access_for(roles=rm.roles_for(user=None))
        proxy2 = rm.access_for(user=None)
        self.assertEqual(proxy1, proxy2)

    def test_access_for_all(self):
        """All users should be able to read some fields"""
        arm = AutoRoleModel(name=u'test')
        proxy = arm.access_for(user=None)
        self.assertEqual(len(proxy), 2)
        self.assertEqual(set(proxy.keys()), {'id', 'name'})

    def test_attr_dict_access(self):
        """Proxies support identical attribute and dictionary access"""
        rm = RoleModel(name=u'test', title=u'Test')
        proxy = rm.access_for(user=None)
        self.assertIn('name', proxy)
        self.assertEqual(proxy.name, u'test')
        self.assertEqual(proxy['name'], u'test')

    def test_diff_roles(self):
        """Different roles get different access"""
        rm = RoleModel(name=u'test', title=u'Test')
        proxy1 = rm.access_for(roles={'all'})
        proxy2 = rm.access_for(roles={'owner'})
        proxy3 = rm.access_for(roles={'all', 'owner'})
        self.assertEqual(set(proxy1), {'id', 'name', 'title', 'mixed_in2'})
        self.assertEqual(set(proxy2), {'name', 'defval', 'mixed_in1', 'mixed_in2', 'mixed_in3', 'mixed_in4'})
        self.assertEqual(set(proxy3),
            {'id', 'name', 'title', 'defval', 'mixed_in1', 'mixed_in2', 'mixed_in3', 'mixed_in4'})

    def test_write_without_read(self):
        """A proxy may allow writes without allowing reads"""
        rm = RoleModel(name=u'test', title=u'Test')
        proxy = rm.access_for(roles={'owner'})
        self.assertEqual(rm.title, u'Test')
        proxy.title = u'Changed'
        self.assertEqual(rm.title, u'Changed')
        with self.assertRaises(AttributeError):
            proxy.title
        with self.assertRaises(KeyError):
            proxy['title']

    def test_no_write(self):
        """A proxy will disallow writes if the role doesn't permit it"""
        rm = RoleModel(name=u'test', title=u'Test')
        proxy = rm.access_for(roles={'editor'})
        self.assertEqual(rm.title, u'Test')
        # 'editor' has permission to write to 'title'
        proxy.title = u'Changed'
        self.assertEqual(rm.title, u'Changed')
        # 'editor' does not have permission to write to 'name'
        self.assertEqual(rm.name, u'test')
        with self.assertRaises(AttributeError):
            proxy.name = u'changed'
        with self.assertRaises(KeyError):
            proxy['name'] = u'changed'
        self.assertEqual(rm.name, u'test')

    def test_method_call(self):
        """Method calls are allowed as calling is just an alias for reading"""
        rm = RoleModel(name=u'test', title=u'Test')
        proxy1 = rm.access_for(roles={'all'})
        proxy2 = rm.access_for(roles={'owner'})
        self.assertEqual(proxy1.hello(), "Hello!")
        with self.assertRaises(AttributeError):
            proxy2.hello()
        with self.assertRaises(KeyError):
            proxy2['hello']()

    def test_dictionary_comparison(self):
        """A proxy can be compared with a dictionary"""
        rm = RoleModel(name=u'test', title=u'Test')
        proxy = rm.access_for(roles={'all'})
        self.assertEqual(proxy,
            {'id': None, 'name': u'test', 'title': u'Test', 'mixed_in2': None}
            )

    def test_bad_decorator(self):
        """Prevent with_roles from being used with a positional parameter"""
        with self.assertRaises(TypeError):
            @with_roles({'all'})
            def foo():
                pass

    def test_roles_for_user_and_token(self):
        """roles_for accepts user or token, not both"""
        rm = RoleModel(name=u'test', title=u'Test')
        with self.assertRaises(TypeError):
            rm.roles_for(user=1, token='owner-secret')

    def test_access_for_roles_and_user_or_token(self):
        """access_for accepts roles or user/token, not both/all"""
        rm = RoleModel(name=u'test', title=u'Test')
        with self.assertRaises(TypeError):
            rm.access_for(roles={'all'}, user=1)
        with self.assertRaises(TypeError):
            rm.access_for(roles={'all'}, token='owner-secret')
        with self.assertRaises(TypeError):
            rm.access_for(roles={'all'}, user=1, token='owner-secret')
