# -*- coding: utf-8 -*-

import unittest

from datetime import datetime, timedelta
from coaster.sqlalchemy import (BaseMixin, BaseNameMixin, BaseScopedNameMixin,
    BaseIdNameMixin, BaseScopedIdMixin, BaseScopedIdNameMixin)
from sqlalchemy import create_engine, Column, Integer, Unicode, UniqueConstraint, ForeignKey
from sqlalchemy.orm import relationship, synonym, sessionmaker, scoped_session
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.exc import IntegrityError

engine = create_engine('sqlite://')
Session = scoped_session(sessionmaker(autocommit=False,
              autoflush=False,
              bind=engine))
Base = declarative_base(bind=engine)


# --- Models ------------------------------------------------------------------

class Container(BaseMixin, Base):
    __tablename__ = 'container'
    name = Column(Unicode(80), nullable=True)
    query = Session.query_property()

    content = Column(Unicode(250))


class UnnamedDocument(BaseMixin, Base):
    __tablename__ = 'unnamed_document'
    query = Session.query_property()
    container_id = Column(Integer, ForeignKey('container.id'))
    container = relationship(Container)

    content = Column(Unicode(250))


class NamedDocument(BaseNameMixin, Base):
    __tablename__ = 'named_document'
    query = Session.query_property()
    container_id = Column(Integer, ForeignKey('container.id'))
    container = relationship(Container)

    content = Column(Unicode(250))


class ScopedNamedDocument(BaseScopedNameMixin, Base):
    __tablename__ = 'scoped_named_document'
    query = Session.query_property()
    container_id = Column(Integer, ForeignKey('container.id'))
    container = relationship(Container)
    parent = synonym('container')

    content = Column(Unicode(250))
    __table_args__ = (UniqueConstraint('name', 'container_id'),)


class IdNamedDocument(BaseIdNameMixin, Base):
    __tablename__ = 'id_named_document'
    query = Session.query_property()
    container_id = Column(Integer, ForeignKey('container.id'))
    container = relationship(Container)

    content = Column(Unicode(250))


class ScopedIdDocument(BaseScopedIdMixin, Base):
    __tablename__ = 'scoped_id_document'
    query = Session.query_property()
    container_id = Column(Integer, ForeignKey('container.id'))
    container = relationship(Container)
    parent = synonym('container')

    content = Column(Unicode(250))
    __table_args__ = (UniqueConstraint('url_id', 'container_id'),)


class ScopedIdNamedDocument(BaseScopedIdNameMixin, Base):
    __tablename__ = 'scoped_id_named_document'
    query = Session.query_property()
    container_id = Column(Integer, ForeignKey('container.id'))
    container = relationship(Container)
    parent = synonym('container')

    content = Column(Unicode(250))
    __table_args__ = (UniqueConstraint('url_id', 'container_id'),)


# -- Tests --------------------------------------------------------------------

class TestCoasterModels(unittest.TestCase):
    def setUp(self):
        Base.metadata.create_all()
        self.session = Session()

    def tearDown(self):
        self.session.rollback()
        Base.metadata.drop_all()

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
        now1 = datetime.utcnow()
        c = self.make_container()
        self.session.commit()
        u = c.updated_at
        now2 = datetime.utcnow()
        self.assertTrue(now1 < c.created_at)
        self.assertTrue(now2 > c.created_at)
        c.content = u"updated"
        self.session.commit()
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
        d1 = NamedDocument(title=u"Hello", content=u"World", container=c1)
        self.session.add(d1)
        self.session.commit()
        self.assertEqual(d1.name, u'hello')

        c2 = self.make_container()
        d2 = NamedDocument(title=u"Hello", content=u"Again", container=c2)
        self.session.add(d2)
        self.session.commit()
        self.assertEqual(d2.name, u'hello1')

    def test_scoped_named(self):
        """Scoped named documents have names unique to their containers."""
        c1 = self.make_container()
        d1 = ScopedNamedDocument(title=u"Hello", content=u"World", container=c1)
        self.session.add(d1)
        self.session.commit()
        self.assertEqual(d1.name, u'hello')

        d2 = ScopedNamedDocument(title=u"Hello", content=u"Again", container=c1)
        self.session.add(d2)
        self.session.commit()
        self.assertEqual(d2.name, u'hello1')

        c2 = self.make_container()
        d3 = ScopedNamedDocument(title=u"Hello", content=u"Once More", container=c2)
        self.session.add(d3)
        self.session.commit()
        self.assertEqual(d3.name, u'hello')

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
        self.session.add(d1)
        self.session.commit()
        self.assertEqual(d1.url_id, 1)

        d2 = ScopedIdDocument(content=u"New document", container=c1)
        self.session.add(d2)
        self.session.commit()
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

    def test_delayed_name(self):
        c = self.make_container()
        d1 = NamedDocument(container=c)
        d1.title = u'Document 1'
        d1.make_name()
        self.session.add(d1)
        d2 = ScopedNamedDocument(container=c)
        d2.title = u'Document 2'
        d2.make_name()
        self.session.add(d2)
        d3 = IdNamedDocument(container=c)
        d3.title = u'Document 3'
        d3.make_name()
        self.session.add(d3)
        d4 = ScopedIdNamedDocument(container=c)
        d4.title = u'Document 4'
        d4.make_name()
        self.session.add(d4)
        self.session.commit()

    def test_has_timestamps(self):
        # Confirm that a model with multiple base classes between it and
        # TimestampMixin still has created_at and updated_at
        c = self.make_container()
        d = ScopedIdNamedDocument(title=u"Hello", content=u"World", container=c)
        self.session.add(d)
        self.session.commit()
        self.assertTrue(d.created_at is not None)
        self.assertTrue(d.updated_at is not None)
        updated_at = d.updated_at
        self.assertTrue(d.updated_at - d.created_at < timedelta(seconds=1))
        self.assertTrue(isinstance(d.created_at, datetime))
        self.assertTrue(isinstance(d.updated_at, datetime))
        d.title = u"Updated hello"
        self.session.commit()
        self.assertTrue(d.updated_at > updated_at)

if __name__ == '__main__':
    unittest.main()
