manage.py
=========

Coaster provides a Flask-Script-based manage.py with common management functions.
To use in your Flask app, create a ``manage.py`` with this boilerplate::

	from coaster import init_manager
	from hgapp	 import app, db, init_for
	manager = init_manager(app, db, init_for)

	if __name__ == "__main__":
		manager.run()


View all available commands

$python manage.py --help


.. automodule:: coaster.manage
   :members:
