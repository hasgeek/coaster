# -*- coding: utf-8 -*-

import unittest
from sqlalchemy import Column, ForeignKey
from sqlalchemy.orm import relationship

from coaster.views import load_model, load_models
from coaster.sqlalchemy import BaseMixin, BaseNameMixin, BaseScopedIdMixin

from test_models import (Base, Session, Container, NamedDocument,
    ScopedNamedDocument, IdNamedDocument, ScopedIdDocument,
    ScopedIdNamedDocument)


# --- Models ------------------------------------------------------------------

class MiddleContainer(BaseMixin, Base):
    __tablename__ = 'middle_container'
    query = Session.query_property()


class ParentDocument(BaseNameMixin, Base):
    __tablename__ = 'parent_document'
    middle_id = Column(None, ForeignKey('middle_container.id'))
    middle = relationship(MiddleContainer, uselist=False)
    query = Session.query_property()

    def __init__(self, **kwargs):
        super(ParentDocument, self).__init__(**kwargs)
        self.middle = MiddleContainer()


class ChildDocument(BaseScopedIdMixin, Base):
    __tablename__ = 'child_document'
    parent_id = Column(None, ForeignKey('middle_container.id'))
    parent = relationship(MiddleContainer, backref='children')
    query = Session.query_property()


# --- load_models decorators --------------------------------------------------

@load_model(Container, {'name': 'container'}, 'container')
def t_container(container):
    return container


@load_models(
    (Container, {'name': 'container'}, 'container'),
    (NamedDocument, {'name': 'document', 'container': 'container'}, 'document')
    )
def t_named_document(container, document):
    return document


@load_models(
    (Container, {'name': 'container'}, 'container'),
    (ScopedNamedDocument, {'name': 'document', 'container': 'container'}, 'document')
    )
def t_scoped_named_document(container, document):
    return document


@load_models(
    (Container, {'name': 'container'}, 'container'),
    (IdNamedDocument, {'url_name': 'document', 'container': 'container'}, 'document')
    )
def t_id_named_document(container, document):
    return document


@load_models(
    (Container, {'name': 'container'}, 'container'),
    (ScopedIdDocument, {'id': 'document', 'container': 'container'}, 'document')
    )
def t_scoped_id_document(container, document):
    return document


@load_models(
    (Container, {'name': 'container'}, 'container'),
    (ScopedIdNamedDocument, {'url_name': 'document', 'container': 'container'}, 'document')
    )
def t_scoped_id_named_document(container, document):
    return document


@load_models(
    (ParentDocument, {'name': 'document'}, 'document'),
    (ChildDocument, {'id': 'child', 'parent': lambda r, p: r['document'].middle}, 'child')
    )
def t_callable_document(document, child):
    return child


@load_models(
    (ParentDocument, {'name': 'document'}, 'document'),
    (ChildDocument, {'id': 'child', 'parent': 'document.middle'}, 'child')
    )
def t_dotted_document(document, child):
    return child


# --- Tests -------------------------------------------------------------------

class TestLoadModels(unittest.TestCase):
    def setUp(self):
        Base.metadata.create_all()
        self.session = Session()
        c = Container(name=u'c')
        self.session.add(c)
        self.container = c
        self.nd1 = NamedDocument(container=c, title=u"Named Document")
        self.session.add(self.nd1)
        self.session.commit()
        self.nd2 = NamedDocument(container=c, title=u"Another Named Document")
        self.session.add(self.nd2)
        self.session.commit()
        self.snd1 = ScopedNamedDocument(container=c, title=u"Scoped Named Document")
        self.session.add(self.snd1)
        self.session.commit()
        self.snd2 = ScopedNamedDocument(container=c, title=u"Another Scoped Named Document")
        self.session.add(self.snd2)
        self.session.commit()
        self.ind1 = IdNamedDocument(container=c, title=u"Id Named Document")
        self.session.add(self.ind1)
        self.session.commit()
        self.ind2 = IdNamedDocument(container=c, title=u"Another Id Named Document")
        self.session.add(self.ind2)
        self.session.commit()
        self.sid1 = ScopedIdDocument(container=c)
        self.session.add(self.sid1)
        self.session.commit()
        self.sid2 = ScopedIdDocument(container=c)
        self.session.add(self.sid2)
        self.session.commit()
        self.sind1 = ScopedIdNamedDocument(container=c, title=u"Scoped Id Named Document")
        self.session.add(self.sind1)
        self.session.commit()
        self.sind2 = ScopedIdNamedDocument(container=c, title=u"Another Scoped Id Named Document")
        self.session.add(self.sind2)
        self.session.commit()
        self.pc = ParentDocument(title=u"Parent")
        self.session.add(self.pc)
        self.session.commit()
        self.child1 = ChildDocument(parent=self.pc.middle)
        self.session.add(self.child1)
        self.session.commit()
        self.child2 = ChildDocument(parent=self.pc.middle)
        self.session.add(self.child2)
        self.session.commit()

    def tearDown(self):
        self.session.rollback()
        Base.metadata.drop_all()

    def test_container(self):
        self.assertEqual(t_container(container=u'c'), self.container)

    def test_named_document(self):
        self.assertEqual(t_named_document(container=u'c', document=u'named-document'), self.nd1)
        self.assertEqual(t_named_document(container=u'c', document=u'another-named-document'), self.nd2)

    def test_scoped_named_document(self):
        self.assertEqual(t_scoped_named_document(container=u'c', document=u'scoped-named-document'), self.snd1)
        self.assertEqual(t_scoped_named_document(container=u'c', document=u'another-scoped-named-document'), self.snd2)

    def test_id_named_document(self):
        self.assertEqual(t_id_named_document(container=u'c', document=u'1-id-named-document'), self.ind1)
        self.assertEqual(t_id_named_document(container=u'c', document=u'2-another-id-named-document'), self.ind2)

    def test_scoped_id_document(self):
        self.assertEqual(t_scoped_id_document(container=u'c', document=u'1'), self.sid1)
        self.assertEqual(t_scoped_id_document(container=u'c', document=u'2'), self.sid2)
        self.assertEqual(t_scoped_id_document(container=u'c', document=1), self.sid1)
        self.assertEqual(t_scoped_id_document(container=u'c', document=2), self.sid2)

    def test_scoped_id_named_document(self):
        self.assertEqual(t_scoped_id_named_document(container=u'c', document=u'1-scoped-id-named-document'), self.sind1)
        self.assertEqual(t_scoped_id_named_document(container=u'c', document=u'2-another-scoped-id-named-document'), self.sind2)

    def test_callable_document(self):
        self.assertEqual(t_callable_document(document=u'parent', child=1), self.child1)
        self.assertEqual(t_callable_document(document=u'parent', child=2), self.child2)

    def test_dotted_document(self):
        self.assertEqual(t_dotted_document(document=u'parent', child=1), self.child1)
        self.assertEqual(t_dotted_document(document=u'parent', child=2), self.child2)


if __name__ == '__main__':
    unittest.main()
