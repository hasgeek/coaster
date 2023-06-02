"""Test classviews."""
# pylint: disable=comparison-with-callable

from typing import cast
import typing as t
import unittest

from flask import Flask, json
from flask.ctx import RequestContext
from flask.typing import ResponseReturnValue
from sqlalchemy.orm import Mapped
from werkzeug.exceptions import Forbidden
import pytest
import sqlalchemy as sa

from coaster.app import JSONProvider
from coaster.auth import add_auth_attribute
from coaster.sqlalchemy import (
    BaseIdNameMixin,
    BaseNameMixin,
    BaseScopedNameMixin,
    LazyRoleSet,
    relationship,
)
from coaster.utils import InspectableSet
from coaster.views import (
    ClassView,
    InstanceLoader,
    ModelView,
    UrlChangeCheck,
    UrlForView,
    current_view,
    render_with,
    requestargs,
    requestform,
    requires_permission,
    requires_roles,
    route,
    viewdata,
)

from .conftest import Model, db, sqlalchemy_uri

app = Flask(__name__)
app.json = JSONProvider(app)
app.testing = True
app.config['SQLALCHEMY_DATABASE_URI'] = sqlalchemy_uri()
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)


# --- Models ---------------------------------------------------------------------------


class ViewDocument(BaseNameMixin, Model):
    __tablename__ = 'view_document'
    __roles__ = {'all': {'read': {'name', 'title'}}}

    def permissions(
        self, actor: t.Optional[str], inherited: t.Optional[t.Set[str]] = None
    ) -> t.Set[str]:
        perms = super().permissions(actor, inherited)
        perms.add('view')
        if actor in (
            'this-is-the-owner',
            'this-is-the-editor',
        ):  # Our hack of a user object, for testing
            perms.add('edit')
            perms.add('delete')
        return perms

    def roles_for(
        self, actor: t.Optional[str] = None, anchors: t.Sequence[t.Any] = ()
    ) -> LazyRoleSet:
        roles = super().roles_for(actor, anchors)
        if actor in ('this-is-the-owner', 'this-is-another-owner'):
            roles.add('owner')
        return roles


class ScopedViewDocument(BaseScopedNameMixin, Model):
    __tablename__ = 'scoped_view_document'
    parent_id: Mapped[int] = sa.orm.mapped_column(
        sa.ForeignKey('view_document.id'), nullable=False
    )
    view_document: Mapped[ViewDocument] = relationship(
        ViewDocument, backref=sa.orm.backref('children', cascade='all, delete-orphan')
    )
    parent = sa.orm.synonym('view_document')

    __roles__ = {'all': {'read': {'name', 'title', 'doctype'}}}

    @property
    def doctype(self) -> str:
        return 'scoped-doc'


class RenameableDocument(BaseIdNameMixin, Model):
    __tablename__ = 'renameable_document'
    __uuid_primary_key__ = (
        False  # So that we can get consistent `1-<name>` url_name in tests
    )
    __roles__ = {'all': {'read': {'name', 'title'}}}


# --- Views ----------------------------------------------------------------------------


@route('/')
class IndexView(ClassView):
    """Test ClassView."""

    @route('')
    @viewdata(title="Index")
    def index(self) -> str:
        return 'index'

    @viewdata(title="Page")
    @route('page')
    def page(self) -> str:
        return 'page'

    @route('current_view')
    def current_view_is_self(self) -> str:
        return str(current_view == self)

    @route('current_view/current_handler_is_self')
    def current_handler_is_self(self) -> str:
        return str(current_view.current_handler.name == 'current_handler_is_self')

    @route('current_view/current_handler_is_wrapper')
    def current_handler_is_wrapper(self) -> str:
        # pylint: disable=comparison-with-callable
        return str(current_view.current_handler == self.current_handler_is_wrapper)

    @route('view_args/<one>/<two>')
    def view_args_are_received(self, **kwargs) -> str:
        # pylint: disable=consider-using-f-string
        return '{one}/{two}'.format(**self.view_args)


