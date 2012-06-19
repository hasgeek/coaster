# -*- coding: utf-8 -*-

import unittest

from datetime import datetime
from coaster.sqlalchemy import BaseMixin, BaseNameMixin, BaseScopedNameMixin, BaseIdNameMixin, BaseScopedIdNameMixin
from sqlalchemy import create_engine, Column, Integer, Unicode, UniqueConstraint, ForeignKey
from sqlalchemy.orm import relationship, synonym, sessionmaker, scoped_session
from sqlalchemy.ext.declarative import declarative_base

engine = create_engine('sqlite://')
Session = scoped_session(sessionmaker(autocommit=False,
              autoflush=False,
              bind=engine))
Base = declarative_base(bind=engine)


# --- Models ------------------------------------------------------------------

class Container(BaseMixin, Base):
    __tablename__ = 'container'
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
        c.content = "updated"
        self.session.commit()
        self.assertTrue(c.updated_at > now2)
        self.assertTrue(c.updated_at > c.created_at)
        self.assertTrue(c.updated_at > u)

    def test_unnamed(self):
        c = self.make_container()
        d = UnnamedDocument(content="hello", container=c)
        self.session.add(d)
        self.session.commit()
        self.assertEqual(c.id, 1)
        self.assertEqual(d.id, 1)

    def test_named(self):
        """Named documents have globally unique names."""
        c1 = self.make_container()
        d1 = NamedDocument(title="Hello", content="World", container=c1)
        self.session.add(d1)
        self.session.commit()
        self.assertEqual(d1.name, 'hello')

        c2 = self.make_container()
        d2 = NamedDocument(title="Hello", content="Again", container=c2)
        self.session.add(d2)
        self.session.commit()
        self.assertEqual(d2.name, 'hello1')

    def test_scoped_named(self):
        """Scoped named documents have names unique to their containers."""
        c1 = self.make_container()
        d1 = ScopedNamedDocument(title="Hello", content="World", container=c1)
        self.session.add(d1)
        self.session.commit()
        self.assertEqual(d1.name, 'hello')

        d2 = ScopedNamedDocument(title="Hello", content="Again", container=c1)
        self.session.add(d2)
        self.session.commit()
        self.assertEqual(d2.name, 'hello1')

        c2 = self.make_container()
        d3 = ScopedNamedDocument(title="Hello", content="Once More", container=c2)
        self.session.add(d3)
        self.session.commit()
        self.assertEqual(d3.name, 'hello')

    def test_id_named(self):
        """Documents with a global id in the URL"""
        c1 = self.make_container()
        d1 = IdNamedDocument(title="Hello", content="World", container=c1)
        self.session.add(d1)
        self.session.commit()
        self.assertEqual(d1.url_name, '1-hello')

        d2 = IdNamedDocument(title="Hello", content="Again", container=c1)
        self.session.add(d2)
        self.session.commit()
        self.assertEqual(d2.url_name, '2-hello')

        c2 = self.make_container()
        d3 = IdNamedDocument(title="Hello", content="Once More", container=c2)
        self.session.add(d3)
        self.session.commit()
        self.assertEqual(d3.url_name, '3-hello')

    def test_scoped_id_named(self):
        """Documents with a container-specifc id in the URL"""
        c1 = self.make_container()
        d1 = ScopedIdNamedDocument(title="Hello", content="World", container=c1)
        self.session.add(d1)
        self.session.commit()
        self.assertEqual(d1.url_name, '1-hello')

        d2 = ScopedIdNamedDocument(title="Hello again", content="New name", container=c1)
        self.session.add(d2)
        self.session.commit()
        self.assertEqual(d2.url_name, '2-hello-again')

        c2 = self.make_container()
        d3 = ScopedIdNamedDocument(title="Hello", content="Once More", container=c2)
        self.session.add(d3)
        self.session.commit()
        self.assertEqual(d3.url_name, '1-hello')

        d4 = ScopedIdNamedDocument(title="Hello", content="Third", container=c1)
        self.session.add(d4)
        self.session.commit()
        self.assertEqual(d4.url_name, '3-hello')

    def test_scoped_without_parent(self):
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
        d1.title = 'Document 1'
        d1.make_name()
        self.session.add(d1)
        d2 = ScopedNamedDocument(container=c)
        d2.title = 'Document 2'
        d2.make_name()
        self.session.add(d2)
        d3 = IdNamedDocument(container=c)
        d3.title = 'Document 3'
        d3.make_name()
        self.session.add(d3)
        d4 = ScopedIdNamedDocument(container=c)
        d4.title = 'Document 4'
        d4.make_name()
        self.session.add(d4)
        self.session.commit()

if __name__ == '__main__':
    unittest.main()
