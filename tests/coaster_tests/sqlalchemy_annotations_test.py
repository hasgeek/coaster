import typing as t
import warnings

from sqlalchemy.orm import Mapped, configure_mappers
from sqlalchemy.orm.attributes import NO_VALUE
import pytest
import sqlalchemy as sa
import sqlalchemy.exc

from coaster.sqlalchemy import (
    BaseMixin,
    ImmutableColumnError,
    UuidMixin,
    cached,
    immutable,
    relationship,
)

from .conftest import AppTestCase, Model

# --- Models ---------------------------------------------------------------------------


class ReferralTarget(BaseMixin, Model):
    __tablename__ = 'referral_target'


class IdOnly(BaseMixin, Model):
    __tablename__ = 'id_only'
    __uuid_primary_key__ = False

    is_regular: Mapped[t.Optional[int]] = sa.orm.mapped_column(sa.Integer)
    is_immutable: Mapped[t.Optional[int]] = immutable(sa.orm.mapped_column(sa.Integer))
    is_cached: Mapped[t.Optional[int]] = cached(sa.orm.mapped_column(sa.Integer))

    # Make the raw column immutable, but allow changes via the relationship
    referral_target_id: Mapped[t.Optional[int]] = immutable(
        sa.orm.mapped_column(sa.ForeignKey('referral_target.id'), nullable=True)
    )
    referral_target: Mapped[t.Optional[ReferralTarget]] = relationship(ReferralTarget)


class IdUuid(UuidMixin, BaseMixin, Model):
    __tablename__ = 'id_uuid'
    __uuid_primary_key__ = False

    is_regular: Mapped[t.Optional[str]] = sa.orm.mapped_column(sa.Unicode(250))
    is_immutable: Mapped[t.Optional[str]] = immutable(
        sa.orm.mapped_column(sa.Unicode(250))
    )
    is_cached: Mapped[t.Optional[str]] = cached(sa.orm.mapped_column(sa.Unicode(250)))

    # Only block changes via the relationship; raw column remains mutable
    referral_target_id: Mapped[t.Optional[int]] = sa.orm.mapped_column(
        sa.ForeignKey('referral_target.id'), nullable=True
    )
    referral_target: Mapped[t.Optional[ReferralTarget]] = immutable(
        relationship(ReferralTarget)
    )


class UuidOnly(UuidMixin, BaseMixin, Model):
    __tablename__ = 'uuid_only'
    __uuid_primary_key__ = True

    is_regular: Mapped[t.Optional[str]] = sa.orm.mapped_column(sa.Unicode(250))
    is_immutable: Mapped[t.Optional[str]] = immutable(
        sa.orm.mapped_column(sa.Unicode(250), deferred=True)
    )
    is_cached: Mapped[t.Optional[str]] = cached(sa.orm.mapped_column(sa.Unicode(250)))

    # Make both raw column and relationship immutable
    referral_target_id: Mapped[t.Optional[int]] = immutable(
        sa.orm.mapped_column(sa.ForeignKey('referral_target.id'), nullable=True)
    )
    referral_target: Mapped[t.Optional[ReferralTarget]] = immutable(
        relationship(ReferralTarget)
    )


class PolymorphicParent(BaseMixin, Model):
    __tablename__ = 'polymorphic_parent'
    ptype = immutable(sa.orm.mapped_column('type', sa.Unicode(30), index=True))
    is_immutable = immutable(
        sa.orm.mapped_column(sa.Unicode(250), default='my_default')
    )
    also_immutable = immutable(sa.orm.mapped_column(sa.Unicode(250)))

    __mapper_args__ = {'polymorphic_on': ptype, 'polymorphic_identity': 'parent'}


# Disable SQLAlchemy warning for the second `also_immutable` below
warnings.simplefilter('ignore', category=sqlalchemy.exc.SAWarning)


