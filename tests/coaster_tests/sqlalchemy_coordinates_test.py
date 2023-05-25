"""Test CoordinatesMixin class."""

import sqlalchemy as sa

from coaster.sqlalchemy import BaseMixin, CoordinatesMixin

from .conftest import AppTestCase, db


class CoordinatesData(
    BaseMixin, CoordinatesMixin, db.Model  # type: ignore[name-defined]
):
    """Test model for coordinates data."""

    __tablename__ = 'coordinates_data'


# -- Tests --------------------------------------------------------------------


class TestCoordinatesColumn(AppTestCase):
    """Test for coordinates column."""

    def test_columns_created(self) -> None:
        table = CoordinatesData.__table__
        assert isinstance(table.c.latitude.type, sa.Numeric)
        assert isinstance(table.c.longitude.type, sa.Numeric)

    def test_columns_when_null(self) -> None:
        data = CoordinatesData()
        assert data.coordinates == (None, None)
        assert data.has_coordinates is False

    def test_columns_when_missing(self) -> None:
        data = CoordinatesData()
        assert data.has_coordinates is False
        assert data.has_missing_coordinates is True
        data.coordinates = (12, None)
        assert data.has_coordinates is False
        assert data.has_missing_coordinates is True
        data.coordinates = (None, 73)
        assert data.has_coordinates is False
        assert data.has_missing_coordinates is True
        data.coordinates = (12, 73)
        assert data.has_coordinates is True
        assert data.has_missing_coordinates is False  # type: ignore[unreachable]

    def test_column_set_value(self) -> None:
        data = CoordinatesData()
        data.coordinates = (12, 73)
        assert data.coordinates == (12, 73)
        assert data.has_coordinates is True
        db.session.add(data)
        db.session.commit()

        readdata = CoordinatesData.query.first()
        assert readdata is not None
        assert readdata.coordinates == (12, 73)
