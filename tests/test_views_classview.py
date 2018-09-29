# -*- coding: utf-8 -*-

from __future__ import absolute_import, unicode_literals

import unittest
from flask import Flask, json
from coaster.sqlalchemy import BaseNameMixin, BaseScopedNameMixin, BaseIdNameMixin
from coaster.auth import add_auth_attribute
from coaster.utils import InspectableSet
from coaster.db import SQLAlchemy
from coaster.views import (ClassView, ModelView, UrlForView, UrlChangeCheck, InstanceLoader,
    route, viewdata, requestargs, requestform, render_with, current_view, requires_permission)


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

    def permissions(self, actor, inherited=()):
        perms = super(ViewDocument, self).permissions(actor, inherited)
        if actor == 'this-is-the-owner':  # Our hack of a user object, for testing
            perms.add('edit')
            perms.add('delete')
        return perms


class ScopedViewDocument(BaseScopedNameMixin, db.Model):
    __tablename__ = 'scoped_view_document'
    parent_id = db.Column(None, db.ForeignKey('view_document.id'), nullable=False)
    view_document = db.relationship(ViewDocument, backref=db.backref('children', cascade='all, delete-orphan'))
    parent = db.synonym('view_document')

    __roles__ = {
        'all': {
            'read': {'name', 'title', 'doctype'}
            }
        }

    @property
    def doctype(self):
        return 'scoped-doc'


class RenameableDocument(BaseIdNameMixin, db.Model):
    __tablename__ = 'renameable_document'
    __uuid_primary_key__ = False  # So that we can get consistent `1-<name>` url_name in tests
    __roles__ = {
        'all': {
            'read': {'name', 'title'}
            }
        }


# --- Views -------------------------------------------------------------------

@route('/')
class IndexView(ClassView):
    @route('')
    @viewdata(title="Index")
    def index(self):
        return 'index'

    @viewdata(title="Page")
    @route('page')
    def page(self):
        return 'page'

    @route('current_view')
    def current_view_is_self(self):
        return str(current_view == self)

    @route('current_view/current_handler_is_self')
    def current_handler_is_self(self):
        return str(current_view.current_handler.name == 'current_handler_is_self')

    @route('current_view/current_handler_is_wrapper')
    def current_handler_is_wrapper(self):
        return str(current_view.current_handler == self.current_handler_is_wrapper)

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
    @viewdata(title="First")
    def first(self):
        return 'first'

    @viewdata(title="Second")
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

    def latent_route(self):
        return 'latent-route'


@route('/subclasstest')
class SubView(BaseView):
    @viewdata(title="Still first")
    @BaseView.first.reroute
    def first(self):
        return 'rerouted-first'

    @route('2')
    @BaseView.second.reroute
    @viewdata(title="Not still second")
    def second(self):
        return 'rerouted-second'

    def third(self):
        return 'removed-third'

SubView.add_route_for('also_inherited', '/inherited')
SubView.add_route_for('also_inherited', 'inherited2', endpoint='just_also_inherited')
SubView.add_route_for('latent_route', 'latent')
SubView.init_app(app)


@route('/secondsub')
class AnotherSubView(BaseView):
    @route('2-2')
    @BaseView.second.reroute
    def second(self):
        return 'also-rerouted-second'

AnotherSubView.init_app(app)


@route('/model/<document>')
class ModelDocumentView(UrlForView, InstanceLoader, ModelView):
    model = ViewDocument
    route_model_map = {
        'document': 'name',
        }

    @requestargs('access_token')
    def before_request(self, kwargs, access_token=None):
        if access_token == 'owner-admin-secret':
            add_auth_attribute('permissions', InspectableSet({'siteadmin'}))
            add_auth_attribute('user', 'this-is-the-owner')  # See ViewDocument.permissions
        if access_token == 'owner-secret':
            add_auth_attribute('user', 'this-is-the-owner')  # See ViewDocument.permissions
        return super(ModelDocumentView, self).before_request(kwargs)

    @route('')
    @render_with(json=True)
    def view(self, **kwargs):
        return self.obj.current_access()

    @route('edit', methods=['GET', 'POST'])
    @route('', methods=['PUT'])
    @requires_permission('edit')
    def edit(self, **kwargs):
        return 'edit-called'

ModelDocumentView.init_app(app)


@route('/model/<parent>/<document>')
class ScopedDocumentView(ModelDocumentView):
    model = ScopedViewDocument
    route_model_map = {
        'document': 'name',
        'parent': 'parent.name',
        }

