SQLAlchemy patterns
===================

Coaster provides a number of mixin classes for SQLAlchemy models. To use in
your Flask app::

    from flask import Flask
    from flask.ext.sqlalchemy import SQLAlchemy
    from coaster.sqlalchemy import BaseMixin

    app = Flask(__name__)
    db = SQLAlchemy(app)

    class MyModel(BaseMixin, db.Model):
        __tablename__ = 'my_model'

Mixin classes must always appear *before* ``db.Model`` in your model's base classes.

.. automodule:: coaster.sqlalchemy
   :members:
