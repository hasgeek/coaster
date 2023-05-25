"""Test ModelBase."""
# pylint: disable=redefined-outer-name

from __future__ import annotations

import typing as t

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DynamicMapped, Mapped, mapped_column
import pytest
import sqlalchemy as sa

from coaster.sqlalchemy import (
    DeclarativeBase,
    ModelBase,
    ModelWarning,
    Query,
    int_pkey,
    relationship,
)


def test_query_is_query() -> None:
    """Model has a query."""

    class Model(ModelBase, DeclarativeBase):
        """Test Model base."""

    class TestModel(Model):
        """Test model."""

        __tablename__ = 'test_model'
        pkey: Mapped[int_pkey]

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///'
    db = SQLAlchemy(app, metadata=Model.metadata)
    Model.init_flask_sqlalchemy(db)

    with app.test_request_context():
        assert hasattr(TestModel, 'query')
        assert isinstance(TestModel.query, Query)


def test_disallow_bind_key_attr() -> None:
    """Bind key must not be specified as __bind_key__ in the class."""

    class Model(ModelBase, DeclarativeBase):
        """Test Model base."""

    assert Model.__bind_key__ is None
    with pytest.raises(TypeError, match="This class has __bind_key__"):

        class _TestModel(Model):
            """Model with __bind_key__."""

            __tablename__ = 'test_model'
            __bind_key__ = 'test'


def test_disallow_bind_key_in_bases_of_subclass() -> None:
    """Bind key must be specified in the bases of only the base class."""

    class Model(ModelBase, DeclarativeBase):
        """Test model base."""

    assert Model.__bind_key__ is None
    with pytest.raises(TypeError, match="base class"):

        class _TestModel(Model, bind_key='test'):
            """Model that is not base with bind_key."""

            __tablename__ = 'test_model'


def test_allow_bind_key_in_bases() -> None:
    """Bind key may be specified in bases of the base class."""

    class Model(ModelBase, DeclarativeBase, bind_key='test'):
        """Test model base."""

    assert Model.__bind_key__ == 'test'


def test_bind_key_metadata_isolation() -> None:
    """Multiple base classes with separate metadatas may exist."""

    class Model(ModelBase, DeclarativeBase):
        """Test model base."""

    class BindModel(ModelBase, DeclarativeBase, bind_key='test'):
        """Test bind model base."""

    assert Model.__bind_key__ is None
    assert BindModel.__bind_key__ == 'test'
    assert Model.metadata != BindModel.metadata

    class TestModel(Model):
        """Test model."""

        __tablename__ = 'test_model'
        pkey: Mapped[int_pkey]

    class BindTestModel(BindModel):
        """Bind test model."""

        __tablename__ = 'bind_test_model'
        pkey: Mapped[int_pkey]

    assert TestModel.metadata is Model.metadata
    assert BindTestModel.metadata is BindModel.metadata
    assert TestModel.metadata != BindTestModel.metadata


def test_init_sqlalchemy() -> None:
    """Init can only be called on the base class."""

    class Model(ModelBase, DeclarativeBase):
        """Test Model base."""

    class TestModel(Model):
        """Test model."""

        __tablename__ = 'test_model'
        pkey: Mapped[int_pkey]

    db = SQLAlchemy(metadata=Model.metadata)

    with pytest.raises(TypeError, match="init_flask_sqlalchemy must be called on"):
        ModelBase.init_flask_sqlalchemy(db)

    with pytest.raises(TypeError, match="init_flask_sqlalchemy must be called on"):
        TestModel.init_flask_sqlalchemy(db)

    # The call on the base model works
    Model.init_flask_sqlalchemy(db)
    assert Model.__fsa__ is db

    with pytest.warns(RuntimeWarning):
        # Second call raises a warning but otherwise works
        Model.init_flask_sqlalchemy(db)
    assert Model.__fsa__ is db


def test_init_sqlalchemy_without_metadata() -> None:
    """Flask-SQLAlchemy must use Model's metadata."""

    class Model(ModelBase, DeclarativeBase):
        """Test Model base."""

    db = SQLAlchemy()
    with pytest.raises(TypeError, match="Flask-SQLAlchemy has its own metadata"):
        Model.init_flask_sqlalchemy(db)


def test_init_sqlalchemy_bind_key_before_init() -> None:
    """Flask-SQLAlchemy db.Model with __bind_key__ must not be before init."""

    class Model(ModelBase, DeclarativeBase):
        """Test model base."""

    class BindModel(ModelBase, DeclarativeBase, bind_key='test'):
        """Test bind model base."""

    db = SQLAlchemy(metadata=Model.metadata)

    class TestBindModel(db.Model):  # type: ignore[name-defined]
        """Bind model with db.Model."""

        __bind_key__ = 'test'
        pkey: Mapped[int_pkey]

    assert TestBindModel.__tablename__ == 'test_bind_model'
    Model.init_flask_sqlalchemy(db)
    with pytest.raises(TypeError, match="Flask-SQLAlchemy has different metadata"):
        BindModel.init_flask_sqlalchemy(db)


def test_init_sqlalchemy_bind_key_after_init() -> None:
    """Flask-SQLAlchemy db.Model with __bind_key__ must be after init."""

    class Model(ModelBase, DeclarativeBase):
        """Test model base."""

    class BindModel(ModelBase, DeclarativeBase, bind_key='test'):
        """Test bind model base."""

    db = SQLAlchemy(metadata=Model.metadata)
    Model.init_flask_sqlalchemy(db)
    BindModel.init_flask_sqlalchemy(db)

    class TestBindModel(db.Model):  # type: ignore[name-defined]
        """Bind model with db.Model."""

        __bind_key__ = 'test'
        pkey: Mapped[int_pkey]

    assert TestBindModel.__tablename__ == 'test_bind_model'
    assert TestBindModel.metadata is BindModel.metadata


def test_relationship_query_class() -> None:
    """Relationships get Coaster's Query."""

    class Model(ModelBase, DeclarativeBase):
        """Test Model base."""

    class TestModel(Model):
        """Test model."""

        __tablename__ = 'test_model'
        pkey: Mapped[int_pkey]
        related: DynamicMapped[t.List[RelatedModel]] = relationship(
            lazy='dynamic', back_populates='test'
        )

    class RelatedModel(Model):
        """Related model."""

        __tablename__ = 'related_model'
        pkey: Mapped[int_pkey]
        test_id: Mapped[int] = mapped_column(sa.ForeignKey('test_model.pkey'))
        test: Mapped[TestModel] = relationship(back_populates='related')

    assert isinstance(TestModel().related, Query)


def test_backref_warning() -> None:
    """Relationships using a backref raise a warning."""

    class Model(ModelBase, DeclarativeBase):
        """Test Model base."""

    class TestModel(Model):
        """Test model."""

        __tablename__ = 'test_model'
        pkey: Mapped[int_pkey]

    class _RelatedModel(Model):
        """Related model."""

        __tablename__ = 'related_model'
        pkey: Mapped[int_pkey]
        test_id: Mapped[int] = mapped_column(sa.ForeignKey('test_model.pkey'))
        with pytest.warns(ModelWarning):
            test: Mapped[TestModel] = relationship(backref='related')