ScopedDocumentView.init_app(app)


@route('/rename/<document>')
class RenameableDocumentView(UrlChangeCheck, InstanceLoader, ModelView):
    model = RenameableDocument
    route_model_map = {
        'document': 'url_name',
        }

    @route('')
    @render_with(json=True)
    def view(self, **kwargs):
        return self.obj.current_access()

RenameableDocumentView.init_app(app)


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
        """Test index view (/)"""
        rv = self.client.get('/')
        assert rv.data == b'index'

    def test_page(self):
        """Test page view (/page)"""
        rv = self.client.get('/page')
        assert rv.data == b'page'

    def test_current_view(self):
        rv = self.client.get('/current_view')
        assert rv.data == b'True'

    def test_current_handler_is_self(self):
        rv = self.client.get('/current_view/current_handler_is_self')
        assert rv.data == b'True'

    def test_current_handler_is_wrapper(self):
        rv = self.client.get('/current_view/current_handler_is_wrapper')
        assert rv.data == b'True'

    def test_document_404(self):
        """Test 404 response from within a view"""
        rv = self.client.get('/doc/this-doc-does-not-exist')
        assert rv.status_code == 404  # This 404 came from DocumentView.view

    def test_document_view(self):
        """Test document view (loaded from database)"""
        doc = ViewDocument(name='test1', title="Test")
        self.session.add(doc)
        self.session.commit()

        rv = self.client.get('/doc/test1')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['name'] == 'test1'
        assert data['title'] == "Test"

    def test_document_edit(self):
        """POST handler shares URL with GET handler but is routed to correctly"""
        doc = ViewDocument(name='test1', title="Test")
        self.session.add(doc)
        self.session.commit()

        self.client.post('/doc/test1/edit', data={'title': "Edit 1"})
        assert doc.title == "Edit 1"
        self.client.post('/edit/test1', data={'title': "Edit 2"})
        assert doc.title == "Edit 2"
        self.client.post('/doc/test1', data={'title': "Edit 3"})
        assert doc.title == "Edit 3"

    def test_callable_view(self):
        """View handlers are callable as regular methods"""
        doc = ViewDocument(name='test1', title="Test")
        self.session.add(doc)
        self.session.commit()

        rv = DocumentView().view('test1')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['name'] == 'test1'
        assert data['title'] == "Test"

        rv = DocumentView().edit('test1', "Edited")
        assert rv == 'edited!'
        assert doc.title == "Edited"

    def test_rerouted(self):
        """Subclass replaces view handler"""
        rv = self.client.get('/subclasstest')
        assert rv.data != b'first'
        assert rv.data == b'rerouted-first'
        assert rv.status_code == 200

    def test_rerouted_with_new_routes(self):
        """Subclass replaces view handler and adds new routes"""
        rv = self.client.get('/subclasstest/second')
        assert rv.data != b'second'
        assert rv.data == b'rerouted-second'
        assert rv.status_code == 200
        rv = self.client.get('/subclasstest/2')
        assert rv.data != b'second'
        assert rv.data == b'rerouted-second'
        assert rv.status_code == 200

    def test_unrouted(self):
        """Subclass removes a route from base class"""
        rv = self.client.get('/subclasstest/third')
        assert rv.data != b'third'
        assert rv.data != b'unrouted-third'
        assert rv.status_code == 404

    def test_inherited(self):
        """Subclass inherits a view from the base class without modifying it"""
        rv = self.client.get('/subclasstest/inherited')
        assert rv.data == b'inherited'
        assert rv.status_code == 200

    def test_added_routes(self):
        """Subclass adds more routes to a base class's view handler"""
        rv = self.client.get('/subclasstest/also-inherited')  # From base class
        assert rv.data == b'also_inherited'
        rv = self.client.get('/subclasstest/inherited2')  # Added in sub class
        assert rv.data == b'also_inherited'
        rv = self.client.get('/inherited')  # Added in sub class
        assert rv.data == b'also_inherited'
        rv = self.client.get('/subclasstest/latent')
        assert rv.data == b'latent-route'

    def test_cant_route_missing_method(self):
        """Routes can't be added for missing attributes"""
        with self.assertRaises(AttributeError):
            SubView.add_route_for('this_method_does_not_exist', '/missing')

    def test_second_subview_reroute(self):
        """Using reroute does not mutate the base class"""
        rv = self.client.get('/secondsub/second')
        assert rv.data != b'second'
        assert rv.data == b'also-rerouted-second'
        assert rv.status_code == 200
        rv = self.client.get('/secondsub/2-2')
        assert rv.data != b'second'
        assert rv.data == b'also-rerouted-second'
        assert rv.status_code == 200
        # Confirm we did not accidentally acquire this from SubView's use of reroute
        rv = self.client.get('/secondsub/2')
        assert rv.status_code == 404

    def test_endpoints(self):
        """View handlers get endpoints reflecting where they are"""
        assert IndexView.index.endpoints == {'IndexView_index'}
        assert IndexView.page.endpoints == {'IndexView_page'}
        assert BaseView.first.endpoints == set()
        assert SubView.first.endpoints == {'SubView_first'}
        assert BaseView.second.endpoints == set()
        assert SubView.second.endpoints == {'SubView_second'}
        assert AnotherSubView.second.endpoints == {'AnotherSubView_second'}
        assert BaseView.inherited.endpoints == set()
        assert SubView.inherited.endpoints == {'SubView_inherited'}
        assert BaseView.also_inherited.endpoints == set()
        assert SubView.also_inherited.endpoints == {'SubView_also_inherited', 'just_also_inherited'}

    def test_viewdata(self):
        """View handlers can have additional data fields"""
        assert IndexView.index.data['title'] == "Index"
        assert IndexView.page.data['title'] == "Page"
        assert BaseView.first.data['title'] == "First"
        assert BaseView.second.data['title'] == "Second"
        assert SubView.first.data['title'] == "Still first"
        assert SubView.second.data['title'] != "Not still second"  # Reroute took priority
        assert SubView.second.data['title'] == "Second"

    def test_viewlist(self):
        assert IndexView.__views__ == {
            'current_handler_is_self', 'current_handler_is_wrapper', 'current_view_is_self', 'index', 'page'}

    def test_modelview_instanceloader_view(self):
        """Test document view in ModelView with InstanceLoader"""
        doc = ViewDocument(name='test1', title="Test")
        self.session.add(doc)
        self.session.commit()

        rv = self.client.get('/model/test1')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['name'] == 'test1'
        assert data['title'] == "Test"

    def test_modelview_instanceloader_requires_permission_edit(self):
        """Test document edit in ModelView with InstanceLoader and requires_permission"""
        doc = ViewDocument(name='test1', title="Test")
        self.session.add(doc)
        self.session.commit()

        rv = self.client.post('/model/test1/edit')
        assert rv.status_code == 403
        rv = self.client.post('/model/test1/edit?access_token=owner-secret')
        assert rv.status_code == 200
        assert rv.data == b'edit-called'
        rv = self.client.post('/model/test1/edit?access_token=owner-admin-secret')
        assert rv.status_code == 200
        assert rv.data == b'edit-called'

    def test_modelview_url_for(self):
        """Test that ModelView provides model.is_url_for with appropriate parameters"""
        doc1 = ViewDocument(name='test1', title="Test 1")
        doc2 = ViewDocument(name='test2', title="Test 2")

        assert doc1.url_for('view') == '/model/test1'
        assert doc2.url_for('view') == '/model/test2'

    def test_scopedmodelview_view(self):
        """Test that InstanceLoader in a scoped model correctly loads parent"""
        doc = ViewDocument(name='test1', title="Test 1")
        sdoc = ScopedViewDocument(name='test2', title="Test 2", parent=doc)
        self.session.add_all([doc, sdoc])
        self.session.commit()

        rv = self.client.get('/model/test1/test2')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['name'] == 'test2'
        assert data['doctype'] == 'scoped-doc'

        # The joined load actually worked
        rv = self.client.get('/model/this-doc-does-not-exist/test2')
        assert rv.status_code == 404

    def test_redirectablemodel_view(self):
        doc = RenameableDocument(name='test1', title="Test 1")
        self.session.add(doc)
        self.session.commit()

        rv = self.client.get('/rename/1-test1')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['name'] == 'test1'

        doc.name = 'renamed'
        self.session.commit()

        rv = self.client.get('/rename/1-test1?preserve=this')
        assert rv.status_code == 302
        assert rv.location == 'http://localhost/rename/1-renamed?preserve=this'

        rv = self.client.get('/rename/1-renamed')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['name'] == 'renamed'
