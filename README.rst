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

Create a test Coaster DB:

   $ createuser `whoami`
   $ createdb -O `whoami` coaster_test

Testing requires additional dependencies. Install them with:

   $ pip install -r test_requirements.txt

To run a single test:

   $ nosetests tests.<test_filename> # Example: `nosetests test.test_render_with`

To run all tests in one go:

   $ nosetests
