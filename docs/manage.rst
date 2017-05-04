App management script
=====================

Coaster provides a Flask-Script-based manage.py with common management functions.
To use in your Flask app, create a ``manage.py`` with this boilerplate::

    from coaster.manage import init_manager
    from hgapp import app, db
    manager = init_manager(app, db)

    if __name__ == "__main__":
        manager.run()


To see all available commands::

    $ python manage.py --help


.. automodule:: coaster.manage
   :members:
