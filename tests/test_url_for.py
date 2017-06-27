# -*- coding: utf-8 -*-

from __future__ import absolute_import

import unittest
from flask import Flask
from coaster.db import db

from .test_models import Container, NamedDocument, ScopedNamedDocument

# --- Test setup --------------------------------------------------------------

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)


@app.route('/<doc>')
@NamedDocument.is_url_for('view', doc='name')
def doc_view(doc):
    return u'{} {}'.format('view', doc)


@app.route('/<doc>/edit')
@NamedDocument.is_url_for('edit', doc='name')
def doc_edit(doc):
    return u'{} {}'.format('edit', doc)


@app.route('/<doc>/upper')
@NamedDocument.is_url_for('upper', doc=lambda d: d.name.upper())
def doc_upper(doc):
    return u'{} {}'.format('upper', doc)


@app.route('/<container>/<doc>')
@ScopedNamedDocument.is_url_for('view', container='parent.id', doc='name')
def sdoc_view(container, doc):
    return u'{} {} {}'.format('view', container, doc)


@app.route('/<container>/<doc>/edit')
@ScopedNamedDocument.is_url_for('edit', _external=True, container=('parent', 'id'), doc='name')
def sdoc_edit(container, doc):
    return u'{} {} {}'.format('edit', container, doc)


# --- Tests -------------------------------------------------------------------

class TestUrlFor(unittest.TestCase):
    def setUp(self):
        self.ctx = app.test_request_context()
        self.ctx.push()
        db.create_all()
        self.session = db.session

    def tearDown(self):
        self.session.rollback()
        db.drop_all()
        self.ctx.pop()

    def test_class_has_url_for(self):
        """
        Test that is_url_for declarations on one class are distinct from those on another class.
        """
        self.assertNotEqual(NamedDocument.url_for_endpoints, ScopedNamedDocument.url_for_endpoints)

    def test_url_for(self):
        """
        Test that is_url_for declarations are saved and used by the url_for method.
        """
        # Make two documents
        doc1 = NamedDocument(name=u'document1', title=u"Document 1")
        self.session.add(doc1)
        c1 = Container()  # Gets an autoincrementing id starting from 1
        self.session.add(c1)
        doc2 = ScopedNamedDocument(container=c1, name=u'document2', title=u"Document 2")
        self.session.add(doc2)
        self.session.commit()

        # Confirm first returns the correct paths
        self.assertEqual(doc1.url_for(), '/document1')
        self.assertEqual(doc1.url_for('view'), '/document1')
        self.assertEqual(doc1.url_for('edit'), '/document1/edit')
        # Test callable parameters
        self.assertEqual(doc1.url_for('upper'), '/DOCUMENT1/upper')
        # Insist on changing one of the parameters
        self.assertEqual(doc1.url_for('edit', doc=doc1.name.upper()), '/DOCUMENT1/edit')
        # Confirm second returns the correct paths
        self.assertEqual(doc2.url_for(), '/1/document2')
        self.assertEqual(doc2.url_for('view'), '/1/document2')
        # Test _external flag
        self.assertEqual(doc2.url_for('edit'), 'http://localhost/1/document2/edit')
        self.assertEqual(doc2.url_for('edit', _external=False), '/1/document2/edit')
        self.assertEqual(doc2.url_for('edit', _external=True), 'http://localhost/1/document2/edit')
