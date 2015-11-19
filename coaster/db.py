# -*- coding: utf-8 -*-

from __future__ import absolute_import
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound
from flask.ext.sqlalchemy import SQLAlchemy as SQLAlchemyBase, SignallingSession

__all__ = ['SQLAlchemy', 'db']


class CoasterSession(SignallingSession):
    """
    Custom session that provides additional helper methods.
    """

    def add_and_commit(self, _instance, **filters):
        """
        Add and commit a new instance, rolling back if the commit fails with an IntegrityError.

        :param _instance: Instance to commit
        :param filters: Filters required to load existing instance from the database
            in case the commit fails (optional).
        :return: Instance that is in the database (in case the commit failed, returned only if filters are specified)
        """
        self.begin_nested()
        try:
            self.add(_instance)
            self.commit()
            return _instance
        except IntegrityError as e:
            self.rollback()
            try:
                return self.query(_instance.__class__).filter_by(**filters).one()
            except NoResultFound:  # Do not trap the other exception, MultipleResultsFound
                raise e


# Provide a Flask-SQLAlchemy alternative that uses our custom session
class SQLAlchemy(SQLAlchemyBase):
    def create_session(self, options):
        """
        Creates the session using :class:`CoasterSession`.
        """
        return CoasterSession(self, **options)

db = SQLAlchemy()
