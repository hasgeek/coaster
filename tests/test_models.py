# -*- coding: utf-8 -*-

import unittest

import uuid
from time import sleep
from datetime import datetime, timedelta
from flask import Flask
from sqlalchemy import Column, Integer, Unicode, UniqueConstraint, ForeignKey, func
from sqlalchemy.orm import relationship, synonym
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import MultipleResultsFound
from coaster.sqlalchemy import (BaseMixin, BaseNameMixin, BaseScopedNameMixin,
    BaseIdNameMixin, BaseScopedIdMixin, BaseScopedIdNameMixin, JsonDict, failsafe_add, InvalidId,
    UuidMixin)
from coaster.utils import uuid2buid, uuid2suuid
from coaster.db import db


app1 = Flask(__name__)
app1.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
app1.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app2 = Flask(__name__)
app2.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql:///coaster_test'
app2.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app1)
db.init_app(app2)


# --- Models ------------------------------------------------------------------
class Container(BaseMixin, db.Model):
    __tablename__ = 'container'
    name = Column(Unicode(80), nullable=True)
    title = Column(Unicode(80), nullable=True)

    content = Column(Unicode(250))


class UnnamedDocument(BaseMixin, db.Model):
    __tablename__ = 'unnamed_document'
    container_id = Column(Integer, ForeignKey('container.id'))
    container = relationship(Container)

    content = Column(Unicode(250))


class NamedDocument(BaseNameMixin, db.Model):
    __tablename__ = 'named_document'
    reserved_names = [u'new']
    container_id = Column(Integer, ForeignKey('container.id'))
    container = relationship(Container)

    content = Column(Unicode(250))


class NamedDocumentBlank(BaseNameMixin, db.Model):
    __tablename__ = 'named_document_blank'
    __name_blank_allowed__ = True
    reserved_names = [u'new']
    container_id = Column(Integer, ForeignKey('container.id'))
    container = relationship(Container)

    content = Column(Unicode(250))


class ScopedNamedDocument(BaseScopedNameMixin, db.Model):
    __tablename__ = 'scoped_named_document'
    reserved_names = [u'new']
    container_id = Column(Integer, ForeignKey('container.id'))
    container = relationship(Container)
    parent = synonym('container')

    content = Column(Unicode(250))
    __table_args__ = (UniqueConstraint('container_id', 'name'),)


class IdNamedDocument(BaseIdNameMixin, db.Model):
    __tablename__ = 'id_named_document'
    container_id = Column(Integer, ForeignKey('container.id'))
    container = relationship(Container)

    content = Column(Unicode(250))


class ScopedIdDocument(BaseScopedIdMixin, db.Model):
    __tablename__ = 'scoped_id_document'
    container_id = Column(Integer, ForeignKey('container.id'))
    container = relationship(Container)
    parent = synonym('container')

    content = Column(Unicode(250))
    __table_args__ = (UniqueConstraint('container_id', 'url_id'),)


class ScopedIdNamedDocument(BaseScopedIdNameMixin, db.Model):
    __tablename__ = 'scoped_id_named_document'
    container_id = Column(Integer, ForeignKey('container.id'))
    container = relationship(Container)
    parent = synonym('container')

    content = Column(Unicode(250))
    __table_args__ = (UniqueConstraint('container_id', 'url_id'),)


class User(BaseMixin, db.Model):
    __tablename__ = 'user'
    username = Column(Unicode(80), nullable=False)


class MyData(db.Model):
    __tablename__ = 'my_data'
    id = Column(Integer, primary_key=True)
    data = Column(JsonDict)


class NonUuidKey(BaseMixin, db.Model):
    __tablename__ = 'non_uuid_key'
    __uuid_primary_key__ = False


class UuidKey(BaseMixin, db.Model):
    __tablename__ = 'uuid_key'
    __uuid_primary_key__ = True


class UuidForeignKey1(BaseMixin, db.Model):
    __tablename__ = 'uuid_foreign_key1'
    __uuid_primary_key__ = False
    uuidkey_id = Column(None, ForeignKey('uuid_key.id'))
    uuidkey = relationship(UuidKey)


class UuidForeignKey2(BaseMixin, db.Model):
    __tablename__ = 'uuid_foreign_key2'
    __uuid_primary_key__ = True
    uuidkey_id = Column(None, ForeignKey('uuid_key.id'))
    uuidkey = relationship(UuidKey)


class UuidIdName(BaseIdNameMixin, db.Model):
    __tablename__ = 'uuid_id_name'
    __uuid_primary_key__ = True


