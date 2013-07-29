# -*- coding: utf-8 -*-

import unittest
from coaster.manage import init_manager, create, drop, set_alembic_revision
import coaster
from flask.ext.sqlalchemy import SQLAlchemy
from flask import Flask


class TestManagePy(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.db = SQLAlchemy(self.app)
        self.manage = init_manager(self.app, self.db, self.init_for)

    def init_for(self, env):
        coaster.app.init_app(self.app, env)

    def test_db_create(self):
        create('dev')
        #command.run()
        #self.assertEqual(self.manage._commands, ['showurls', 'set_alembic_version', 'shell', 'migrate', 'db', 'clean'])

    def test_db_drop(self):
        drop('dev')

    def set_alembic_revision(self):
        set_alembic_revision(path='tests/alembic')

if __name__ == '__main__':
    unittest.main()
