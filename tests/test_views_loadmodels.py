import unittest

from sqlalchemy import Column, ForeignKey
from sqlalchemy.orm import relationship

from flask import Flask, g
from werkzeug.exceptions import Forbidden, NotFound

import pytest

from coaster.db import db
from coaster.sqlalchemy import BaseMixin, BaseNameMixin, BaseScopedIdMixin
from coaster.views import load_model, load_models

from .test_sqlalchemy_models import (
    Container,
    IdNamedDocument,
    NamedDocument,
    ScopedIdDocument,
    ScopedIdNamedDocument,
    ScopedNamedDocument,
    User,
    app1,
    app2,
    login_manager,
)

# --- Models ------------------------------------------------------------------


class MiddleContainer(BaseMixin, db.Model):
    __tablename__ = 'middle_container'


class ParentDocument(BaseNameMixin, db.Model):
    __tablename__ = 'parent_document'
    middle_id = Column(  # type: ignore[call-overload]
        None, ForeignKey('middle_container.id')
    )
    middle = relationship(MiddleContainer, uselist=False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.middle = MiddleContainer()

    def permissions(self, actor, inherited=None):
        perms = super().permissions(actor, inherited)
        perms.add('view')
        if actor.username == 'foo':
            perms.add('edit')
            perms.add('delete')
        return perms


class ChildDocument(BaseScopedIdMixin, db.Model):
    __tablename__ = 'child_document'
    parent_id = Column(  # type: ignore[call-overload]
        None, ForeignKey('middle_container.id')
    )
    parent = relationship(MiddleContainer, backref='children')

    def permissions(self, actor, inherited=None):
        if inherited is None:
            perms = set()
        else:
            perms = inherited
        if actor.username == 'foo' and 'delete' in perms:
            perms.remove('delete')
        return perms


class RedirectDocument(BaseNameMixin, db.Model):
    __tablename__ = 'redirect_document'
    container_id = Column(  # type: ignore[call-overload]
        None, ForeignKey('container.id')
    )
    container = relationship(Container)

    target_id = Column(  # type: ignore[call-overload]
        None, ForeignKey('named_document.id')
    )
    target = relationship(NamedDocument)

    def redirect_view_args(self):
        return {'document': self.target.name}


def return_siteadmin_perms():
    return {'siteadmin'}


# --- load_models decorators --------------------------------------------------


@load_model(
    Container,
    {'name': 'container'},
    'container',
    permission='siteadmin',
    kwargs=True,
    addlperms=return_siteadmin_perms,
)
def t_container(container, kwargs):
    return container


@load_model(User, {'username': 'username'}, 'g.user')
def t_load_user_to_g(user):
    return user


@load_models((User, {'username': 'username'}, 'g.user'))
def t_single_model_in_loadmodels(user):
    return user


@load_models(
    (Container, {'name': 'container'}, 'container'),
    (NamedDocument, {'name': 'document', 'container': 'container'}, 'document'),
)
def t_named_document(container, document):
    return document


@load_models(
    (Container, {'name': 'container'}, 'container'),
    (
        (NamedDocument, RedirectDocument),
        {'name': 'document', 'container': 'container'},
        'document',
    ),
)
def t_redirect_document(container, document):
    return document


@load_models(
    (Container, {'name': 'container'}, 'container'),
    (ScopedNamedDocument, {'name': 'document', 'container': 'container'}, 'document'),
)
def t_scoped_named_document(container, document):
    return document


@load_models(
    (Container, {'name': 'container'}, 'container'),
    (IdNamedDocument, {'url_name': 'document', 'container': 'container'}, 'document'),
    urlcheck=['url_name'],
)
def t_id_named_document(container, document):
    return document


@load_models(
    (Container, {'name': 'container'}, 'container'),
    (ScopedIdDocument, {'id': 'document', 'container': 'container'}, 'document'),
)
def t_scoped_id_document(container, document):
    return document


@load_models(
    (Container, {'name': 'container'}, 'container'),
    (
        ScopedIdNamedDocument,
        {'url_name': 'document', 'container': 'container'},
        'document',
    ),
    urlcheck=['url_name'],
)
def t_scoped_id_named_document(container, document):
    return document


@load_models(
    (ParentDocument, {'name': 'document'}, 'document'),
    (
        ChildDocument,
        {'id': 'child', 'parent': lambda r, p: r['document'].middle},
        'child',
    ),
)
def t_callable_document(document, child):
    return child


@load_models(
    (ParentDocument, {'name': 'document'}, 'document'),
    (ChildDocument, {'id': 'child', 'parent': 'document.middle'}, 'child'),
)
def t_dotted_document(document, child):
    return child


@load_models(
    (ParentDocument, {'name': 'document'}, 'document'),
    (ChildDocument, {'id': 'child', 'parent': 'document.middle'}, 'child'),
    permission='view',
)
def t_dotted_document_view(document, child):
    return child


@load_models(
    (ParentDocument, {'name': 'document'}, 'document'),
    (ChildDocument, {'id': 'child', 'parent': 'document.middle'}, 'child'),
    permission='edit',
)
def t_dotted_document_edit(document, child):
    return child


@load_models(
    (ParentDocument, {'name': 'document'}, 'document'),
    (ChildDocument, {'id': 'child', 'parent': 'document.middle'}, 'child'),
    permission='delete',
)
def t_dotted_document_delete(document, child):
    return child


# --- Tests -------------------------------------------------------------------


class TestLoadModels(unittest.TestCase):
    app = app1

    def setUp(self):
        self.ctx = self.app.test_request_context()
        self.ctx.push()

        db.create_all()
        self.session = db.session
        c = Container(name='c')
        self.session.add(c)
        self.container = c
        self.nd1 = NamedDocument(container=c, title="Named Document")
        self.session.add(self.nd1)
        self.session.commit()
        self.nd2 = NamedDocument(container=c, title="Another Named Document")
        self.session.add(self.nd2)
        self.session.commit()
        self.rd1 = RedirectDocument(
            container=c, title="Redirect Document", target=self.nd1
        )
        self.session.add(self.rd1)
        self.session.commit()
        self.snd1 = ScopedNamedDocument(container=c, title="Scoped Named Document")
        self.session.add(self.snd1)
        self.session.commit()
        self.snd2 = ScopedNamedDocument(
            container=c, title="Another Scoped Named Document"
        )
        self.session.add(self.snd2)
        self.session.commit()
        self.ind1 = IdNamedDocument(container=c, title="Id Named Document")
        self.session.add(self.ind1)
        self.session.commit()
        self.ind2 = IdNamedDocument(container=c, title="Another Id Named Document")
        self.session.add(self.ind2)
        self.session.commit()
        self.sid1 = ScopedIdDocument(container=c)
        self.session.add(self.sid1)
        self.session.commit()
        self.sid2 = ScopedIdDocument(container=c)
        self.session.add(self.sid2)
        self.session.commit()
        self.sind1 = ScopedIdNamedDocument(
            container=c, title="Scoped Id Named Document"
        )
        self.session.add(self.sind1)
        self.session.commit()
        self.sind2 = ScopedIdNamedDocument(
            container=c, title="Another Scoped Id Named Document"
        )
        self.session.add(self.sind2)
        self.session.commit()
        self.pc = ParentDocument(title="Parent")
        self.session.add(self.pc)
        self.session.commit()
        self.child1 = ChildDocument(parent=self.pc.middle)
        self.session.add(self.child1)
        self.session.commit()
        self.child2 = ChildDocument(parent=self.pc.middle)
        self.session.add(self.child2)
        self.session.commit()
        self.app = Flask(__name__)
        self.app.add_url_rule(
            '/<container>/<document>', 'redirect_document', t_redirect_document
        )

    def tearDown(self):
        self.session.rollback()
        db.drop_all()
        self.ctx.pop()

    def test_container(self):
        with self.app.test_request_context():
            login_manager.set_user_for_testing(User(username='test'), load=True)
            assert t_container(container='c') == self.container

    def test_named_document(self):
        assert t_named_document(container='c', document='named-document') == self.nd1
        assert (
            t_named_document(container='c', document='another-named-document')
            == self.nd2
        )

    def test_redirect_document(self):
        with self.app.test_request_context('/c/named-document'):
            assert (
                t_redirect_document(container='c', document='named-document')
                == self.nd1
            )
        with self.app.test_request_context('/c/another-named-document'):
            assert (
                t_redirect_document(container='c', document='another-named-document')
                == self.nd2
            )
        with self.app.test_request_context('/c/redirect-document'):
            response = t_redirect_document(container='c', document='redirect-document')
            assert response.status_code == 307
            assert response.headers['Location'] == '/c/named-document'
        with self.app.test_request_context('/c/redirect-document?preserve=this'):
            response = t_redirect_document(container='c', document='redirect-document')
            assert response.status_code == 307
            assert response.headers['Location'] == '/c/named-document?preserve=this'

    def test_scoped_named_document(self):
        assert (
            t_scoped_named_document(container='c', document='scoped-named-document')
            == self.snd1
        )
        assert (
            t_scoped_named_document(
                container='c', document='another-scoped-named-document'
            )
            == self.snd2
        )

    def test_id_named_document(self):
        assert (
            t_id_named_document(container='c', document='1-id-named-document')
            == self.ind1
        )
        assert (
            t_id_named_document(container='c', document='2-another-id-named-document')
            == self.ind2
        )
        with self.app.test_request_context('/c/1-wrong-name'):
            r = t_id_named_document(container='c', document='1-wrong-name')
            assert r.status_code == 302
            assert r.location == '/c/1-id-named-document'
        with self.app.test_request_context('/c/1-wrong-name?preserve=this'):
            r = t_id_named_document(container='c', document='1-wrong-name')
            assert r.status_code == 302
            assert r.location == '/c/1-id-named-document?preserve=this'
        with pytest.raises(NotFound):
            t_id_named_document(container='c', document='random-non-integer')

    def test_scoped_id_document(self):
        assert t_scoped_id_document(container='c', document='1') == self.sid1
        assert t_scoped_id_document(container='c', document='2') == self.sid2
        assert t_scoped_id_document(container='c', document=1) == self.sid1
        assert t_scoped_id_document(container='c', document=2) == self.sid2

    def test_scoped_id_named_document(self):
        assert (
            t_scoped_id_named_document(
                container='c', document='1-scoped-id-named-document'
            )
            == self.sind1
        )
        assert (
            t_scoped_id_named_document(
                container='c', document='2-another-scoped-id-named-document'
            )
            == self.sind2
        )
        with self.app.test_request_context('/c/1-wrong-name'):
            r = t_scoped_id_named_document(container='c', document='1-wrong-name')
            assert r.status_code == 302
            assert r.location == '/c/1-scoped-id-named-document'
        with pytest.raises(NotFound):
            t_scoped_id_named_document(container='c', document='random-non-integer')

    def test_callable_document(self):
        assert t_callable_document(document='parent', child=1) == self.child1
        assert t_callable_document(document='parent', child=2) == self.child2

    def test_dotted_document(self):
        assert t_dotted_document(document='parent', child=1) == self.child1
        assert t_dotted_document(document='parent', child=2) == self.child2

    def test_direct_permissions(self):
        user1 = User(username='foo')
        user2 = User(username='bar')
        assert self.pc.permissions(user1) == {'view', 'edit', 'delete'}
        assert self.pc.permissions(user2) == {'view'}
        assert self.child1.permissions(user1, inherited=self.pc.permissions(user1)) == {
            'view',
            'edit',
        }
        assert self.child1.permissions(user2, inherited=self.pc.permissions(user2)) == {
            'view'
        }

    def test_inherited_permissions(self):
        user = User(username='admin')
        assert self.pc.permissions(user, inherited={'add-video'}) == {
            'add-video',
            'view',
        }

    def test_unmutated_inherited_permissions(self):
        """The inherited permission set should not be mutated by a permission check"""
        user = User(username='admin')
        inherited = {'add-video'}
        assert self.pc.permissions(user, inherited=inherited) == {'add-video', 'view'}
        assert inherited == {'add-video'}

    def test_loadmodel_permissions(self):
        with self.app.test_request_context():
            login_manager.set_user_for_testing(User(username='foo'), load=True)
            assert t_dotted_document_view(document='parent', child=1) == self.child1
            assert t_dotted_document_edit(document='parent', child=1) == self.child1
            with pytest.raises(Forbidden):
                t_dotted_document_delete(document='parent', child=1)

    def test_load_user_to_g(self):
        with self.app.test_request_context():
            user = User(username='baz')
            self.session.add(user)
            self.session.commit()
            assert not hasattr(g, 'user')
            assert t_load_user_to_g(username='baz') == g.user
            with pytest.raises(NotFound):
                t_load_user_to_g(username='boo')

    def test_single_model_in_loadmodels(self):
        with self.app.test_request_context():
            user = User(username='user1')
            self.session.add(user)
            self.session.commit()
            assert t_single_model_in_loadmodels(username='user1') == g.user


class TestLoadModels2(TestLoadModels):
    app = app2
