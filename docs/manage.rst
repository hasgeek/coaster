manage.py
=========

Coaster provides manage.py for all HasGeek App. To use in
your Flask app create `manage.py` in base directory::

	from coaster import init_manager
	from hacknight import app, db, init_for
	manager = init_manager(app, db, init_for)

	if __name__ == "__main__":
		manager.run()


View all available commands

$python manage.py --help


.. automodule:: coaster.manage
   :members:
