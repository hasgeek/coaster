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

You can also look at `.travis.yml` for instructions on how to run tests.
Create a test Coaster DB:

   $ createuser coaster
   $ createdb -O coaster coaster_test

Ensure you have PySQLite installed before you run:

   $ coverage run `which nosetests`

To run a single test:

   $ nosetests tests/<test_filename.py> # Example: `nosetests test/test_render_with.py`

