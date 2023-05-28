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


def test_allow_bind_key_in_base() -> None:
    """Bind key may be specified in the base class."""

    class BindModel(ModelBase, DeclarativeBase):
        """Test model base."""

        __bind_key__ = 'test'

    assert BindModel.__bind_key__ == 'test'


def test_bind_key_must_match_base() -> None:
    """A bind key in subclasses must match the base class."""
    # pylint: disable=unused-variable

    class Model(ModelBase, DeclarativeBase):
        """Test model base."""

    class BindModel(ModelBase, DeclarativeBase):
        """Test bind model base."""

        __bind_key__: t.Optional[str] = 'test'

    class Mixin:
        """Mixin that replaces bind_key."""

        __bind_key__: t.Optional[str] = 'other'

    assert Model.__bind_key__ is None
    with pytest.raises(TypeError, match="__bind_key__.*does not match base class"):

        class ModelWithWrongBaseModel(Model):  # skipcq: PTC-W0065
            """Model with a custom bind key not matching the base's bind key (None)."""

            __bind_key__ = 'wrong_bind'  # Expected to be None
            __tablename__ = 'model_with_wrong_base_model'
            pkey: Mapped[int_pkey]

    with pytest.raises(TypeError, match="__bind_key__.*does not match base class"):

        class BindModelWithWrongBaseModel(BindModel):  # skipcq: PTC-W0065
            """Model with a custom bind key not matching the base's bind key (None)."""

            __bind_key__ = None  # Expected to be 'test'
            __tablename__ = 'bind_model_with_wrong_base_model'
            pkey: Mapped[int_pkey]

    with pytest.raises(TypeError, match="__bind_key__.*does not match base class"):

        class MixinChangedBindKey(Mixin, Model):  # skipcq: PTC-W0065
            """A mixin introduced a mismatched bind key."""

            __tablename__ = 'mixin_changed_bind_key'
            pkey: Mapped[int_pkey]


def test_repeat_bind_key() -> None:
    """Repeating a bind_key in subclasses is okay if it matches the base class."""

    class Model(ModelBase, DeclarativeBase):
        """Test model base."""

    class BindModel(ModelBase, DeclarativeBase):
        """Test bind model base."""

        __bind_key__: t.Optional[str] = 'test'

    assert Model.__bind_key__ is None
    assert BindModel.__bind_key__ == 'test'

    class TestModel(Model):
        """Model that repeats bind_key."""

        __bind_key__ = None
        __tablename__ = 'test_model'
        pkey: Mapped[int_pkey]

    class TestBindModel(BindModel):
        """Model that also repeats bind_key."""

        __bind_key__ = 'test'
        __tablename__ = 'test_bind_model'
        pkey: Mapped[int_pkey]

    assert TestModel.__bind_key__ is None
    assert TestBindModel.__bind_key__ == 'test'


def test_bind_key_metadata_isolation() -> None:
    """Multiple base classes with separate metadatas may exist."""

    class Model(ModelBase, DeclarativeBase):
        """Test model base."""

    class BindModel(ModelBase, DeclarativeBase):
        """Test bind model base."""

        __bind_key__ = 'test'

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


def test_inheritance_pattern_must_keep_bind() -> None:
    """Inheritance pattern models must also keep a consistent bind key."""
    # pylint: disable=unused-variable

    class Model(ModelBase, DeclarativeBase):
        """Test Model base."""

        __bind_key__ = 'base'

    class GenericType(Model):
        """Generic type that has subtypes."""

        __tablename__ = 'generic_type'
        pkey: Mapped[int_pkey]
        type_: Mapped[str] = mapped_column(default='generic')
        __mapper_args__ = {'polymorphic_on': type_, 'with_polymorphic': '*'}

    with pytest.raises(TypeError, match="__bind_key__.*does not match base class"):

        class SpecificType(GenericType):  # skipcq: PTC-W0065
            """Specific subtype of GenericType."""

            __bind_key__ = 'other'  # This is not allowed
            __mapper_args__ = {'polymorphic_identity': 'specific'}


def test_inheritance_pattern_is_okay() -> None:
    """Inheritance pattern models will have a consistent MetaData and bind_key."""

    class Model(ModelBase, DeclarativeBase):
        """Test Model base."""

    class GenericType(Model):
        """Generic type that has subtypes."""

        __tablename__ = 'generic_type'
        pkey: Mapped[int_pkey]
        type_: Mapped[str] = mapped_column(default='generic')
        __mapper_args__ = {'polymorphic_on': type_, 'with_polymorphic': '*'}

    class SpecificType(GenericType):
        """Specific subtype of GenericType."""

        __bind_key__ = None
        __mapper_args__ = {'polymorphic_identity': 'specific'}

    assert SpecificType.metadata is GenericType.metadata
    assert SpecificType.metadata is Model.metadata
    assert SpecificType.__bind_key__ == Model.__bind_key__


def test_init_sqlalchemy() -> None:
    """Init can only be called on the base class."""

    class Model(ModelBase, DeclarativeBase):
        """Test Model base."""

    class TestModel(Model):
        """Test model."""

        __tablename__ = 'test_model'
        pkey: Mapped[int_pkey]

    class TestBindKeyModel(Model):
        """Test model that has a custom (matching) bind_key attr."""

        __bind_key__ = None
        __tablename__ = 'test_bind_key_model'
        pkey: Mapped[int_pkey]

    db = SQLAlchemy(metadata=Model.metadata)

    with pytest.raises(TypeError, match="init_flask_sqlalchemy must be called on"):
        ModelBase.init_flask_sqlalchemy(db)
    with pytest.raises(TypeError, match="init_flask_sqlalchemy must be called on"):
        TestModel.init_flask_sqlalchemy(db)
    with pytest.raises(TypeError, match="init_flask_sqlalchemy must be called on"):
        TestBindKeyModel.init_flask_sqlalchemy(db)

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
    """Model using db.Model with __bind_key__ must not be before init."""

    class Model(ModelBase, DeclarativeBase):
        """Test model base."""

    class BindModel(ModelBase, DeclarativeBase):
        """Test bind model base."""

        __bind_key__ = 'test'

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
    """Model using db.Model with __bind_key__ must be after init."""

    class Model(ModelBase, DeclarativeBase):
        """Test model base."""

    class BindModel(ModelBase, DeclarativeBase):
        """Test bind model base."""

        __bind_key__ = 'test'

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

    class RelatedModel(Model):  # skipcq: PTC-W0065
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

    class _RelatedModel(Model):  # skipcq: PTC-W0065
        """Related model."""

        __tablename__ = 'related_model'
        pkey: Mapped[int_pkey]
        test_id: Mapped[int] = mapped_column(sa.ForeignKey('test_model.pkey'))
        with pytest.warns(ModelWarning):
            test: Mapped[TestModel] = relationship(backref='related')
