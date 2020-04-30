# -*- coding: utf-8 -*-

import unittest

from coaster.db import db
from coaster.sqlalchemy import BaseMixin

# We have two sample models and two registered items to test that
# the registry is unique to each model and is not a global registry
# in the base class.


# Sample model 1
class RegistryTest1(BaseMixin, db.Model):
    __tablename__ = 'registry_test1'


# Sample model 2
class RegistryTest2(BaseMixin, db.Model):
    __tablename__ = 'registry_test2'


# Sample registered item (form or view) 1
class RegisteredItem1(object):
    def __init__(self, obj=None):
        self.obj = obj


# Sample registered item 2
@RegistryTest2.views('test')
class RegisteredItem2(object):
    def __init__(self, obj=None):
        self.obj = obj


# Sample registered item 3
@RegistryTest1.features('is1')
@RegistryTest2.features()
def is1(obj):
    return isinstance(obj, RegistryTest1)


RegistryTest1.views.test = RegisteredItem1


class TestRegistry(unittest.TestCase):
    def test_access_item_from_class(self):
        """Registered items are available from the model class"""
        assert RegistryTest1.views.test is RegisteredItem1
        assert RegistryTest2.views.test is RegisteredItem2
        assert RegistryTest1.views.test is not RegisteredItem2
        assert RegistryTest2.views.test is not RegisteredItem1
        assert RegistryTest1.features.is1 is is1
        assert RegistryTest2.features.is1 is is1

    def test_access_item_class_from_instance(self):
        """Registered items are available from the model instance"""
        r1 = RegistryTest1()
        r2 = RegistryTest2()
        # When accessed from the instance, we get a partial that resembles
        # the wrapped item, but is not the item itself.
        assert r1.views.test is not RegisteredItem1
        assert r1.views.test.func is RegisteredItem1
        assert r2.views.test is not RegisteredItem2
        assert r2.views.test.func is RegisteredItem2
        assert r1.features.is1 is not is1
        assert r1.features.is1.func is is1
        assert r2.features.is1 is not is1
        assert r2.features.is1.func is is1

    def test_access_item_instance_from_instance(self):
        """Registered items can be instantiated from the model instance"""
        r1 = RegistryTest1()
        r2 = RegistryTest2()
        i1 = r1.views.test()
        i2 = r2.views.test()

        assert isinstance(i1, RegisteredItem1)
        assert isinstance(i2, RegisteredItem2)
        assert not isinstance(i1, RegisteredItem2)
        assert not isinstance(i2, RegisteredItem1)
        assert i1.obj is r1
        assert i2.obj is r2
        assert i1.obj is not r2
        assert i2.obj is not r1

    def test_features(self):
        """The features registry can be used for feature tests"""
        r1 = RegistryTest1()
        r2 = RegistryTest2()

        assert r1.features.is1() is True
        assert r2.features.is1() is False
