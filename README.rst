Coaster: common patterns for Flask and Quart apps
=================================================

|docs| |travis| |coveralls| |deepsource|

Coaster contains functions and db models for recurring patterns in Flask and Quart
apps. Documentation is at https://coaster.readthedocs.org/. Coaster requires
Python 3.9 or later.


Run tests
---------

Testing requires SQLite and PostgreSQL for the ``coaster.sqlalchemy`` module.
Create a test database in PostgreSQL::

    $ createuser `whoami`
    $ createdb -O `whoami` coaster_test

Testing also requires additional dependencies. Install them with::

    $ pip install -r test_requirements.txt

To run tests::

    $ pytest

Some tests are in the form of doctests within each function.


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
