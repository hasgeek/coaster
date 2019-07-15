# -*- coding: utf-8 -*-

import unittest

from flask_sqlalchemy import SQLAlchemy

from flask import Flask

from coaster.manage import init_manager, set_alembic_revision
import coaster


class TestManagePy(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        coaster.app.init_app(self.app)
        self.db = SQLAlchemy(self.app)

        self.manage = init_manager(self.app, self.db)

    def test_sqlalchemy_database_uri(self):
        """Check settings file loaded properly"""
        self.assertEqual('postgresql:///coaster_test', self.app.config.get('SQLALCHEMY_DATABASE_URI'))

    def test_set_alembic_revision(self):
        set_alembic_revision(path='tests/alembic')
