Coaster: common patterns for Flask apps
=======================================

.. image:: https://secure.travis-ci.org/hasgeek/coaster.png
   :alt: Build status

.. image:: https://coveralls.io/repos/hasgeek/coaster/badge.png
   :target: https://coveralls.io/r/hasgeek/coaster
   :alt: Coverage status

Coaster contains functions and db models for recurring patterns in Flask
apps. Documentation at http://coaster.readthedocs.org/

### Run tests

Testing requires SQLite and PostgreSQL. Create a test database in PostgreSQL::

    $ createuser `whoami`
    $ createdb -O `whoami` coaster_test

Testing also requires additional dependencies. Install them with::

    $ pip install -r test_requirements.txt

To run a single test::

    $ nosetests tests.<test_filename> 
    $ # Example: nosetests tests.test_render_with

To run all tests in one go::

    $ ./runtests.sh

Some tests are in the form of doctests within each function, and only
accessible by running all tests via ``runtests.sh``.
