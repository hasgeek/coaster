Database instance
=================

Coaster provides an instance of Flask-SQLAlchemy. If your app has models
distributed across modules, you can use coaster's instance instead of
creating a new module solely for a shared dependency. Some HasGeek libraries
like nodular_ and `Flask-Commentease`_ use this instance for their models.

.. py:attribute:: db

    Instance of :class:`flask.ext.sqlalchemy.SQLAlchemy`

    .. caution::
        This instance is process-global. Your database models will be shared
        across all apps running in the same process. Do not run unrelated
        apps in the same process.
