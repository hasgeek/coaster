Coaster: common patterns for Flask apps
=======================================

|travis| |coveralls|

Coaster contains functions and db models for recurring patterns in Flask
apps. Documentation at http://coaster.readthedocs.org/

Coaster is compatible with Python versions 2.7 and 3.6. Earlier 3.x versions
are not supported due to obsolete SQLite drivers missing some functionality.
If you need to use an earlier 3.x version (3.3-3.5) and don't use SQLite, you
may still be in luck.


Run tests
---------

Testing requires SQLite and PostgreSQL for the ``coaster.sqlalchemy`` module.
Create a test database in PostgreSQL::

    $ createuser `whoami`
    $ createdb -O `whoami` coaster_test

Testing also requires additional dependencies. Install them with::

    $ pip install -r test_requirements.txt

On Python 2.7, an additional package is required, to replace the obsolete
SQLite driver shipped with 2.7::

    $ pip install PySqlite

To run a single test::

    $ nosetests tests.<test_filename> 
    $ # Example: nosetests tests.test_render_with

To run all tests in one go::

    $ ./runtests.sh

Some tests are in the form of doctests within each function, and only
accessible by running all tests via ``runtests.sh``.


.. |travis| image:: https://secure.travis-ci.org/hasgeek/coaster.svg?branch=master
    :target: https://travis-ci.org/hasgeek/coaster
    :alt: Build status

.. |coveralls| image:: https://coveralls.io/repos/hasgeek/coaster/badge.svg
    :target: https://coveralls.io/r/hasgeek/coaster
    :alt: Coverage status