IndexView.init_app(app)


@route('/doc/<name>')
class DocumentView(ClassView):
    """Test ClassView for ViewDocument."""

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
    """Test ClassView base class."""

    @route('')
    @viewdata(title="First")
    def first(self) -> str:
        return 'first'

    @viewdata(title="Second")
    @route('second')
    def second(self) -> str:
        return 'second'

    @route('third')
    def third(self) -> str:
        return 'third'

    @route('inherited')
    def inherited(self) -> str:
        return 'inherited'

    @route('also-inherited')
    def also_inherited(self) -> str:
        return 'also_inherited'

    def latent_route(self) -> str:
        return 'latent-route'


@route('/subclasstest')
class SubView(BaseView):
    """Test subclass of a ClassView."""

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
    """Test second subclass of a ClassView."""

    @route('2-2')
    @BaseView.second.reroute
    def second(self):
        return 'also-rerouted-second'


AnotherSubView.init_app(app)


@route('/model/<document>')
class ModelDocumentView(UrlForView, InstanceLoader, ModelView):
    """Test ModelView."""

    model = ViewDocument
    route_model_map = {'document': 'name'}

    @requestargs('access_token')
    def before_request(
        self, access_token: t.Optional[str] = None
    ) -> t.Optional[ResponseReturnValue]:
        if access_token == 'owner-admin-secret':  # nosec
            add_auth_attribute('permissions', InspectableSet({'siteadmin'}))
            add_auth_attribute(
                'user', 'this-is-the-owner'
            )  # See ViewDocument.permissions
        if access_token == 'owner-secret':  # nosec
            add_auth_attribute(
                'user', 'this-is-the-owner'
            )  # See ViewDocument.permissions
        return super().before_request()

    @route('')
    @render_with(json=True)
    def view(self):
        return self.obj.current_access()

    @route('edit', methods=['GET', 'POST'])
    @route('', methods=['PUT'])
    @requires_permission('edit')
    def edit(self):
        return 'edit-called'


ViewDocument.views.main = ModelDocumentView
ModelDocumentView.init_app(app)


@route('/model/<parent>/<document>')
class ScopedDocumentView(ModelDocumentView):
    """Test subclass of a ModelView."""

    model = ScopedViewDocument  # type: ignore[assignment]
    route_model_map = {'document': 'name', 'parent': 'parent.name'}


ScopedViewDocument.views.main = ScopedDocumentView
ScopedDocumentView.init_app(app)


@route('/rename/<document>')
class RenameableDocumentView(UrlChangeCheck, UrlForView, InstanceLoader, ModelView):
    """Test ModelView for a document that will auto-redirect if the URL changes."""

    model = RenameableDocument
    route_model_map = {'document': 'url_name'}

    @route('')
    @render_with(json=True)
    def view(self):
        return self.obj.current_access()


RenameableDocument.views.main = RenameableDocumentView
RenameableDocumentView.init_app(app)


@route('/multi/<doc1>/<doc2>')
class MultiDocumentView(UrlForView, ModelView):
    """Test ModelView that has multiple documents."""

    model = ViewDocument
    route_model_map = {'doc1': 'name', 'doc2': '**doc2.url_name'}

    def loader(self, doc1: str, doc2: str) -> t.Tuple[ViewDocument, RenameableDocument]:
        obj1 = ViewDocument.query.filter_by(name=doc1).first_or_404()
        obj2 = RenameableDocument.query.filter_by(url_name=doc2).first_or_404()
        return (obj1, obj2)

    @route('')
    @requires_permission('view')
    def linked_view(self):
        return self.obj[0].url_for('linked_view', doc2=self.obj[1])


MultiDocumentView.init_app(app)


