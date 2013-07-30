# -*- coding: utf-8 -*-

import unittest
from coaster.manage import init_manager, set_alembic_revision
import coaster
from flask.ext.sqlalchemy import SQLAlchemy
from flask import Flask


class TestManagePy(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.from_pyfile('development.py')
        self.db = SQLAlchemy(self.app)

        class Test(self.db.Model):
            __table__ = "test"
            name = self.db.Column(self.db.Unicode(32))
        self.Test = Test
        self.manage = init_manager(self.app, self.db, self.init_for)

    def init_for(self, env):
        coaster.app.init_app(self.app, env)

    def test_set_alembic_revision(self):
        set_alembic_revision(path='tests/alembic')

if __name__ == '__main__':
    unittest.main()
