"""Test @load_models view helper."""

# pylint: disable=redefined-outer-name,no-value-for-parameter

from __future__ import annotations

from typing import Optional

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Mapped
from werkzeug.exceptions import Forbidden, NotFound

from coaster.compat import g
from coaster.sqlalchemy import BaseMixin, BaseNameMixin, BaseScopedIdMixin, relationship
from coaster.views import Redirect, load_model, load_models

from .auth_test import LoginManager
from .conftest import AppTestCase, Model
from .sqlalchemy_models_test import (
    Container,
    IdNamedDocument,
    NamedDocument,
    ScopedIdDocument,
    ScopedIdNamedDocument,
    ScopedNamedDocument,
    User,
)

# --- Models ---------------------------------------------------------------------------


class MiddleContainer(BaseMixin, Model):
    __tablename__ = 'middle_container'
    children: Mapped[list[ChildDocument]] = relationship(back_populates='parent')


class ParentDocument(BaseNameMixin, Model):
    __tablename__ = 'parent_document'
    middle_id: Mapped[int] = sa.orm.mapped_column(sa.ForeignKey('middle_container.id'))
    middle: Mapped[MiddleContainer] = relationship(MiddleContainer)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.middle = MiddleContainer()

    def permissions(
        self, actor: User, inherited: Optional[set[str]] = None
    ) -> set[str]:
        perms = super().permissions(actor, inherited)
        perms.add('view')
        if actor.username == 'foo':
            perms.add('edit')
            perms.add('delete')
        return perms


class ChildDocument(BaseScopedIdMixin, Model):
    __tablename__ = 'child_document'
    parent_id: Mapped[int] = sa.orm.mapped_column(sa.ForeignKey('middle_container.id'))
    parent: Mapped[MiddleContainer] = relationship(back_populates='children')

    def permissions(
        self, actor: User, inherited: Optional[set[str]] = None
    ) -> set[str]:
        perms = set() if inherited is None else inherited
        if actor.username == 'foo' and 'delete' in perms:
            perms.remove('delete')
        return perms


class RedirectDocument(BaseNameMixin, Model):
    __tablename__ = 'redirect_document'
    container_id: Mapped[int] = sa.orm.mapped_column(sa.ForeignKey('container.id'))
    container: Mapped[Container] = relationship()
    target_id: Mapped[int] = sa.orm.mapped_column(sa.ForeignKey('named_document.id'))
    target: Mapped[NamedDocument] = relationship()

    def redirect_view_args(self) -> dict[str, str]:
        return {'document': self.target.name}


def return_siteadmin_perms() -> set[str]:
    return {'siteadmin'}


# --- load_models decorators -----------------------------------------------------------


@load_model(
    Container,
    {'name': 'container'},
    'container',
    permission='siteadmin',
    kwargs=True,
    addlperms=return_siteadmin_perms,
)
def t_container(
    container: Container,
    kwargs: dict[str, str],
) -> Container:
    return container


@load_model(User, {'username': 'username'}, 'g.user')
def t_load_user_to_g(user: User) -> User:
    return user


@load_models((User, {'username': 'username'}, 'g.user'))
def t_single_model_in_loadmodels(user: User) -> User:
    return user


@load_models(
    (Container, {'name': 'container'}, 'container'),
    (NamedDocument, {'name': 'document', 'container': 'container'}, 'document'),
)
def t_named_document(
    container: Container,
    document: NamedDocument,
) -> NamedDocument:
    return document


@load_models(
    (Container, {'name': 'container'}, 'container'),
    (
        (NamedDocument, RedirectDocument),
        {'name': 'document', 'container': 'container'},
        'document',
    ),
)
def t_redirect_document(
    container: Container,
    document: NamedDocument,
) -> NamedDocument:
    return document


