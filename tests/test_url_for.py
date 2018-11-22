# -*- coding: utf-8 -*-

from __future__ import absolute_import

import unittest
from werkzeug.routing import BuildError
from flask import Flask
from coaster.db import db

from .test_models import Container, NamedDocument, ScopedNamedDocument

# --- Test setup --------------------------------------------------------------

app1 = Flask(__name__)
app1.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
app1.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app1)

app2 = Flask(__name__)
app2.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
app2.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app2)


@app1.route('/<doc>')
@NamedDocument.is_url_for('view', doc='name')
def doc_view(doc):
    return u'{} {}'.format('view', doc)


@app1.route('/<doc>/edit')
@NamedDocument.is_url_for('edit', doc='name')
def doc_edit(doc):
    return u'{} {}'.format('edit', doc)


@app1.route('/<doc>/upper')
@NamedDocument.is_url_for('upper', doc=lambda d: d.name.upper())
def doc_upper(doc):
    return u'{} {}'.format('upper', doc)


@app1.route('/<container>/<doc>')
@ScopedNamedDocument.is_url_for('view', container='parent.id', doc='name')
def sdoc_view(container, doc):
    return u'{} {} {}'.format('view', container, doc)


@app1.route('/<container>/<doc>/edit')
@ScopedNamedDocument.is_url_for('edit', _external=True, container=('parent', 'id'), doc='name')
def sdoc_edit(container, doc):
    return u'{} {} {}'.format('edit', container, doc)


@app1.route('/<doc>/app_only')
@NamedDocument.is_url_for('app_only', _app=app1, doc='name')
def doc_app_only(doc):
    return u'{} {}'.format('app_only', doc)


@app1.route('/<doc>/app1')
@NamedDocument.is_url_for('per_app', _app=app1, doc='name')
def doc_per_app1(doc):
    return u'{} {}'.format('per_app', doc)


@app2.route('/<doc>/app2')
@NamedDocument.is_url_for('per_app', _app=app2, doc='name')
def doc_per_app2(doc):
    return u'{} {}'.format('per_app', doc)


# --- Tests -------------------------------------------------------------------

class TestUrlForBase(unittest.TestCase):
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


class TestUrlFor(TestUrlForBase):
    def test_class_has_url_for(self):
        """
        Test that is_url_for declarations on one class are distinct from those on another class.
        """
        assert NamedDocument.url_for_endpoints is not ScopedNamedDocument.url_for_endpoints

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
        assert doc1.url_for() == '/document1'
        assert doc1.url_for('view') == '/document1'
        assert doc1.url_for('edit') == '/document1/edit'
        # Test callable parameters
        assert doc1.url_for('upper') == '/DOCUMENT1/upper'
        # Insist on changing one of the parameters
        assert doc1.url_for('edit', doc=doc1.name.upper()) == '/DOCUMENT1/edit'
        # Confirm second returns the correct paths
        assert doc2.url_for() == '/1/document2'
        assert doc2.url_for('view') == '/1/document2'
        # Test _external flag
        assert doc2.url_for('edit') == 'http://localhost/1/document2/edit'
        assert doc2.url_for('edit', _external=False) == '/1/document2/edit'
        assert doc2.url_for('edit', _external=True) == 'http://localhost/1/document2/edit'

    def test_absolute_url(self):
        """
        The .absolute_url property is the same as .url_for(_external=True)
        """
        # Make two documents
        doc1 = NamedDocument(name=u'document1', title=u"Document 1")
        self.session.add(doc1)
        c1 = Container()  # Gets an autoincrementing id starting from 1
        self.session.add(c1)
        doc2 = ScopedNamedDocument(container=c1, name=u'document2', title=u"Document 2")
        self.session.add(doc2)
        self.session.commit()

        assert doc1.absolute_url == doc1.url_for(_external=True)
        assert doc1.absolute_url != doc1.url_for(_external=False)
        assert doc2.absolute_url == doc2.url_for(_external=True)
        assert doc2.absolute_url != doc2.url_for(_external=False)

    def test_per_app(self):
        """Allow app-specific URLs for the same action name"""
        doc1 = NamedDocument(name=u'document1', title=u"Document 1")
        self.session.add(doc1)
        self.session.commit()

        # The action's URL is specific to the app
        assert doc1.url_for('per_app') == '/document1/app1'

    def test_app_only(self):
        """Allow URLs to only be available in one app"""
        doc1 = NamedDocument(name=u'document1', title=u"Document 1")
        self.session.add(doc1)
        self.session.commit()

        # This action is only available in this app
        assert doc1.url_for('app_only') == '/document1/app_only'


class TestUrlFor2(TestUrlForBase):
    app = app2

    def test_per_app(self):
        """Allow app-specific URLs for the same action name"""
        doc1 = NamedDocument(name=u'document1', title=u"Document 1")
        self.session.add(doc1)
        self.session.commit()

        # The action's URL is specific to the app
        assert doc1.url_for('per_app') == '/document1/app2'

    def test_app_only(self):
        """Allow URLs to only be available in one app"""
        doc1 = NamedDocument(name=u'document1', title=u"Document 1")
        self.session.add(doc1)
        self.session.commit()

        # This action is not available in this app
        with self.assertRaises(BuildError):
            doc1.url_for('app_only')