class PolymorphicChild(PolymorphicParent):
    __tablename__ = 'polymorphic_child'
    id = sa.orm.mapped_column(  # type: ignore[assignment]  # noqa: A003
        None,
        sa.ForeignKey('polymorphic_parent.id', ondelete='CASCADE'),
        primary_key=True,
        nullable=False,
    )
    # Redefining a column will keep existing annotations, even if not specified here
    also_immutable = sa.orm.mapped_column(sa.Unicode(250))

    __mapper_args__ = {'polymorphic_identity': 'child'}


warnings.resetwarnings()


class SynonymAnnotation(BaseMixin, Model):
    __tablename__ = 'synonym_annotation'
    col_regular = sa.orm.mapped_column(sa.Unicode())
    col_immutable = immutable(sa.orm.mapped_column(sa.Unicode()))

    # Synonyms cannot have annotations. They mirror the underlying attribute
    syn_to_immutable = sa.orm.synonym('col_immutable')


configure_mappers()

# --- Tests ----------------------------------------------------------------------------


def test_has_annotations() -> None:
    """Annotations on the models were processed."""
    for model in (IdOnly, IdUuid, UuidOnly):
        assert hasattr(model, '__column_annotations__')
        assert hasattr(model, '__column_annotations_by_attr__')


def test_annotation_in_annotations() -> None:
    """Annotations were discovered."""
    for model in (IdOnly, IdUuid, UuidOnly):
        for annotation in (immutable, cached):
            assert annotation.__name__ in model.__column_annotations__


def test_attr_in_annotations() -> None:
    """Annotated attributes were discovered and documented."""
    for model in (IdOnly, IdUuid, UuidOnly):
        assert 'is_immutable' in model.__column_annotations__['immutable']
        assert 'is_cached' in model.__column_annotations__['cached']


def test_base_attrs_in_annotations() -> None:
    """Annotations in the base class were also discovered and added to subclass."""
    for model in (IdOnly, IdUuid, UuidOnly):
        for attr in ('created_at', 'id'):
            assert attr in model.__column_annotations__['immutable']
    assert 'uuid' in IdUuid.__column_annotations__['immutable']