class UuidIdNameMixin(UuidMixin, BaseIdNameMixin, db.Model):
    __tablename__ = 'uuid_id_name_mixin'
    __uuid_primary_key__ = True


class UuidIdNameSecondary(UuidMixin, BaseIdNameMixin, db.Model):
    __tablename__ = 'uuid_id_name_secondary'
    __uuid_primary_key__ = False


class NonUuidMixinKey(UuidMixin, BaseMixin, db.Model):
    __tablename__ = 'non_uuid_mixin_key'
    __uuid_primary_key__ = False


class UuidMixinKey(UuidMixin, BaseMixin, db.Model):
    __tablename__ = 'uuid_mixin_key'
    __uuid_primary_key__ = True


class ProxiedDocument(BaseMixin, db.Model):
    __tablename__ = 'proxied_document'
    __roles__ = {
        'name': {
            'write': {'document_writer'},
            'read': {'document_reader'}
        },
        'title': {
            'write': {'document_writer'},
            'read': {'document_reader', 'title_reader'}
        },
        'content': {
            'write': {'document_writer'},
            'read': {'document_reader'}
        }
    }

    name = Column(Unicode(80), nullable=True)
    title = Column(Unicode(80), nullable=True)
    content = Column(Unicode(250))


# -- Tests --------------------------------------------------------------------