@route('/gated/<document>')
class GatedDocumentView(UrlForView, InstanceLoader, ModelView):
    """Test ModelView that has an intercept in before_request."""

    model = ViewDocument
    route_model_map = {'document': 'name'}

    @requestargs('access_token')
    def before_request(
        self, access_token: t.Optional[str] = None
    ) -> t.Optional[ResponseReturnValue]:
        if access_token == 'owner-secret':  # nosec
            add_auth_attribute(
                'user', 'this-is-the-owner'
            )  # See ViewDocument.permissions
        if access_token == 'editor-secret':  # nosec
            add_auth_attribute(
                'user', 'this-is-the-editor'
            )  # See ViewDocument.permissions
        if access_token == 'another-owner-secret':  # nosec
            add_auth_attribute(
                'user', 'this-is-another-owner'
            )  # See ViewDocument.permissions
        return super().before_request()

    @route('perm')
    @requires_permission('edit')
    def by_perm(self):
        return 'perm-called'

    @route('role')
    @requires_roles({'owner'})
    def by_role(self):
        return 'role-called'

    @route('perm-role')
    @requires_permission('edit')
    @requires_roles({'owner'})
    def by_perm_role(self):
        return 'perm-role-called'

    @route('role-perm')
    @requires_roles({'owner'})
    @requires_permission('edit')
    def by_role_perm(self):
        return 'role-perm-called'


ViewDocument.views.gated = GatedDocumentView
GatedDocumentView.init_app(app)


# --- Tests ----------------------------------------------------------------------------