@load_models(
    (Container, {'name': 'container'}, 'container'),
    (ScopedNamedDocument, {'name': 'document', 'container': 'container'}, 'document'),
)
def t_scoped_named_document(
    container: Container,
    document: ScopedNamedDocument,
) -> ScopedNamedDocument:
    return document


@load_models(
    (Container, {'name': 'container'}, 'container'),
    (IdNamedDocument, {'url_name': 'document', 'container': 'container'}, 'document'),
    urlcheck=['url_name'],
)
def t_id_named_document(
    container: Container,
    document: IdNamedDocument,
) -> IdNamedDocument:
    return document


@load_models(
    (Container, {'name': 'container'}, 'container'),
    (
        ScopedIdDocument,
        {'url_id': lambda _r, p: int(p['document']), 'container': 'container'},
        'document',
    ),
)
def t_scoped_id_document(
    container: Container,
    document: ScopedIdDocument,
) -> ScopedIdDocument:
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
def t_scoped_id_named_document(
    container: Container,
    document: ScopedIdNamedDocument,
) -> ScopedIdNamedDocument:
    return document


@load_models(
    (ParentDocument, {'name': 'document'}, 'document'),
    (
        ChildDocument,
        {'id': 'child', 'parent': lambda r, _p: r['document'].middle},
        'child',
    ),
)
def t_callable_document(
    document: ParentDocument,
    child: ChildDocument,
) -> ChildDocument:
    return child


@load_models(
    (ParentDocument, {'name': 'document'}, 'document'),
    (ChildDocument, {'id': 'child', 'parent': 'document.middle'}, 'child'),
)
def t_dotted_document(
    document: ParentDocument,
    child: ChildDocument,
) -> ChildDocument:
    return child


@load_models(
    (ParentDocument, {'name': 'document'}, 'document'),
    (ChildDocument, {'id': 'child', 'parent': 'document.middle'}, 'child'),
    permission='view',
)
def t_dotted_document_view(
    document: ParentDocument,
    child: ChildDocument,
) -> ChildDocument:
    return child


@load_models(
    (ParentDocument, {'name': 'document'}, 'document'),
    (ChildDocument, {'id': 'child', 'parent': 'document.middle'}, 'child'),
    permission='edit',
)
def t_dotted_document_edit(
    document: ParentDocument,
    child: ChildDocument,
) -> ChildDocument:
    return child


@load_models(
    (ParentDocument, {'name': 'document'}, 'document'),
    (ChildDocument, {'id': 'child', 'parent': 'document.middle'}, 'child'),
    permission='delete',
)
def t_dotted_document_delete(
    document: ParentDocument,
    child: ChildDocument,
) -> ChildDocument:
    return child


# --- Tests ----------------------------------------------------------------------------


@pytest.fixture(scope='module', autouse=True)
def _app_extra(app) -> None:
    LoginManager(app)
    app.add_url_rule(
        '/<container>/<document>', 'redirect_document', t_redirect_document
    )


