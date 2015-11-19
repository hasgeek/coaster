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
        Add and commit a new instance, gracefully handling failure in case a conflicting entry
        is already in the database (which may occur due to parallel requests causing race
        conditions in a production environment with multiple workers).

        Returns the instance saved to database if no error occured, or loaded from database
        using the provided filters if an error occured. If the filters fail to load from
        the database, the original IntegrityError is re-raised, as it is assumed to imply
        that the commit failed because of missing or invalid data, not because of a duplicate
        entry.

        Usage: ``db.session().add_and_commit(instance, **filters)`` where filters are the
        parameters passed to ``Model.query.filter_by(**filters).one()`` to load the instance.

        :param _instance: Instance to commit
        :param filters: Filters required to load existing instance from the database
            in case the commit fails (required)
        :return: Instance that is in the database
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
    """
    Subclass of :class:`flask.ext.sqlalchemy.SQLAlchemy` that uses :class:`CoasterSession`,
    providing additional methods in the database session.
    """
    def create_session(self, options):
        """
        Creates the session using :class:`CoasterSession`.
        """
        return CoasterSession(self, **options)

db = SQLAlchemy()