class TestClassView(unittest.TestCase):
    """Tests for ClassView and ModelView."""

    app = app
    ctx: RequestContext

    def setUp(self) -> None:
        self.ctx = cast(RequestContext, self.app.test_request_context())
        self.ctx.push()
        db.create_all()
        self.session = db.session
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.session.rollback()
        db.drop_all()
        self.ctx.pop()

    def test_index(self) -> None:
        """Test index view (/)"""
        rv = self.client.get('/')
        assert rv.data == b'index'

    def test_page(self) -> None:
        """Test page view (/page)"""
        rv = self.client.get('/page')
        assert rv.data == b'page'

    def test_current_view(self) -> None:
        rv = self.client.get('/current_view')
        assert rv.data == b'True'

    def test_current_handler_is_self(self) -> None:
        rv = self.client.get('/current_view/current_handler_is_self')
        assert rv.data == b'True'

    def test_current_handler_is_wrapper(self) -> None:
        rv = self.client.get('/current_view/current_handler_is_wrapper')
        assert rv.data == b'True'

    def test_view_args_are_received(self) -> None:
        rv = self.client.get('/view_args/one/two')
        assert rv.data == b'one/two'
        rv = self.client.get('/view_args/three/four')
        assert rv.data == b'three/four'

    def test_document_404(self) -> None:
        """Test 404 response from within a view"""
        rv = self.client.get('/doc/this-doc-does-not-exist')
        assert rv.status_code == 404  # This 404 came from DocumentView.view

    def test_document_view(self) -> None:
        """Test document view (loaded from database)"""
        doc = ViewDocument(name='test1', title="Test")
        self.session.add(doc)
        self.session.commit()

        rv = self.client.get('/doc/test1')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['name'] == 'test1'
        assert data['title'] == "Test"

    def test_document_edit(self) -> None:
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

    def test_callable_view(self) -> None:
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

    def test_rerouted(self) -> None:
        """Subclass replaces view handler"""
        rv = self.client.get('/subclasstest')
        assert rv.data != b'first'
        assert rv.data == b'rerouted-first'
        assert rv.status_code == 200

    def test_rerouted_with_new_routes(self) -> None:
        """Subclass replaces view handler and adds new routes"""
        rv = self.client.get('/subclasstest/second')
        assert rv.data != b'second'
        assert rv.data == b'rerouted-second'
        assert rv.status_code == 200
        rv = self.client.get('/subclasstest/2')
        assert rv.data != b'second'
        assert rv.data == b'rerouted-second'
        assert rv.status_code == 200

    def test_unrouted(self) -> None:
        """Subclass removes a route from base class"""
        rv = self.client.get('/subclasstest/third')
        assert rv.data != b'third'
        assert rv.data != b'unrouted-third'
        assert rv.status_code == 404

    def test_inherited(self) -> None:
        """Subclass inherits a view from the base class without modifying it"""
        rv = self.client.get('/subclasstest/inherited')
        assert rv.data == b'inherited'
        assert rv.status_code == 200

    def test_added_routes(self) -> None:
        """Subclass adds more routes to a base class's view handler"""
        rv = self.client.get('/subclasstest/also-inherited')  # From base class
        assert rv.data == b'also_inherited'
        rv = self.client.get('/subclasstest/inherited2')  # Added in sub class
        assert rv.data == b'also_inherited'
        rv = self.client.get('/inherited')  # Added in sub class
        assert rv.data == b'also_inherited'
        rv = self.client.get('/subclasstest/latent')
        assert rv.data == b'latent-route'

    def test_cant_route_missing_method(self) -> None:
        """Routes can't be added for missing attributes"""
        with pytest.raises(AttributeError):
            SubView.add_route_for('this_method_does_not_exist', '/missing')

    def test_second_subview_reroute(self) -> None:
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

    def test_endpoints(self) -> None:
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
        assert SubView.also_inherited.endpoints == {
            'SubView_also_inherited',
            'just_also_inherited',
        }

    def test_viewdata(self) -> None:
        """View handlers can have additional data fields"""
        assert IndexView.index.data['title'] == "Index"
        assert IndexView.page.data['title'] == "Page"
        assert BaseView.first.data['title'] == "First"
        assert BaseView.second.data['title'] == "Second"
        assert SubView.first.data['title'] == "Still first"
        assert (
            SubView.second.data['title'] != "Not still second"
        )  # Reroute took priority
        assert SubView.second.data['title'] == "Second"

    def test_viewlist(self) -> None:
        assert IndexView.__views__ == {
            'current_handler_is_self',
            'current_handler_is_wrapper',
            'current_view_is_self',
            'index',
            'page',
            'view_args_are_received',
        }

    def test_modelview_instanceloader_view(self) -> None:
        """Test document view in ModelView with InstanceLoader"""
        doc = ViewDocument(name='test1', title="Test")
        self.session.add(doc)
        self.session.commit()

        rv = self.client.get('/model/test1')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['name'] == 'test1'
        assert data['title'] == "Test"

    def test_modelview_instanceloader_requires_permission_edit(self) -> None:
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

    def test_modelview_url_for(self) -> None:
        """Test that ModelView provides model.is_url_for with appropriate parameters"""
        doc1 = ViewDocument(name='test1', title="Test 1")
        doc2 = ViewDocument(name='test2', title="Test 2")

        assert doc1.url_for('view') == '/model/test1'
        assert doc2.url_for('view') == '/model/test2'

    def test_scopedmodelview_view(self) -> None:
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

    def test_redirectablemodel_view(self) -> None:
        doc = RenameableDocument(name='test1', title="Test 1")
        self.session.add(doc)
        self.session.commit()

        rv = self.client.get('/rename/1-test1')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['name'] == 'test1'

        doc.name = 'renamed'
        self.session.commit()

        rv = self.client.get('/rename/1-test1')
        assert rv.status_code == 302
        assert rv.location == 'http://localhost/rename/1-renamed'

        rv = self.client.get('/rename/1-test1?preserve=this')
        assert rv.status_code == 302
        assert rv.location == 'http://localhost/rename/1-renamed?preserve=this'

        rv = self.client.get('/rename/1-test1?utf-8=✓')
        assert rv.status_code == 302
        # UTF-8 query parameters will be encoded by urlunsplit. There does not appear
        # to be a way to disable this.
        assert rv.location == 'http://localhost/rename/1-renamed?utf-8=%E2%9C%93'

        rv = self.client.get('/rename/1-renamed')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['name'] == 'renamed'

    def test_multi_view(self) -> None:
        """
        A ModelView view can handle multiple objects and also construct URLs
        for objects that do not have a well defined relationship between each other.
        """
        doc1 = ViewDocument(name='test1', title="Test 1")
        doc2 = RenameableDocument(name='test2', title="Test 2")
        self.session.add_all([doc1, doc2])
        self.session.commit()

        rv = self.client.get('/multi/test1/1-test2')
        assert rv.status_code == 200
        assert rv.data == b'/multi/test1/1-test2'

    def test_registered_views(self) -> None:
        doc1 = ViewDocument(name='test1', title="Test 1")
        doc2 = ScopedViewDocument(name='test2', title="Test 2", parent=doc1)
        doc3 = RenameableDocument(name='test3', title="Test 3")
        self.session.add_all([doc1, doc2, doc3])
        self.session.commit()

        assert ViewDocument.views.main is ModelDocumentView
        assert ScopedViewDocument.views.main is ScopedDocumentView
        assert RenameableDocument.views.main is RenameableDocumentView

        assert isinstance(doc1.views.main(), ModelDocumentView)
        assert isinstance(doc2.views.main(), ScopedDocumentView)
        assert isinstance(doc3.views.main(), RenameableDocumentView)

    def test_view_for(self) -> None:
        doc = ViewDocument(name='test1', title="Test")
        self.session.add(doc)
        self.session.commit()

        assert doc.classview_for() == ModelDocumentView(doc)
        assert doc.classview_for('edit') == ModelDocumentView(doc)
        assert doc.classview_for('by_perm') == GatedDocumentView(doc)

        # doc.view_for() returns the view handler. Calling it with
        # _render=False will disable the @render_with wrapper.
        assert dict(doc.view_for()(_render=False)) == {
            'name': doc.name,
            'title': doc.title,
        }

        # Calling the 'edit' view will abort with a Forbidden as we have
        # not granted any access rights in the request context
        with pytest.raises(Forbidden):
            doc.view_for('edit')()

    def test_requires_roles_layered1(self) -> None:
        doc = ViewDocument(name='test1', title="Test")
        self.session.add(doc)
        self.session.commit()

        # All four gates refuse access without appropriate
        # permission or role
        rv = self.client.get('/gated/test1/perm')
        assert rv.status_code == 403
        rv = self.client.get('/gated/test1/role')
        assert rv.status_code == 403
        rv = self.client.get('/gated/test1/perm-role')
        assert rv.status_code == 403
        rv = self.client.get('/gated/test1/role-perm')
        assert rv.status_code == 403

    def test_requires_roles_layered2(self) -> None:
        doc = ViewDocument(name='test1', title="Test")
        self.session.add(doc)
        self.session.commit()

        # All four gates grant access if we have 'owner' role
        # with 'edit' permission
        rv = self.client.get('/gated/test1/perm?access_token=owner-secret')
        assert rv.status_code == 200
        assert rv.data == b'perm-called'
        rv = self.client.get('/gated/test1/role?access_token=owner-secret')
        assert rv.status_code == 200
        assert rv.data == b'role-called'
        rv = self.client.get('/gated/test1/perm-role?access_token=owner-secret')
        assert rv.status_code == 200
        assert rv.data == b'perm-role-called'
        rv = self.client.get('/gated/test1/role-perm?access_token=owner-secret')
        assert rv.status_code == 200
        assert rv.data == b'role-perm-called'

    def test_requires_roles_layered3(self) -> None:
        doc = ViewDocument(name='test1', title="Test")
        self.session.add(doc)
        self.session.commit()

        # Now we are 'owner' but without 'edit' permission
        # Only one goes through
        rv = self.client.get('/gated/test1/perm?access_token=another-owner-secret')
        assert rv.status_code == 403
        rv = self.client.get('/gated/test1/role?access_token=another-owner-secret')
        assert rv.status_code == 200
        assert rv.data == b'role-called'
        rv = self.client.get('/gated/test1/perm-role?access_token=another-owner-secret')
        assert rv.status_code == 403
        rv = self.client.get('/gated/test1/role-perm?access_token=another-owner-secret')
        assert rv.status_code == 403

    def test_requires_roles_layered4(self) -> None:
        doc = ViewDocument(name='test1', title="Test")
        self.session.add(doc)
        self.session.commit()

        # Finally, we have 'edit' permission but without 'owner' role
        rv = self.client.get('/gated/test1/perm?access_token=editor-secret')
        assert rv.status_code == 200
        assert rv.data == b'perm-called'
        rv = self.client.get('/gated/test1/role?access_token=editor-secret')
        assert rv.status_code == 403
        rv = self.client.get('/gated/test1/perm-role?access_token=editor-secret')
        assert rv.status_code == 403
        rv = self.client.get('/gated/test1/role-perm?access_token=editor-secret')
        assert rv.status_code == 403

    def test_is_available(self) -> None:
        doc = ViewDocument(name='test1', title="Test")
        self.session.add(doc)
        self.session.commit()

        # The default view has no requires_* decorators
        # and so is always available.
        assert doc.view_for().is_available() is True

        # The four gated views are all not available
        assert doc.view_for('by_perm').is_available() is False
        assert doc.view_for('by_role').is_available() is False
        assert doc.view_for('by_perm_role').is_available() is False
        assert doc.view_for('by_role_perm').is_available() is False

    def test_class_is_available(self) -> None:
        doc = ViewDocument(name='test1', title="Test")
        self.session.add(doc)
        self.session.commit()

        # First, confirm we're working with the correct view
        assert isinstance(doc.views.main(), ModelDocumentView)
        assert isinstance(doc.views.gated(), GatedDocumentView)

        # Since ModelDocumentView.view is not gated, ModelDocumentView is always
        # available. This is not the case for GatedDocumentView
        assert doc.views.main().is_always_available is True
        assert doc.views.main().is_available() is True
        assert doc.views.gated().is_always_available is False
        assert doc.views.gated().is_available() is False

        # If we add access permissions, the availability changes
        add_auth_attribute('user', 'this-is-the-owner')  # See ViewDocument.permissions
        assert doc.views.gated().is_available() is True

    def test_classview_equals(self) -> None:
        # ClassView implements __eq__ that is not fooled by subclasses
        assert BaseView() == BaseView()
        assert SubView() == SubView()
        assert BaseView() != SubView()
        assert SubView() != BaseView()

        doc1 = ViewDocument(name='test1', title="Test 1")
        doc2 = ViewDocument(name='test2', title="Test 2")

        # ModelView implements __eq__ that extends ClassView's by also comparing the object
        assert ModelDocumentView(obj=doc1) == ModelDocumentView(obj=doc1)
        assert ModelDocumentView(obj=doc1) != ModelDocumentView(obj=doc2)

        # Note: while ScopedDocumentView handles ScopedViewDocument and not ViewDocument,
        # there is no type check in __init__, so the constructor will pass. We want __eq__
        # to catch a mismatch here. This test will break if ModelView introduces type
        # safety checks, and will need amending then.
        assert ModelDocumentView(obj=doc1) != ScopedDocumentView(obj=doc1)
        assert ScopedDocumentView(obj=doc1) != ModelDocumentView(obj=doc1)

    def test_url_dict_current_roles(self) -> None:
        doc1 = ViewDocument(name='test1', title="Test 1")
        assert set(doc1.urls) == {
            'view',  # From ModelDocumentView
            'edit',  # From ModelDocumentView
            'by_perm',  # From GatedDocumentView (`urls` can't handle permission gating)
        }
        # Adding acess permissions changes the URLs available
        add_auth_attribute('user', 'this-is-the-owner')  # See ViewDocument.permissions
        assert set(doc1.urls) == {
            # From ModelDocumentView
            'view',
            'edit',
            # From GatedDocumentView
            'by_perm',
            'by_role_perm',
            'by_perm_role',
            'by_role',
        }