class TestLoadModels(AppTestCase):
    def setUp(self) -> None:
        super().setUp()
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

    @pytest.mark.flaky
    def test_container(self) -> None:
        assert self.app.login_manager is not None  # type: ignore[attr-defined]
        with self.app.test_request_context():
            self.app.login_manager.set_user_for_testing(  # type: ignore[attr-defined]
                User(username='test'), load=True
            )
            assert t_container(container='c') == self.container

    def test_named_document(self) -> None:
        assert t_named_document(container='c', document='named-document') == self.nd1
        assert (
            t_named_document(container='c', document='another-named-document')
            == self.nd2
        )

    @pytest.mark.flaky
    def test_redirect_document(self) -> None:
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
            with pytest.raises(Redirect) as exc_info:
                t_redirect_document(container='c', document='redirect-document')
            assert exc_info.value.code == 307
            assert exc_info.value.location == '/c/named-document'
        with self.app.test_request_context('/c/redirect-document?preserve=this'):
            with pytest.raises(Redirect) as exc_info:
                t_redirect_document(container='c', document='redirect-document')
            assert exc_info.value.code == 307
            assert exc_info.value.location == '/c/named-document?preserve=this'

    def test_scoped_named_document(self) -> None:
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

    @pytest.mark.flaky
    def test_id_named_document(self) -> None:
        assert (
            t_id_named_document(container='c', document='1-id-named-document')
            == self.ind1
        )
        assert (
            t_id_named_document(container='c', document='2-another-id-named-document')
            == self.ind2
        )
        with self.app.test_request_context('/c/1-wrong-name'):
            with pytest.raises(Redirect) as exc_info:
                t_id_named_document(container='c', document='1-wrong-name')
            assert exc_info.value.code == 302
            assert exc_info.value.location == '/c/1-id-named-document'
        with self.app.test_request_context('/c/1-wrong-name?preserve=this'):
            with pytest.raises(Redirect) as exc_info:
                t_id_named_document(container='c', document='1-wrong-name')
            assert exc_info.value.code == 302
            assert exc_info.value.location == '/c/1-id-named-document?preserve=this'
        with pytest.raises(NotFound):
            t_id_named_document(container='c', document='random-non-integer')

    def test_scoped_id_document(self) -> None:
        assert t_scoped_id_document(container='c', document='1') == self.sid1
        assert t_scoped_id_document(container='c', document='2') == self.sid2
        assert t_scoped_id_document(container='c', document=1) == self.sid1
        assert t_scoped_id_document(container='c', document=2) == self.sid2

    @pytest.mark.flaky
    def test_scoped_id_named_document(self) -> None:
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
            with pytest.raises(Redirect) as exc_info:
                t_scoped_id_named_document(container='c', document='1-wrong-name')
            assert exc_info.value.code == 302
            assert exc_info.value.location == '/c/1-scoped-id-named-document'
        with pytest.raises(NotFound):
            t_scoped_id_named_document(container='c', document='random-non-integer')

    def test_callable_document(self) -> None:
        assert t_callable_document(document='parent', child=1) == self.child1
        assert t_callable_document(document='parent', child=2) == self.child2

    def test_dotted_document(self) -> None:
        assert t_dotted_document(document='parent', child=1) == self.child1
        assert t_dotted_document(document='parent', child=2) == self.child2

    def test_direct_permissions(self) -> None:
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

    def test_inherited_permissions(self) -> None:
        user = User(username='admin')
        assert self.pc.permissions(user, inherited={'add-video'}) == {
            'add-video',
            'view',
        }

    def test_unmutated_inherited_permissions(self) -> None:
        """The inherited permission set should not be mutated by a permission check."""
        user = User(username='admin')
        inherited = {'add-video'}
        assert self.pc.permissions(user, inherited=inherited) == {'add-video', 'view'}
        assert inherited == {'add-video'}

    @pytest.mark.flaky
    def test_loadmodel_permissions(self) -> None:
        with self.app.test_request_context():
            self.app.login_manager.set_user_for_testing(  # type: ignore[attr-defined]
                User(username='foo'), load=True
            )
            assert t_dotted_document_view(document='parent', child=1) == self.child1
            assert t_dotted_document_edit(document='parent', child=1) == self.child1
            with pytest.raises(Forbidden):
                t_dotted_document_delete(document='parent', child=1)

    @pytest.mark.flaky
    def test_load_user_to_g(self) -> None:
        with self.app.test_request_context():
            user = User(username='baz')
            self.session.add(user)
            self.session.commit()
            assert not hasattr(g, 'user')
            assert t_load_user_to_g(username='baz') == g.user
            with pytest.raises(NotFound):
                t_load_user_to_g(username='boo')

    @pytest.mark.flaky
    def test_single_model_in_loadmodels(self) -> None:
        with self.app.test_request_context():
            user = User(username='user1')
            self.session.add(user)
            self.session.commit()
            assert t_single_model_in_loadmodels(username='user1') == g.user
