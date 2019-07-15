# -*- coding: utf-8 -*-

"""
Helper functions
----------------
"""

from __future__ import absolute_import
from sqlalchemy import Table, Column, ForeignKey, TIMESTAMP, func, event, inspect, DDL
from sqlalchemy.sql import functions
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import relationship, ColumnProperty
from sqlalchemy.orm.exc import NoResultFound

__all__ = ['make_timestamp_columns', 'failsafe_add', 'add_primary_relationship', 'auto_init_default']


# --- SQL functions -----------------------------------------------------------

# Provide sqlalchemy.func.utcnow()
# Adapted from http://docs.sqlalchemy.org/en/rel_1_0/core/compiler.html#utc-timestamp-function
class utcnow(functions.GenericFunction):  # NOQA: N801
    type = TIMESTAMP()  # NOQA: A003


@compiles(utcnow)
def _utcnow_default(element, compiler, **kw):
    return 'CURRENT_TIMESTAMP'


@compiles(utcnow, 'mysql')
def _utcnow_mysql(element, compiler, **kw):  # pragma: no cover
    return 'UTC_TIMESTAMP()'


@compiles(utcnow, 'mssql')
def _utcnow_mssql(element, compiler, **kw):  # pragma: no cover
    return 'SYSUTCDATETIME()'


# --- Helper functions --------------------------------------------------------

def make_timestamp_columns(timezone=False):
    """Return two columns, `created_at` and `updated_at`, with appropriate defaults"""
    return (
        Column(
            'created_at',
            TIMESTAMP(timezone=timezone),
            default=func.utcnow(),
            nullable=False
            ),
        Column(
            'updated_at',
            TIMESTAMP(timezone=timezone),
            default=func.utcnow(),
            onupdate=func.utcnow(),
            nullable=False
            ),
        )


def failsafe_add(_session, _instance, **filters):
    """
    Add and commit a new instance in a nested transaction (using SQL SAVEPOINT),
    gracefully handling failure in case a conflicting entry is already in the
    database (which may occur due to parallel requests causing race conditions
    in a production environment with multiple workers).

    Returns the instance saved to database if no error occurred, or loaded from
    database using the provided filters if an error occurred. If the filters fail
    to load from the database, the original IntegrityError is re-raised, as it
    is assumed to imply that the commit failed because of missing or invalid
    data, not because of a duplicate entry.

    However, when no filters are provided, nothing is returned and IntegrityError
    is also suppressed as there is no way to distinguish between data validation
    failure and an existing conflicting record in the database. Use this option
    when failures are acceptable but the cost of verification is not.

    Usage: ``failsafe_add(db.session, instance, **filters)`` where filters
    are the parameters passed to ``Model.query.filter_by(**filters).one()``
    to load the instance.

    You must commit the transaction as usual after calling ``failsafe_add``.

    :param _session: Database session
    :param _instance: Instance to commit
    :param filters: Filters required to load existing instance from the
        database in case the commit fails (required)
    :return: Instance that is in the database
    """
    if _instance in _session:
        # This instance is already in the session, most likely due to a
        # save-update cascade. SQLAlchemy will flush before beginning a
        # nested transaction, which defeats the purpose of nesting, so
        # remove it for now and add it back inside the SAVEPOINT.
        _session.expunge(_instance)
    _session.begin_nested()
    try:
        _session.add(_instance)
        _session.commit()
        if filters:
            return _instance
    except IntegrityError as e:
        _session.rollback()
        if filters:
            try:
                return _session.query(_instance.__class__).filter_by(**filters).one()
            except NoResultFound:  # Do not trap the other exception, MultipleResultsFound
                raise e


