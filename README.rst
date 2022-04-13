Coaster: common patterns for Flask apps
=======================================

|docs| |travis| |coveralls| |deepsource|

Coaster contains functions and db models for recurring patterns in Flask
apps. Documentation is at https://coaster.readthedocs.org/. Coaster requires
Python 3.7 or later.


Run tests
---------

Testing requires SQLite and PostgreSQL for the ``coaster.sqlalchemy`` module.
Create a test database in PostgreSQL::

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


.. |docs| image:: https://readthedocs.org/projects/coaster/badge/?version=latest
    :target: http://coaster.readthedocs.io/en/latest/?badge=latest
    :alt: Documentation status

.. |travis| image:: https://secure.travis-ci.org/hasgeek/coaster.svg?branch=master
    :target: https://travis-ci.org/hasgeek/coaster
    :alt: Build status

.. |coveralls| image:: https://coveralls.io/repos/hasgeek/coaster/badge.svg
    :target: https://coveralls.io/r/hasgeek/coaster
    :alt: Coverage status

.. |deepsource| image:: https://static.deepsource.io/deepsource-badge-light-mini.svg
    :target: https://deepsource.io/gh/hasgeek/coaster
    :alt: DeepSource Enabled