class TestCoasterAnnotations(AppTestCase):
    """Tests for annotations."""

    def test_init_immutability(self) -> None:
        i1 = IdOnly(is_regular=1, is_immutable=2, is_cached=3)
        i2 = IdUuid(is_regular='a', is_immutable='b', is_cached='c')
        i3 = UuidOnly(is_regular='x', is_immutable='y', is_cached='z')

        # Regular columns work as usual
        assert i1.is_regular == 1
        assert i2.is_regular == 'a'
        assert i3.is_regular == 'x'
        # Immutable columns gets an initial value
        assert i1.is_immutable == 2
        assert i2.is_immutable == 'b'
        assert i3.is_immutable == 'y'
        # No special behaviour for cached columns, despite the annotation
        assert i1.is_cached == 3
        assert i2.is_cached == 'c'
        assert i3.is_cached == 'z'

        # Regular columns are mutable
        i1.is_regular = 10
        i2.is_regular = 'aa'
        i3.is_regular = 'xx'
        assert i1.is_regular == 10
        assert i2.is_regular == 'aa'
        assert i3.is_regular == 'xx'

        # Immutable columns won't complain if they're updated with the same value
        i1.is_immutable = 2
        i2.is_immutable = 'b'
        i3.is_immutable = 'y'

        # Immutable columns are immutable if the value changes
        with pytest.raises(ImmutableColumnError):
            i1.is_immutable = 20
        with pytest.raises(ImmutableColumnError):
            i2.is_immutable = 'bb'
        with pytest.raises(ImmutableColumnError):
            i3.is_immutable = 'yy'

        # No special behaviour for cached columns, despite the annotation
        i1.is_cached = 30
        i2.is_cached = 'cc'
        i3.is_cached = 'zz'
        assert i1.is_cached == 30
        assert i2.is_cached == 'cc'
        assert i3.is_cached == 'zz'

    def test_postinit_immutability(self) -> None:
        # Make instances with no initial value
        i1 = IdOnly()
        i2 = IdUuid()
        i3 = UuidOnly()

        # Regular columns can be set
        i1.is_regular = 1
        i2.is_regular = 'a'
        i3.is_regular = 'x'

        # Immutable columns can be set the first time
        i1.is_immutable = 2
        i2.is_immutable = 'b'
        i3.is_immutable = 'y'

        # Cached columns behave like regular columns
        i1.is_cached = 3
        i2.is_cached = 'c'
        i3.is_cached = 'z'

        # Regular columns work as usual
        assert i1.is_regular == 1
        assert i2.is_regular == 'a'
        assert i3.is_regular == 'x'
        # Immutable columns accept the initial value
        assert i1.is_immutable == 2
        assert i2.is_immutable == 'b'
        assert i3.is_immutable == 'y'
        # No special behaviour for cached columns, despite the annotation
        assert i1.is_cached == 3
        assert i2.is_cached == 'c'
        assert i3.is_cached == 'z'

        # Regular columns are mutable
        i1.is_regular = 10
        i2.is_regular = 'aa'
        i3.is_regular = 'xx'
        assert i1.is_regular == 10
        assert i2.is_regular == 'aa'
        assert i3.is_regular == 'xx'

        # Immutable columns are immutable
        with pytest.raises(ImmutableColumnError):
            i1.is_immutable = 20
        with pytest.raises(ImmutableColumnError):
            i2.is_immutable = 'bb'
        with pytest.raises(ImmutableColumnError):
            i3.is_immutable = 'yy'

        # No special behaviour for cached columns, despite the annotation
        i1.is_cached = 30
        i2.is_cached = 'cc'
        i3.is_cached = 'zz'
        assert i1.is_cached == 30
        assert i2.is_cached == 'cc'
        assert i3.is_cached == 'zz'

    def test_postload_immutability(self) -> None:
        i1 = IdOnly(is_regular=1, is_immutable=2, is_cached=3)
        i2 = IdUuid(is_regular='a', is_immutable='b', is_cached='c')
        i3 = UuidOnly(is_regular='x', is_immutable='y', is_cached='z')
        self.session.add_all([i1, i2, i3])
        self.session.commit()

        id1 = i1.id
        id2 = i2.id
        id3 = i3.id

        # Delete objects so SQLAlchemy's session cache can't populate fields from them
        del i1, i2, i3

        # Using `query.get` appears to ignore the `load_only` option,
        # so we use `query.filter_by`
        pi1 = IdOnly.query.options(sa.orm.load_only(IdOnly.id)).filter_by(id=id1).one()
        pi2 = IdUuid.query.options(sa.orm.load_only(IdUuid.id)).filter_by(id=id2).one()
        pi3 = (
            UuidOnly.query.options(sa.orm.load_only(UuidOnly.id))
            .filter_by(id=id3)
            .one()
        )

        # Confirm there is no value for is_immutable
        assert (
            sa.inspect(pi1).attrs.is_immutable.loaded_value  # type: ignore[union-attr]
            is NO_VALUE
        )
        assert (
            sa.inspect(pi2).attrs.is_immutable.loaded_value  # type: ignore[union-attr]
            is NO_VALUE
        )
        assert (
            sa.inspect(pi3).attrs.is_immutable.loaded_value  # type: ignore[union-attr]
            is NO_VALUE
        )

        # Immutable columns are immutable even if not loaded
        with pytest.raises(ImmutableColumnError):
            pi1.is_immutable = 20
        with pytest.raises(ImmutableColumnError):
            pi2.is_immutable = 'bb'
        with pytest.raises(ImmutableColumnError):
            pi3.is_immutable = 'yy'

    def test_immutable_foreignkey(self) -> None:
        rt1 = ReferralTarget()
        rt2 = ReferralTarget()
        self.session.add_all([rt1, rt2])
        self.session.commit()  # This gets us rt1.id and rt2.id

        i1 = IdOnly(is_regular=1, is_immutable=2, is_cached=3)
        i2 = IdUuid(is_regular='a', is_immutable='b', is_cached='c')
        i3 = UuidOnly(is_regular='x', is_immutable='y', is_cached='z')

        i1.referral_target_id = rt1.id  # type: ignore[assignment]
        i2.referral_target_id = rt1.id  # type: ignore[assignment]
        i3.referral_target_id = rt1.id  # type: ignore[assignment]

        self.session.add_all([i1, i2, i3])
        self.session.commit()

        # Now try changing the value. i1 and i3 should block, i2 should allow
        with pytest.raises(ImmutableColumnError):
            i1.referral_target_id = rt2.id  # type: ignore[assignment]
        i2.referral_target_id = rt2.id  # type: ignore[assignment]
        with pytest.raises(ImmutableColumnError):
            i3.referral_target_id = rt2.id  # type: ignore[assignment]

    def test_immutable_relationship(self) -> None:
        rt1 = ReferralTarget()
        rt2 = ReferralTarget()
        self.session.add_all([rt1, rt2])
        self.session.commit()  # This gets us rt1.id and rt2.id

        i1 = IdOnly(is_regular=1, is_immutable=2, is_cached=3)
        i2 = IdUuid(is_regular='a', is_immutable='b', is_cached='c')
        i3 = UuidOnly(is_regular='x', is_immutable='y', is_cached='z')

        i1.referral_target_id = rt1.id  # type: ignore[assignment]
        i2.referral_target_id = rt1.id  # type: ignore[assignment]
        i3.referral_target_id = rt1.id  # type: ignore[assignment]

        self.session.add_all([i1, i2, i3])
        # If we don't commit and flush session cache, i2.referral_target
        # will be in NEVER_SET state and hence mutable
        self.session.commit()

        # Now try changing the value. i1 will not block because the
        # immutable validator only listens for direct changes, not
        # via relationships
        i1.referral_target = rt2
        with pytest.raises(ImmutableColumnError):
            i2.referral_target = rt2
        self.session.rollback()
        with pytest.raises(ImmutableColumnError):
            i3.referral_target = rt2

    def test_polymorphic_annotations(self) -> None:
        assert 'is_immutable' in PolymorphicParent.__column_annotations__['immutable']
        assert 'also_immutable' in PolymorphicParent.__column_annotations__['immutable']
        assert 'is_immutable' in PolymorphicChild.__column_annotations__['immutable']
        assert 'also_immutable' in PolymorphicChild.__column_annotations__['immutable']

    def test_polymorphic_immutable(self) -> None:
        parent = PolymorphicParent(is_immutable='a', also_immutable='b')
        child = PolymorphicChild(is_immutable='x', also_immutable='y')
        with pytest.raises(ImmutableColumnError):
            parent.is_immutable = 'aa'
        with pytest.raises(ImmutableColumnError):
            parent.also_immutable = 'bb'
        with pytest.raises(ImmutableColumnError):
            child.is_immutable = 'xx'
        with pytest.raises(ImmutableColumnError):
            child.also_immutable = 'yy'

    def test_synonym_annotation(self) -> None:
        """The immutable annotation can be bypassed via synonyms"""
        syna = SynonymAnnotation(col_regular='a', col_immutable='b')
        # The columns behave as expected:
        assert syna.col_regular == 'a'
        assert syna.col_immutable == 'b'
        syna.col_regular = 'x'
        assert syna.col_regular == 'x'
        with pytest.raises(ImmutableColumnError):
            syna.col_immutable = 'y'
        assert syna.col_immutable == 'b'
        with pytest.raises(ImmutableColumnError):
            syna.syn_to_immutable = 'y'
        assert syna.syn_to_immutable == 'b'
        assert syna.col_immutable == 'b'
