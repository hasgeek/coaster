# -*- coding: utf-8 -*-

import unittest
from os import environ
from flask import Flask
from coaster.app import _additional_config, configure, load_config_from_file


class TestCoasterUtils(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def test_load_config_from_file(self):
        load_config_from_file(self.app, "settings.py")
        self.assertEqual(self.app.config['SETTINGS_KEY'], "settings")

    def test_additional_settings_from_file(self):
        env = 'COASTER_ENV'
        environ[env] = "gibberish"
        self.assertEqual(_additional_config.get(environ[env]), None)
        for k, v in _additional_config.items():
            environ[env] = k
            self.assertEqual(_additional_config.get(environ[env]), v)

    def test_configure(self):
        env = 'COASTER_ENV'
        environ[env] = "testing"
        configure(self.app, env)
        self.assertEqual(self.app.config['SETTINGS_KEY'], "settings")
        self.assertEqual(self.app.config['TEST_KEY'], "test")

if __name__ == '__main__':
    unittest.main()
