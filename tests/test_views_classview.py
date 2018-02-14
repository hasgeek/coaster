# -*- coding: utf-8 -*-

from __future__ import absolute_import, unicode_literals

import unittest
from flask import Flask, json
from coaster.sqlalchemy import BaseNameMixin, BaseScopedNameMixin
from coaster.db import SQLAlchemy
from coaster.views import ClassView, route, requestform, render_with


app = Flask(__name__)
app.testing = True
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


# --- Models ------------------------------------------------------------------

class ViewDocument(BaseNameMixin, db.Model):
    __tablename__ = 'view_document'
    __roles__ = {
        'all': {
            'read': {'name', 'title'}
            }
        }


class ScopedViewDocument(BaseScopedNameMixin, db.Model):
    __tablename__ = 'scoped_view_document'
    parent_id = db.Column(None, db.ForeignKey('view_document.id'), nullable=False)
    parent = db.relationship(ViewDocument, backref=db.backref('children', cascade='all, delete-orphan'))


# --- Views -------------------------------------------------------------------

@route('/')
class IndexView(ClassView):
    @route('')
    def index(self):
        return 'index'

    @route('page')
    def page(self):
        return 'page'

IndexView.init_app(app)


@route('/doc/<name>')
class DocumentView(ClassView):
    @route('')
    @render_with(json=True)
    def view(self, name):
        document = ViewDocument.query.filter_by(name=name).first_or_404()
        return document.current_access()

    @route('edit', methods=['POST'])  # Maps to /doc/<name>/edit
    @route('/edit/<name>', methods=['POST'])  # Maps to /edit/<name>
    @route('', methods=['POST'])  # Maps to /doc/<name>
    @requestform('title')
    def edit(self, name, title):
        document = ViewDocument.query.filter_by(name=name).first_or_404()
        document.title = title
        return 'edited!'

DocumentView.init_app(app)


class BaseView(ClassView):
    @route('')
    def first(self):
        return 'first'

    @route('second')
    def second(self):
        return 'second'

    @route('third')
    def third(self):
        return 'third'

    @route('inherited')
    def inherited(self):
        return 'inherited'

    @route('also-inherited')
    def also_inherited(self):
        return 'also_inherited'


@route('/subclasstest')
class SubView(BaseView):
    @BaseView.first.reroute
    def first(self):
        return 'rerouted-first'

    @route('2')
    @BaseView.second.reroute
    def second(self):
        return 'rerouted-second'

    def third(self):
        return 'removed-third'

SubView.init_app(app)


# --- Tests -------------------------------------------------------------------

class TestClassView(unittest.TestCase):
    app = app

    def setUp(self):
        self.ctx = self.app.test_request_context()
        self.ctx.push()
        db.create_all()
        self.session = db.session
        self.client = self.app.test_client()

    def tearDown(self):
        self.session.rollback()
        db.drop_all()
        self.ctx.pop()

    def test_index(self):
        rv = self.client.get('/')
        assert rv.data == b'index'

    def test_page(self):
        rv = self.client.get('/page')
        assert rv.data == b'page'

    def test_document_404(self):
        rv = self.client.get('/doc/this-doc-does-not-exist')
        assert rv.status_code == 404  # This 404 came from DocumentView.view

    def test_document_view(self):
        doc = ViewDocument(name='test1', title="Test")
        self.session.add(doc)
        self.session.commit()
        rv = self.client.get('/doc/test1')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['name'] == 'test1'
        assert data['title'] == "Test"

    def test_document_edit(self):
        doc = ViewDocument(name='test1', title="Test")
        self.session.add(doc)
        self.session.commit()
        self.client.post('/doc/test1/edit', data={'title': "Edit 1"})
        assert doc.title == "Edit 1"
        self.client.post('/edit/test1', data={'title': "Edit 2"})
        assert doc.title == "Edit 2"
        self.client.post('/doc/test1', data={'title': "Edit 3"})
        assert doc.title == "Edit 3"

    def test_rerouted(self):
        rv = self.client.get('/subclasstest')
        assert rv.data != b'first'
        assert rv.data == b'rerouted-first'
        assert rv.status_code == 200
        rv = self.client.get('/subclasstest/second')
        assert rv.data != b'second'
        assert rv.data == b'rerouted-second'
        assert rv.status_code == 200
        rv = self.client.get('/subclasstest/2')
        assert rv.data != b'second'
        assert rv.data == b'rerouted-second'
        assert rv.status_code == 200

    def test_unrouted(self):
        rv = self.client.get('/subclasstest/third')
        assert rv.data != b'third'
        assert rv.data != b'unrouted-third'
        assert rv.status_code == 404

    def test_inherited(self):
        rv = self.client.get('/subclasstest/inherited')
        assert rv.data == b'inherited'