class TestCoasterModels(unittest.TestCase):
    app = app1

    def setUp(self):
        self.ctx = self.app.test_request_context()
        self.ctx.push()
        db.create_all()
        self.session = db.session

    def tearDown(self):
        self.session.rollback()
        db.drop_all()
        self.ctx.pop()

    def make_container(self):
        c = Container()
        self.session.add(c)
        return c

    def test_container(self):
        c = self.make_container()
        self.assertEqual(c.id, None)
        self.session.commit()
        self.assertEqual(c.id, 1)

    def test_timestamp(self):
        now1 = self.session.query(func.utcnow()).first()[0]
        # Start a new transaction so that NOW() returns a new value
        self.session.commit()
        # The db may not store microsecond precision, so sleep at least 1 second
        # to ensure adequate gap between operations
        sleep(1)
        c = self.make_container()
        self.session.commit()
        u = c.updated_at
        sleep(1)
        now2 = self.session.query(func.utcnow()).first()[0]
        self.session.commit()
        self.assertNotEqual(now1, c.created_at)
        self.assertTrue(now1 < c.created_at)
        self.assertTrue(now2 > c.created_at)
        sleep(1)
        c.content = u"updated"
        self.session.commit()
        self.assertNotEqual(c.updated_at, u)
        self.assertTrue(c.updated_at > now2)
        self.assertTrue(c.updated_at > c.created_at)
        self.assertTrue(c.updated_at > u)

    def test_unnamed(self):
        c = self.make_container()
        d = UnnamedDocument(content=u"hello", container=c)
        self.session.add(d)
        self.session.commit()
        self.assertEqual(c.id, 1)
        self.assertEqual(d.id, 1)

    def test_named(self):
        """Named documents have globally unique names."""
        c1 = self.make_container()
        # XXX: We don't know why, but this raises a non-Unicode string warning
        d1 = NamedDocument(title=u"Hello", content=u"World", container=c1)
        self.session.add(d1)
        self.session.commit()
        self.assertEqual(d1.name, u'hello')
        self.assertEqual(NamedDocument.get(u'hello'), d1)

        c2 = self.make_container()
        d2 = NamedDocument(title=u"Hello", content=u"Again", container=c2)
        self.session.add(d2)
        self.session.commit()
        self.assertEqual(d2.name, u'hello2')

        # test insert in BaseNameMixin's upsert
        d3 = NamedDocument.upsert(u'hello3', title=u'hello3', content=u'hello3')
        self.session.commit()
        d3_persisted = NamedDocument.get(u'hello3')
        self.assertEqual(d3_persisted, d3)
        self.assertEqual(d3_persisted.content, u'hello3')

        # test update in BaseNameMixin's upsert
        d4 = NamedDocument.upsert(u'hello3', title=u'hello4', content=u'hello4')
        d4.make_name()
        self.session.commit()
        d4_persisted = NamedDocument.get(u'hello4')
        self.assertEqual(d4_persisted, d4)
        self.assertEqual(d4_persisted.content, u'hello4')

        with self.assertRaises(TypeError) as insert_error:
            NamedDocument.upsert(u'invalid1', title=u'Invalid1', non_existent_field=u"I don't belong here.")
        self.assertEqual(TypeError, insert_error.expected)

        with self.assertRaises(TypeError) as update_error:
            NamedDocument.upsert(u'valid1', title=u'Valid1')
            self.session.commit()
            NamedDocument.upsert(u'valid1', title=u'Invalid1', non_existent_field=u"I don't belong here.")
            self.session.commit()
        self.assertEqual(TypeError, update_error.expected)

    # TODO: Versions of this test are required for BaseNameMixin,
    # BaseScopedNameMixin, BaseIdNameMixin and BaseScopedIdNameMixin
    # since they replicate code without sharing it. Only BaseNameMixin
    # is tested here.
    def test_named_blank_disallowed(self):
        c1 = self.make_container()
        d1 = NamedDocument(title=u"Index", name=u"", container=c1)
        d1.name = u""  # BaseNameMixin will always try to set a name. Explicitly blank it.
        self.session.add(d1)
        self.assertRaises(IntegrityError, self.session.commit)

    def test_named_blank_allowed(self):
        c1 = self.make_container()
        d1 = NamedDocumentBlank(title=u"Index", name=u"", container=c1)
        d1.name = u""  # BaseNameMixin will always try to set a name. Explicitly blank it.
        self.session.add(d1)
        self.assertEqual(d1.name, u"")

    def test_scoped_named(self):
        """Scoped named documents have names unique to their containers."""
        c1 = self.make_container()
        d1 = ScopedNamedDocument(title=u"Hello", content=u"World", container=c1)
        u = User(username=u'foo')
        self.session.add(d1)
        self.session.commit()
        self.assertEqual(ScopedNamedDocument.get(c1, u'hello'), d1)
        self.assertEqual(d1.name, u'hello')
        self.assertEqual(d1.permissions(user=u), set([]))
        self.assertEqual(d1.permissions(user=u, inherited=set(['view'])), set(['view']))

        d2 = ScopedNamedDocument(title=u"Hello", content=u"Again", container=c1)
        self.session.add(d2)
        self.session.commit()
        self.assertEqual(d2.name, u'hello2')

        c2 = self.make_container()
        d3 = ScopedNamedDocument(title=u"Hello", content=u"Once More", container=c2)
        self.session.add(d3)
        self.session.commit()
        self.assertEqual(d3.name, u'hello')

        # test insert in BaseScopedNameMixin's upsert
        d4 = ScopedNamedDocument.upsert(c1, u'hello4', title=u'Hello 4', content=u'scoped named doc')
        self.session.commit()
        d4_persisted = ScopedNamedDocument.get(c1, u'hello4')
        self.assertEqual(d4_persisted, d4)
        self.assertEqual(d4_persisted.content, u'scoped named doc')

        # test update in BaseScopedNameMixin's upsert
        d5 = ScopedNamedDocument.upsert(c1, u'hello4', container=c2, title=u'Hello5', content=u'scoped named doc')
        d5.make_name()
        self.session.commit()
        d5_persisted = ScopedNamedDocument.get(c2, u'hello5')
        self.assertEqual(d5_persisted, d5)
        self.assertEqual(d5_persisted.content, u'scoped named doc')

        with self.assertRaises(TypeError) as insert_error:
            ScopedNamedDocument.upsert(c1, u'invalid1', title=u'Invalid1', non_existent_field=u"I don't belong here.")
        self.assertEqual(TypeError, insert_error.expected)

        ScopedNamedDocument.upsert(c1, u'valid1', title=u'Valid1')
        self.session.commit()
        with self.assertRaises(TypeError) as update_error:
            ScopedNamedDocument.upsert(c1, u'valid1', title=u'Invalid1', non_existent_field=u"I don't belong here.")
            self.session.commit()
        self.assertEqual(TypeError, update_error.expected)

    def test_scoped_named_short_title(self):
        """Test the short_title method of BaseScopedNameMixin."""
        c1 = self.make_container()
        d1 = ScopedNamedDocument(title=u"Hello", content=u"World", container=c1)
        self.assertEqual(d1.short_title(), u"Hello")

        c1.title = u"Container"
        d1.title = u"Container Contained"
        self.assertEqual(d1.short_title(), u"Contained")

    def test_id_named(self):
        """Documents with a global id in the URL"""
        c1 = self.make_container()
        d1 = IdNamedDocument(title=u"Hello", content=u"World", container=c1)
        self.session.add(d1)
        self.session.commit()
        self.assertEqual(d1.url_name, u'1-hello')

        d2 = IdNamedDocument(title=u"Hello", content=u"Again", container=c1)
        self.session.add(d2)
        self.session.commit()
        self.assertEqual(d2.url_name, u'2-hello')

        c2 = self.make_container()
        d3 = IdNamedDocument(title=u"Hello", content=u"Once More", container=c2)
        self.session.add(d3)
        self.session.commit()
        self.assertEqual(d3.url_name, u'3-hello')

    def test_scoped_id(self):
        """Documents with a container-specific id in the URL"""
        c1 = self.make_container()
        d1 = ScopedIdDocument(content=u"Hello", container=c1)
        u = User(username="foo")
        self.session.add(d1)
        self.session.commit()
        self.assertEqual(ScopedIdDocument.get(c1, d1.url_id), d1)
        self.assertEqual(d1.permissions(user=u, inherited=set(['view'])), set(['view']))
        self.assertEqual(d1.permissions(user=u), set([]))

        d2 = ScopedIdDocument(content=u"New document", container=c1)
        self.session.add(d2)
        self.session.commit()
        self.assertEqual(d1.url_id, 1)
        self.assertEqual(d2.url_id, 2)

        c2 = self.make_container()
        d3 = ScopedIdDocument(content=u"Once More", container=c2)
        self.session.add(d3)
        self.session.commit()
        self.assertEqual(d3.url_id, 1)

        d4 = ScopedIdDocument(content=u"Third", container=c1)
        self.session.add(d4)
        self.session.commit()
        self.assertEqual(d4.url_id, 3)

    def test_scoped_id_named(self):
        """Documents with a container-specific id and name in the URL"""
        c1 = self.make_container()
        d1 = ScopedIdNamedDocument(title=u"Hello", content=u"World", container=c1)
        self.session.add(d1)
        self.session.commit()
        self.assertEqual(d1.url_name, u'1-hello')
        self.assertEqual(d1.url_name, d1.url_id_name)  # url_name is now an alias for url_id_name
        self.assertEqual(ScopedIdNamedDocument.get(c1, d1.url_id), d1)

        d2 = ScopedIdNamedDocument(title=u"Hello again", content=u"New name", container=c1)
        self.session.add(d2)
        self.session.commit()
        self.assertEqual(d2.url_name, u'2-hello-again')

        c2 = self.make_container()
        d3 = ScopedIdNamedDocument(title=u"Hello", content=u"Once More", container=c2)
        self.session.add(d3)
        self.session.commit()
        self.assertEqual(d3.url_name, u'1-hello')

        d4 = ScopedIdNamedDocument(title=u"Hello", content=u"Third", container=c1)
        self.session.add(d4)
        self.session.commit()
        self.assertEqual(d4.url_name, u'3-hello')

        # Queries work as well
        qd1 = ScopedIdNamedDocument.query.filter_by(container=c1, url_name=d1.url_name).first()
        self.assertEqual(qd1, d1)
        qd2 = ScopedIdNamedDocument.query.filter_by(container=c1, url_id_name=d2.url_id_name).first()
        self.assertEqual(qd2, d2)

    def test_scoped_id_without_parent(self):
        d1 = ScopedIdDocument(content=u"Hello")
        self.session.add(d1)
        self.assertRaises(IntegrityError, self.session.commit)
        self.session.rollback()
        d2 = ScopedIdDocument(content=u"Hello again")
        self.session.add(d2)
        self.assertRaises(IntegrityError, self.session.commit)

    def test_scoped_named_without_parent(self):
        d1 = ScopedNamedDocument(title=u"Hello", content=u"World")
        self.session.add(d1)
        self.assertRaises(IntegrityError, self.session.commit)
        self.session.rollback()
        d2 = ScopedIdNamedDocument(title=u"Hello", content=u"World")
        self.session.add(d2)
        self.assertRaises(IntegrityError, self.session.commit)

    def test_reserved_name(self):
        c = self.make_container()
        d1 = NamedDocument(container=c, title=u"New")
        # 'new' is reserved in the class definition. Also reserve new2 here and
        # confirm we get new3 for the name
        d1.make_name(reserved=[u'new2'])
        self.assertEqual(d1.name, u'new3')
        d2 = ScopedNamedDocument(container=c, title=u"New")
        # 'new' is reserved in the class definition. Also reserve new2 here and
        # confirm we get new3 for the name
        d2.make_name(reserved=[u'new2'])
        self.assertEqual(d2.name, u'new3')

        # Now test again after adding to session. Results should be identical
        self.session.add(d1)
        self.session.add(d2)
        self.session.commit()

        d1.make_name(reserved=[u'new2'])
        self.assertEqual(d1.name, u'new3')
        d2.make_name(reserved=[u'new2'])
        self.assertEqual(d2.name, u'new3')

    def test_has_timestamps(self):
        # Confirm that a model with multiple base classes between it and
        # TimestampMixin still has created_at and updated_at
        c = self.make_container()
        d = ScopedIdNamedDocument(title=u"Hello", content=u"World", container=c)
        self.session.add(d)
        self.session.commit()
        sleep(1)
        self.assertTrue(d.created_at is not None)
        self.assertTrue(d.updated_at is not None)
        updated_at = d.updated_at
        self.assertTrue(d.updated_at - d.created_at < timedelta(seconds=1))
        self.assertTrue(isinstance(d.created_at, datetime))
        self.assertTrue(isinstance(d.updated_at, datetime))
        d.title = u"Updated hello"
        self.session.commit()
        self.assertTrue(d.updated_at > updated_at)

    def test_url_for(self):
        d = UnnamedDocument(content=u"hello")
        self.assertEqual(d.url_for(), None)

    def test_jsondict(self):
        m1 = MyData(data={u'value': u'foo'})
        self.session.add(m1)
        self.session.commit()
        # Test for __setitem__
        m1.data[u'value'] = u'bar'
        self.assertEqual(m1.data[u'value'], u'bar')
        del m1.data[u'value']
        self.assertEqual(m1.data, {})
        self.assertRaises(ValueError, MyData, data=u'NonDict')

    def test_query(self):
        c1 = Container(name=u'c1')
        self.session.add(c1)
        c2 = Container(name=u'c2')
        self.session.add(c2)
        self.session.commit()

        self.assertEqual(Container.query.filter_by(name=u'c1').one_or_none(), c1)
        self.assertEqual(Container.query.filter_by(name=u'c3').one_or_none(), None)
        self.assertRaises(MultipleResultsFound, Container.query.one_or_none)

    def test_failsafe_add(self):
        """
        failsafe_add gracefully handles IntegrityError from dupe entries
        """
        d1 = NamedDocument(name=u'add_and_commit_test', title=u"Test")
        d1a = failsafe_add(self.session, d1, name=u'add_and_commit_test')
        self.assertTrue(d1a is d1)  # We got back what we created, so the commit succeeded

        d2 = NamedDocument(name=u'add_and_commit_test', title=u"Test")
        d2a = failsafe_add(self.session, d2, name=u'add_and_commit_test')
        self.assertFalse(d2a is d2)  # This time we got back d1 instead of d2
        self.assertTrue(d2a is d1)

    def test_failsafe_add_existing(self):
        """
        failsafe_add doesn't fail if the item is already in the session
        """
        d1 = NamedDocument(name=u'add_and_commit_test', title=u"Test")
        d1a = failsafe_add(self.session, d1, name=u'add_and_commit_test')
        self.assertTrue(d1a is d1)  # We got back what we created, so the commit succeeded

        d2 = NamedDocument(name=u'add_and_commit_test', title=u"Test")
        self.session.add(d2)  # Add to session before going to failsafe_add
        d2a = failsafe_add(self.session, d2, name=u'add_and_commit_test')
        self.assertFalse(d2a is d2)  # This time we got back d1 instead of d2
        self.assertTrue(d2a is d1)

    def test_failsafe_add_fail(self):
        """
        failsafe_add passes through errors occuring from bad data
        """
        d1 = NamedDocument(name=u'missing_title')
        self.assertRaises(IntegrityError, failsafe_add, self.session, d1, name=u'missing_title')

    def test_failsafe_add_silent_fail(self):
        """
        failsafe_add does not raise IntegrityError with bad data
        when no filters are provided
        """
        d1 = NamedDocument(name=u'missing_title')
        self.assertIsNone(failsafe_add(self.session, d1))

    def test_uuid_key(self):
        """
        Models with a UUID primary key work as expected
        """
        u1 = UuidKey()
        u2 = UuidKey()
        self.session.add(u1)
        self.session.add(u2)
        self.session.commit()
        self.assertTrue(isinstance(u1.id, uuid.UUID))
        self.assertTrue(isinstance(u2.id, uuid.UUID))
        self.assertNotEqual(u1.id, u2.id)

        fk1 = UuidForeignKey1(uuidkey=u1)
        fk2 = UuidForeignKey2(uuidkey=u2)
        db.session.add(fk1)
        db.session.add(fk2)
        db.session.commit()

        self.assertIs(fk1.uuidkey, u1)
        self.assertIs(fk2.uuidkey, u2)
        self.assertTrue(isinstance(fk1.uuidkey_id, uuid.UUID))
        self.assertTrue(isinstance(fk2.uuidkey_id, uuid.UUID))
        self.assertEqual(fk1.uuidkey_id, u1.id)
        self.assertEqual(fk2.uuidkey_id, u2.id)

    def test_uuid_url_id(self):
        """
        IdMixin provides a url_id that renders as a string of
        either the integer primary key or the UUID primary key
        """
        u1 = NonUuidKey()
        u2 = UuidKey()
        u3 = NonUuidMixinKey()
        u4 = UuidMixinKey()
        db.session.add_all([u1, u2, u3, u4])
        db.session.commit()

        # Regular IdMixin ids
        i1 = u1.id
        i2 = u2.id
        # UUID keys from UuidMixin
        i3 = u3.uuid
        i4 = u4.uuid

        self.assertEqual(u1.url_id, unicode(i1))

        self.assertIsInstance(i2, uuid.UUID)
        self.assertEqual(u2.url_id, i2.hex)
        self.assertEqual(len(u2.url_id), 32)  # This is a 32-byte hex representation
        self.assertFalse('-' in u2.url_id)  # Without dashes

        self.assertIsInstance(i3, uuid.UUID)
        self.assertEqual(u3.url_id, i3.hex)
        self.assertEqual(len(u3.url_id), 32)  # This is a 32-byte hex representation
        self.assertFalse('-' in u3.url_id)  # Without dashes

        self.assertIsInstance(i4, uuid.UUID)
        self.assertEqual(u4.url_id, i4.hex)
        self.assertEqual(len(u4.url_id), 32)  # This is a 32-byte hex representation
        self.assertFalse('-' in u4.url_id)  # Without dashes

        # Querying against `url_id` redirects the query to
        # `id` (IdMixin) or `uuid` (UuidMixin).

        # With integer primary keys, `url_id` is simply a proxy for `id`
        self.assertEqual(
            unicode((NonUuidKey.url_id == 1
                ).compile(compile_kwargs={'literal_binds': True})),
            u"non_uuid_key.id = 1")
        # We don't check the data type here, leaving that to the engine
        self.assertEqual(
            unicode((NonUuidKey.url_id == '1'
                ).compile(compile_kwargs={'literal_binds': True})),
            u"non_uuid_key.id = '1'")

        # With UUID primary keys, `url_id` casts the value into a UUID
        # and then queries against `id` or ``uuid``

        # Note that `literal_binds` here doesn't know how to render UUIDs if
        # no engine is specified, and so casts them into a string. We test this
        # with multiple renderings.

        # Hex UUID
        self.assertEqual(
            unicode((UuidKey.url_id == '74d588574a7611e78c27c38403d0935c'
                ).compile(compile_kwargs={'literal_binds': True})),
            u"uuid_key.id = '74d588574a7611e78c27c38403d0935c'")
        # Hex UUID with dashes
        self.assertEqual(
            unicode((UuidKey.url_id == '74d58857-4a76-11e7-8c27-c38403d0935c'
                ).compile(compile_kwargs={'literal_binds': True})),
            u"uuid_key.id = '74d588574a7611e78c27c38403d0935c'")
        # UUID object
        self.assertEqual(
            unicode((UuidKey.url_id == uuid.UUID('74d58857-4a76-11e7-8c27-c38403d0935c')
                ).compile(compile_kwargs={'literal_binds': True})),
            u"uuid_key.id = '74d588574a7611e78c27c38403d0935c'")

        # Query raises InvalidId if given an invalid value
        with self.assertRaises(InvalidId):
            UuidKey.url_id == 'garbage!'
        with self.assertRaises(InvalidId):
            NonUuidMixinKey.url_id == 'garbage!'
        with self.assertRaises(InvalidId):
            UuidMixinKey.url_id == 'garbage!'

        # Repeat against UuidMixin classes (with only hex keys for brevity)
        self.assertEqual(
            unicode((NonUuidMixinKey.url_id == '74d588574a7611e78c27c38403d0935c'
                ).compile(compile_kwargs={'literal_binds': True})),
            u"non_uuid_mixin_key.uuid = '74d588574a7611e78c27c38403d0935c'")
        self.assertEqual(
            unicode((UuidMixinKey.url_id == '74d588574a7611e78c27c38403d0935c'
                ).compile(compile_kwargs={'literal_binds': True})),
            u"uuid_mixin_key.id = '74d588574a7611e78c27c38403d0935c'")

        # Running a database query with url_id works as expected.
        # This test should pass on both SQLite and PostgreSQL
        qu1 = NonUuidKey.query.filter_by(url_id=u1.url_id).first()
        self.assertEqual(u1, qu1)
        qu2 = UuidKey.query.filter_by(url_id=u2.url_id).first()
        self.assertEqual(u2, qu2)
        qu3 = NonUuidMixinKey.query.filter_by(url_id=u3.url_id).first()
        self.assertEqual(u3, qu3)
        qu4 = UuidMixinKey.query.filter_by(url_id=u4.url_id).first()
        self.assertEqual(u4, qu4)

    def test_uuid_buid_suuid(self):
        """
        UuidMixin provides buid and suuid
        """
        u1 = NonUuidMixinKey()
        u2 = UuidMixinKey()
        db.session.add_all([u1, u2])
        db.session.commit()

        # The `uuid` column contains a UUID
        self.assertIsInstance(u1.uuid, uuid.UUID)
        self.assertIsInstance(u2.uuid, uuid.UUID)

        # Test readbility of `buid` attribute
        self.assertEqual(u1.buid, uuid2buid(u1.uuid))
        self.assertEqual(len(u1.buid), 22)  # This is a 22-byte BUID representation
        self.assertEqual(u2.buid, uuid2buid(u2.uuid))
        self.assertEqual(len(u2.buid), 22)  # This is a 22-byte BUID representation

        # Test readability of `suuid` attribute
        self.assertEqual(u1.suuid, uuid2suuid(u1.uuid))
        self.assertEqual(len(u1.suuid), 22)  # This is a 22-byte ShortUUID representation
        self.assertEqual(u2.suuid, uuid2suuid(u2.uuid))
        self.assertEqual(len(u2.suuid), 22)  # This is a 22-byte ShortUUID representation

        # SQL queries against `buid` and `suuid` cast the value into a UUID
        # and then query against `id` or ``uuid``

        # Note that `literal_binds` here doesn't know how to render UUIDs if
        # no engine is specified, and so casts them into a string

        # UuidMixin with integer primary key queries against the `uuid` column
        self.assertEqual(
            unicode((NonUuidMixinKey.buid == 'dNWIV0p2EeeMJ8OEA9CTXA'
                ).compile(compile_kwargs={'literal_binds': True})),
            u"non_uuid_mixin_key.uuid = '74d588574a7611e78c27c38403d0935c'")

        # UuidMixin with UUID primary key queries against the `id` column
        self.assertEqual(
            unicode((UuidMixinKey.buid == 'dNWIV0p2EeeMJ8OEA9CTXA'
                ).compile(compile_kwargs={'literal_binds': True})),
            u"uuid_mixin_key.id = '74d588574a7611e78c27c38403d0935c'")

        # Repeat for `suuid`
        self.assertEqual(
            unicode((NonUuidMixinKey.suuid == 'vVoaZTeXGiD4qrMtYNosnN'
                ).compile(compile_kwargs={'literal_binds': True})),
            u"non_uuid_mixin_key.uuid = '74d588574a7611e78c27c38403d0935c'")
        self.assertEqual(
            unicode((UuidMixinKey.suuid == 'vVoaZTeXGiD4qrMtYNosnN'
                ).compile(compile_kwargs={'literal_binds': True})),
            u"uuid_mixin_key.id = '74d588574a7611e78c27c38403d0935c'")

        # Query raises InvalidId if given an invalid value
        with self.assertRaises(InvalidId):
            NonUuidMixinKey.buid == 'garbage!'
        with self.assertRaises(InvalidId):
            NonUuidMixinKey.suuid == 'garbage!'
        with self.assertRaises(InvalidId):
            UuidMixinKey.buid == 'garbage!'
        with self.assertRaises(InvalidId):
            UuidMixinKey.suuid == 'garbage!'

    def test_uuid_url_id_name_suuid(self):
        """
        BaseIdNameMixin models with UUID primary or secondary keys should
        generate properly formatted url_id, url_id_name and url_name_suuid.
        The url_id_name and url_name_suuid fields should be queryable as well.
        """
        u1 = UuidIdName(id=uuid.UUID('74d58857-4a76-11e7-8c27-c38403d0935c'), name=u'test', title=u'Test')
        u2 = UuidIdNameMixin(id=uuid.UUID('74d58857-4a76-11e7-8c27-c38403d0935c'), name=u'test', title=u'Test')
        u3 = UuidIdNameSecondary(uuid=uuid.UUID('74d58857-4a76-11e7-8c27-c38403d0935c'), name=u'test', title=u'Test')
        db.session.add_all([u1, u2, u3])
        db.session.commit()

        self.assertEqual(u1.url_id, u'74d588574a7611e78c27c38403d0935c')
        self.assertEqual(u1.url_id_name, u'74d588574a7611e78c27c38403d0935c-test')
        with self.assertRaises(AttributeError):
            # No UuidMixin == No suuid or url_name_suuid attributes
            self.assertEqual(u1.url_name_suuid, u'test-vVoaZTeXGiD4qrMtYNosnN')
        self.assertEqual(u2.url_id, u'74d588574a7611e78c27c38403d0935c')
        self.assertEqual(u2.url_id_name, u'74d588574a7611e78c27c38403d0935c-test')
        self.assertEqual(u2.url_name_suuid, u'test-vVoaZTeXGiD4qrMtYNosnN')
        self.assertEqual(u3.url_id, u'74d588574a7611e78c27c38403d0935c')
        self.assertEqual(u3.url_id_name, u'74d588574a7611e78c27c38403d0935c-test')
        self.assertEqual(u3.url_name_suuid, u'test-vVoaZTeXGiD4qrMtYNosnN')

        # url_name is legacy
        self.assertEqual(u1.url_id_name, u1.url_name)
        self.assertEqual(u2.url_id_name, u2.url_name)
        self.assertEqual(u3.url_id_name, u3.url_name)

        qu1 = UuidIdName.query.filter_by(url_id_name=u1.url_id_name).first()
        self.assertEqual(qu1, u1)
        qu2 = UuidIdNameMixin.query.filter_by(url_id_name=u2.url_id_name).first()
        self.assertEqual(qu2, u2)
        qu3 = UuidIdNameSecondary.query.filter_by(url_id_name=u3.url_id_name).first()
        self.assertEqual(qu3, u3)

        qsu2 = UuidIdNameMixin.query.filter_by(url_name_suuid=u2.url_name_suuid).first()
        self.assertEqual(qsu2, u2)
        qsu3 = UuidIdNameSecondary.query.filter_by(url_name_suuid=u3.url_name_suuid).first()
        self.assertEqual(qsu3, u3)

    def test_uuid_default(self):
        """
        Models with a UUID primary or secondary key have a default value before
        adding to session
        """
        uuid_no = NonUuidKey()
        uuid_yes = UuidKey()
        uuidm_no = NonUuidMixinKey()
        uuidm_yes = UuidMixinKey()
        # Non-UUID primary keys are not automatically generated
        u1 = uuid_no.id
        self.assertIsNone(u1)
        # However, UUID keys are generated even before adding to session
        u2 = uuid_yes.id
        self.assertIsInstance(u2, uuid.UUID)
        # Once generated, the key remains stable
        u3 = uuid_yes.id
        self.assertEqual(u2, u3)

        # UuidMixin works likewise
        um1 = uuidm_no.uuid
        self.assertIsInstance(um1, uuid.UUID)
        um2 = uuidm_yes.uuid  # This should generate uuidm_yes.id
        self.assertIsInstance(um2, uuid.UUID)
        self.assertEqual(uuidm_yes.id, uuidm_yes.uuid)

    def test_accessible_proxy(self):
        """
        Should be able to proxy SQLAlchemy model objects
        to control read, write access on attributes
        """
        doc = ProxiedDocument(name='document1', title='Document 1', content='content')
        db.session.add(doc)
        db.session.commit()
        non_existent_roles = {'non_existent_role'}
        inaccessible_doc_proxy = doc.accessible_proxy(roles=non_existent_roles)
        self.assertIsNone(inaccessible_doc_proxy.name)

        reader_roles = {'document_reader'}
        reader_accessible_doc_proxy = doc.accessible_proxy(roles=reader_roles)
        self.assertEquals(reader_accessible_doc_proxy.name, doc.name)

        partial_reader_roles = {'title_reader'}
        partial_reader_accessible_doc_proxy = doc.accessible_proxy(roles=partial_reader_roles)
        self.assertIsNone(partial_reader_accessible_doc_proxy.name)
        self.assertIsNone(partial_reader_accessible_doc_proxy.content)
        self.assertEquals(partial_reader_accessible_doc_proxy.title, doc.title)

        # writer should also be able to read the attributes
        # they have access to read
        writer_roles = {'document_writer'}
        writer_accessible_doc_proxy = doc.accessible_proxy(roles=writer_roles)
        self.assertEquals(writer_accessible_doc_proxy.name, doc.name)

        new_title = u"Document 1 updated via proxy"
        writer_accessible_doc_proxy.title = new_title
        db.session.commit()
        self.assertEquals(doc.title, new_title)
        self.assertIsInstance(dict(writer_accessible_doc_proxy), dict)
        self.assertEquals(dict(writer_accessible_doc_proxy), {'name': doc.name, 'title': doc.title, 'content': doc.content})


class TestCoasterModels2(TestCoasterModels):
    app = app2
