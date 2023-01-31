"""Test CoordinatesMixin class."""

import typing as t  # noqa: F401  # pylint: disable=unused-import
import unittest
import uuid as uuid_  # noqa: F401  # pylint: disable=unused-import

import sqlalchemy as sa  # noqa: F401  # pylint: disable=unused-import

from coaster.sqlalchemy import BaseMixin, CoordinatesMixin

from .test_sqlalchemy_models import app2, db


class CoordinatesData(BaseMixin, CoordinatesMixin, db.Model):  # type: ignore[name-defined]
    __tablename__ = 'coordinates_data'


# -- Tests --------------------------------------------------------------------


class TestCoordinatesColumn(unittest.TestCase):
    # Restrict tests to PostgreSQL as SQLite3 doesn't have a Decimal type
    app = app2

    def setUp(self):
        self.ctx = self.app.test_request_context()
        self.ctx.push()
        db.create_all()
        self.session = db.session

    def tearDown(self):
        self.session.rollback()
        db.drop_all()
        self.ctx.pop()

    def test_columns_created(self):
        table = CoordinatesData.__table__
        assert isinstance(table.c.latitude.type, db.Numeric)
        assert isinstance(table.c.longitude.type, db.Numeric)

    def test_columns_when_null(self):
        data = CoordinatesData()
        assert data.coordinates == (None, None)
        assert data.has_coordinates is False

    def test_columns_when_missing(self):
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
        assert data.has_missing_coordinates is False

    def test_column_set_value(self):
        data = CoordinatesData()
        data.coordinates = (12, 73)
        assert data.coordinates == (12, 73)
        assert data.has_coordinates is True
        db.session.add(data)
        db.session.commit()

        readdata = CoordinatesData.query.first()
        assert readdata.coordinates == (12, 73)