def add_primary_relationship(parent, childrel, child, parentrel, parentcol):
    """
    When a parent-child relationship is defined as one-to-many,
    :func:`add_primary_relationship` lets the parent refer to one child as the
    primary, by creating a secondary table to hold the reference. Under
    PostgreSQL, a trigger is added as well to ensure foreign key integrity.

    A SQLAlchemy relationship named ``parent.childrel`` is added that makes
    usage seamless within SQLAlchemy.

    The secondary table is named after the parent and child tables, with
    ``_primary`` appended, in the form ``parent_child_primary``. This table can
    be found in the metadata in the ``parent.metadata.tables`` dictionary.

    Multi-column primary keys on either parent or child are unsupported at
    this time.

    :param parent: The parent model (on which this relationship will be added)
    :param childrel: The name of the relationship to the child that will be
        added
    :param child: The child model
    :param str parentrel: Name of the existing relationship on the child model
        that refers back to the parent model
    :param str parentcol: Name of the existing table column on the child model
        that refers back to the parent model
    :return: None
    """

    parent_table_name = parent.__tablename__
    child_table_name = child.__tablename__
    primary_table_name = parent_table_name + '_' + child_table_name + '_primary'
    parent_id_columns = [c.name for c in inspect(parent).primary_key]
    child_id_columns = [c.name for c in inspect(child).primary_key]

    primary_table_columns = (
        [Column(
            parent_table_name + '_' + name,
            None,
            ForeignKey(parent_table_name + '.' + name, ondelete='CASCADE'),
            primary_key=True,
            nullable=False) for name in parent_id_columns]
        + [Column(
            child_table_name + '_' + name,
            None,
            ForeignKey(child_table_name + '.' + name, ondelete='CASCADE'),
            nullable=False) for name in child_id_columns]
        + list(make_timestamp_columns(timezone=parent.__with_timezone__))
        )

    primary_table = Table(primary_table_name, parent.metadata, *primary_table_columns)
    rel = relationship(child, uselist=False, secondary=primary_table)
    setattr(parent, childrel, rel)

    @event.listens_for(rel, 'set')
    def _validate_child(target, value, oldvalue, initiator):
        if value and getattr(value, parentrel) != target:
            raise ValueError("The target is not affiliated with this parent")

    # XXX: To support multi-column primary keys, update this SQL function
    event.listen(primary_table, 'after_create',
        DDL('''
            CREATE FUNCTION %(function)s() RETURNS TRIGGER AS $$
            DECLARE
                target RECORD;
            BEGIN
                IF (NEW.%(rhs)s IS NOT NULL) THEN
                    SELECT %(parentcol)s INTO target FROM %(child_table_name)s WHERE %(child_id_column)s = NEW.%(rhs)s;
                    IF (target.%(parentcol)s != NEW.%(lhs)s) THEN
                        RAISE foreign_key_violation USING MESSAGE = 'The target is not affiliated with this parent';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            CREATE TRIGGER %(trigger)s BEFORE INSERT OR UPDATE
            ON %(table)s
            FOR EACH ROW EXECUTE PROCEDURE %(function)s();
            ''',
            context={
                'table': primary_table_name,
                'function': '%s_validate' % primary_table_name,
                'trigger': '%s_trigger' % primary_table_name,
                'parentcol': parentcol,
                'child_table_name': child_table_name,
                'child_id_column': child_id_columns[0],
                'lhs': '%s_%s' % (parent_table_name, parent_id_columns[0]),
                'rhs': '%s_%s' % (child_table_name, child_id_columns[0]),
                }
            ).execute_if(dialect='postgresql')
        )

    event.listen(primary_table, 'before_drop',
        DDL('''
            DROP TRIGGER %(trigger)s ON %(table)s;
            DROP FUNCTION %(function)s();
            ''',
            context={
                'table': primary_table_name,
                'trigger': '%s_trigger' % primary_table_name,
                'function': '%s_validate' % primary_table_name,
                }
            ).execute_if(dialect='postgresql')
        )


def auto_init_default(column):
    """
    Set the default value for a column when it's first accessed rather than
    first committed to the database.
    """
    if isinstance(column, ColumnProperty):
        default = column.columns[0].default
    else:
        default = column.default

    @event.listens_for(column, 'init_scalar', retval=True, propagate=True)
    def init_scalar(target, value, dict_):
        # A subclass may override the column and not provide a default. Watch out for that.
        if default:
            if default.is_callable:
                value = default.arg(None)
            elif default.is_scalar:
                value = default.arg
            else:
                raise NotImplementedError("Can't invoke pre-default for a SQL-level column default")
            dict_[column.key] = value
            return value
