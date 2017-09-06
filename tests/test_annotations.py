# -*- coding: utf-8 -*-

from __future__ import unicode_literals
import unittest
from sqlalchemy import inspect
from sqlalchemy.orm.attributes import NO_VALUE
from flask import Flask
from coaster.sqlalchemy import BaseMixin, UuidMixin
from coaster.annotations import immutable, cached
from coaster.db import db

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)


# --- Models ------------------------------------------------------------------

class ReferralTarget(BaseMixin, db.Model):
    __tablename__ = 'referral_target'
    pass


class IdOnly(BaseMixin, db.Model):
    __tablename__ = 'id_only'
    __uuid_primary_key__ = False

    is_regular = db.Column(db.Integer)
    is_immutable = immutable(db.Column(db.Integer))
    is_cached = cached(db.Column(db.Integer))

    # Make the raw column immutable, but allow changes via the relationship
    referral_target_id = immutable(db.Column(None, db.ForeignKey('referral_target.id'), nullable=True))
    referral_target = db.relationship(ReferralTarget)


class IdUuid(UuidMixin, BaseMixin, db.Model):
    __tablename__ = 'id_uuid'
    __uuid_primary_key__ = False

    is_regular = db.Column(db.Unicode(250))
    is_immutable = immutable(db.Column(db.Unicode(250)))
    is_cached = cached(db.Column(db.Unicode(250)))

    # Only block changes via the relationship; raw column remains mutable
    referral_target_id = db.Column(None, db.ForeignKey('referral_target.id'), nullable=True)
    referral_target = immutable(db.relationship(ReferralTarget))


class UuidOnly(UuidMixin, BaseMixin, db.Model):
    __tablename__ = 'uuid_only'
    __uuid_primary_key__ = True

    is_regular = db.Column(db.Unicode(250))
    is_immutable = immutable(db.Column(db.Unicode(250)))
    is_cached = cached(db.Column(db.Unicode(250)))

    # Make both raw column and relationship immutable
    referral_target_id = immutable(db.Column(None, db.ForeignKey('referral_target.id'), nullable=True))
    referral_target = immutable(db.relationship(ReferralTarget))


class PolymorphicParent(BaseMixin, db.Model):
    __tablename__ = 'polymorphic_parent'
    type = db.Column(db.Unicode(30), index=True)
    is_immutable = immutable(db.Column(db.Unicode(250)))
    also_immutable = immutable(db.Column(db.Unicode(250)))

    __mapper_args__ = {'polymorphic_on': type, 'polymorphic_identity': u'parent'}


class PolymorphicChild(PolymorphicParent):
    __tablename__ = 'polymorphic_child'
    id = db.Column(None, db.ForeignKey('polymorphic_parent.id', ondelete='CASCADE'), primary_key=True, nullable=False)
    # Redefining a column will keep existing annotations, even if not specified here
    also_immutable = db.Column(db.Unicode(250))
    __mapper_args__ = {'polymorphic_identity': u'child'}


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
            self.assertTrue(hasattr(model, '__annotations__'))
            self.assertTrue(hasattr(model, '__annotations_by_attr__'))

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

    def test_postload_immutability(self):
        i1 = IdOnly(is_regular=1, is_immutable=2, is_cached=3)
        i2 = IdUuid(is_regular='a', is_immutable='b', is_cached='c')
        i3 = UuidOnly(is_regular='x', is_immutable='y', is_cached='z')
        self.session.add_all([i1, i2, i3])
        self.session.commit()

        id1 = i1.id
        id2 = i2.id
        id3 = i3.id

        # Delete objects so SQLAlchemy's session cache can't populate fields from them
        del i1, i2, i3

        # Using `query.get` appears to ignore the `load_only` option,
        # so we use `query.filter_by`
        pi1 = IdOnly.query.options(db.load_only('id')).filter_by(id=id1).one()
        pi2 = IdUuid.query.options(db.load_only('id')).filter_by(id=id2).one()
        pi3 = UuidOnly.query.options(db.load_only('id')).filter_by(id=id3).one()

        # Confirm there is no value for is_immutable
        self.assertIs(inspect(pi1).attrs.is_immutable.loaded_value, NO_VALUE)
        self.assertIs(inspect(pi2).attrs.is_immutable.loaded_value, NO_VALUE)
        self.assertIs(inspect(pi3).attrs.is_immutable.loaded_value, NO_VALUE)

        # Immutable columns are immutable even if not loaded
        with self.assertRaises(AttributeError):
            pi1.is_immutable = 20
        with self.assertRaises(AttributeError):
            pi2.is_immutable = 'bb'
        with self.assertRaises(AttributeError):
            pi3.is_immutable = 'yy'

    def test_immutable_foreignkey(self):
        rt1 = ReferralTarget()
        rt2 = ReferralTarget()
        self.session.add_all([rt1, rt2])
        self.session.commit()  # This gets us rt1.id and rt2.id

        i1 = IdOnly(is_regular=1, is_immutable=2, is_cached=3)
        i2 = IdUuid(is_regular='a', is_immutable='b', is_cached='c')
        i3 = UuidOnly(is_regular='x', is_immutable='y', is_cached='z')

        i1.referral_target_id = rt1.id
        i2.referral_target_id = rt1.id
        i3.referral_target_id = rt1.id

        self.session.add_all([i1, i2, i3])
        self.session.commit()

        # Now try changing the value. i1 and i3 should block, i2 should allow
        with self.assertRaises(AttributeError):
            i1.referral_target_id = rt2.id
        i2.referral_target_id = rt2.id
        with self.assertRaises(AttributeError):
            i3.referral_target_id = rt2.id

    def test_immutable_relationship(self):
        rt1 = ReferralTarget()
        rt2 = ReferralTarget()
        self.session.add_all([rt1, rt2])
        self.session.commit()  # This gets us rt1.id and rt2.id

        i1 = IdOnly(is_regular=1, is_immutable=2, is_cached=3)
        i2 = IdUuid(is_regular='a', is_immutable='b', is_cached='c')
        i3 = UuidOnly(is_regular='x', is_immutable='y', is_cached='z')

        i1.referral_target_id = rt1.id
        i2.referral_target_id = rt1.id
        i3.referral_target_id = rt1.id

        self.session.add_all([i1, i2, i3])
        # If we don't commit and flush session cache, i2.referral_target
        # will be in NEVER_SET state and hence mutable
        self.session.commit()

        # Now try changing the value. i1 will not block because the
        # immutable validator only listens for direct changes, not
        # via relationships
        i1.referral_target = rt2
        with self.assertRaises(AttributeError):
            i2.referral_target = rt2
        with self.assertRaises(AttributeError):
            i3.referral_target = rt2

    def test_polymorphic_annotations(self):
        self.assertIn('is_immutable', PolymorphicParent.__annotations__['immutable'])
        self.assertIn('also_immutable', PolymorphicParent.__annotations__['immutable'])
        self.assertIn('is_immutable', PolymorphicChild.__annotations__['immutable'])
        self.assertIn('also_immutable', PolymorphicChild.__annotations__['immutable'])

    def test_polymorphic_immutable(self):
        parent = PolymorphicParent(is_immutable='a', also_immutable='b')
        child = PolymorphicChild(is_immutable='x', also_immutable='y')
        with self.assertRaises(AttributeError):
            parent.is_immutable = 'aa'
        with self.assertRaises(AttributeError):
            parent.also_immutable = 'bb'
        with self.assertRaises(AttributeError):
            child.is_immutable = 'xx'
        with self.assertRaises(AttributeError):
            child.also_immutable = 'yy'
