# -*- coding: utf-8 -*-

from __future__ import absolute_import, unicode_literals

import unittest
from flask import Flask, json
from coaster.sqlalchemy import BaseNameMixin, BaseScopedNameMixin
from coaster.db import db
from coaster.views import ClassView, route, requestform, render_with


app = Flask(__name__)
app.testing = True
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)


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
    @requestform('title')
    def edit(self, name, title):
        document = ViewDocument.query.filter_by(name=name).first_or_404()
        document.title = title
        return 'edited!'

DocumentView.init_app(app)


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
        assert rv.data == 'index'.encode('utf-8')

    def test_page(self):
        rv = self.client.get('/page')
        assert rv.data == 'page'.encode('utf-8')

    def test_document_404(self):
        rv = self.client.get('/doc/non-existant')
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
