# -*- coding: utf-8 -*-

import unittest
from flask import Flask
from coaster.sqlalchemy import BaseMixin, UuidMixin
from coaster.annotations import immutable, cached
from coaster.db import db

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)


# --- Models ------------------------------------------------------------------

class IdOnly(BaseMixin, db.Model):
    __tablename__ = 'id_only'
    __uuid_primary_key__ = False

    is_regular = db.Column(db.Integer)
    is_immutable = immutable(db.Column(db.Integer))
    is_cached = cached(db.Column(db.Integer))


class IdUuid(UuidMixin, BaseMixin, db.Model):
    __tablename__ = 'id_uuid'
    __uuid_primary_key__ = False

    is_regular = db.Column(db.Unicode(250))
    is_immutable = immutable(db.Column(db.Unicode(250)))
    is_cached = cached(db.Column(db.Unicode(250)))


class UuidOnly(UuidMixin, BaseMixin, db.Model):
    __tablename__ = 'uuid_only'
    __uuid_primary_key__ = True

    is_regular = db.Column(db.Unicode(250))
    is_immutable = immutable(db.Column(db.Unicode(250)))
    is_cached = cached(db.Column(db.Unicode(250)))


# --- Tests -------------------------------------------------------------------

class TestCoasterAnnotations(unittest.TestCase):
    app = app

    def setUp(self):
        self.ctx = self.app.test_request_context()
        self.ctx.push()
        db.create_all()
        self.session = db.session
        # SQLAlchemy doesn't fire mapper_configured events until the first time a mapping is used
        IdOnly()

    def tearDown(self):
        self.session.rollback()
        db.drop_all()
        self.ctx.pop()

    def test_has_annotations(self):
        for model in (IdOnly, IdUuid, UuidOnly):
            self.assertTrue(hasattr(IdOnly, '__annotations__'))
            self.assertTrue(hasattr(IdOnly, '__annotations_by_attr__'))

    def test_annotation_in_annotations(self):
        for model in (IdOnly, IdUuid, UuidOnly):
            for annotation in (immutable, cached):
                self.assertIn(annotation.name, model.__annotations__)

    def test_attr_in_annotations(self):
        for model in (IdOnly, IdUuid, UuidOnly):
            self.assertIn('is_immutable', model.__annotations__['immutable'])
            self.assertIn('is_cached', model.__annotations__['cached'])

    def test_base_attrs_in_annotations(self):
        for model in (IdOnly, IdUuid, UuidOnly):
            for attr in ('created_at', 'id'):
                self.assertIn(attr, model.__annotations__['immutable'])
        self.assertIn('uuid', IdUuid.__annotations__['immutable'])

    def test_init_immutability(self):
        i1 = IdOnly(is_regular=1, is_immutable=2, is_cached=3)
        i2 = IdUuid(is_regular='a', is_immutable='b', is_cached='c')
        i3 = UuidOnly(is_regular='x', is_immutable='y', is_cached='z')

        # Regular columns work as usual
        self.assertEqual(i1.is_regular, 1)
        self.assertEqual(i2.is_regular, 'a')
        self.assertEqual(i3.is_regular, 'x')
        # Immutable columns gets an initial value
        self.assertEqual(i1.is_immutable, 2)
        self.assertEqual(i2.is_immutable, 'b')
        self.assertEqual(i3.is_immutable, 'y')
        # No special behaviour for cached columns, despite the annotation
        self.assertEqual(i1.is_cached, 3)
        self.assertEqual(i2.is_cached, 'c')
        self.assertEqual(i3.is_cached, 'z')

        # Regular columns are mutable
        i1.is_regular = 10
        i2.is_regular = 'aa'
        i3.is_regular = 'xx'
        self.assertEqual(i1.is_regular, 10)
        self.assertEqual(i2.is_regular, 'aa')
        self.assertEqual(i3.is_regular, 'xx')

        # Immutable columns are immutable
        with self.assertRaises(AttributeError):
            i1.is_immutable = 20
        with self.assertRaises(AttributeError):
            i2.is_immutable = 'bb'
        with self.assertRaises(AttributeError):
            i3.is_immutable = 'yy'

        # No special behaviour for cached columns, despite the annotation
        i1.is_cached = 30
        i2.is_cached = 'cc'
        i3.is_cached = 'zz'
        self.assertEqual(i1.is_cached, 30)
        self.assertEqual(i2.is_cached, 'cc')
        self.assertEqual(i3.is_cached, 'zz')

    def test_postinit_immutability(self):
        # Make instances with no initial value
        i1 = IdOnly()
        i2 = IdUuid()
        i3 = UuidOnly()

        # Regular columns can be set
        i1.is_regular = 1
        i2.is_regular = 'a'
        i3.is_regular = 'x'

        # Immutable columns can be set the first time
        i1.is_immutable = 2
        i2.is_immutable = 'b'
        i3.is_immutable = 'y'

        # Cached columns behave like regular columns
        i1.is_cached = 3
        i2.is_cached = 'c'
        i3.is_cached = 'z'

        # Regular columns work as usual
        self.assertEqual(i1.is_regular, 1)
        self.assertEqual(i2.is_regular, 'a')
        self.assertEqual(i3.is_regular, 'x')
        # Immutable columns accept the initial value
        self.assertEqual(i1.is_immutable, 2)
        self.assertEqual(i2.is_immutable, 'b')
        self.assertEqual(i3.is_immutable, 'y')
        # No special behaviour for cached columns, despite the annotation
        self.assertEqual(i1.is_cached, 3)
        self.assertEqual(i2.is_cached, 'c')
        self.assertEqual(i3.is_cached, 'z')

        # Regular columns are mutable
        i1.is_regular = 10
        i2.is_regular = 'aa'
        i3.is_regular = 'xx'
        self.assertEqual(i1.is_regular, 10)
        self.assertEqual(i2.is_regular, 'aa')
        self.assertEqual(i3.is_regular, 'xx')

        # Immutable columns are immutable
        with self.assertRaises(AttributeError):
            i1.is_immutable = 20
        with self.assertRaises(AttributeError):
            i2.is_immutable = 'bb'
        with self.assertRaises(AttributeError):
            i3.is_immutable = 'yy'

        # No special behaviour for cached columns, despite the annotation
        i1.is_cached = 30
        i2.is_cached = 'cc'
        i3.is_cached = 'zz'
        self.assertEqual(i1.is_cached, 30)
        self.assertEqual(i2.is_cached, 'cc')
        self.assertEqual(i3.is_cached, 'zz')
