# -*- coding: utf-8 -*-

import unittest
from os import environ
import sys
from flask import Flask
from coaster.app import _additional_config, configure, load_config_from_file, SandboxedFlask
from coaster.logging import init_app


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

    def test_testing_settings_file(self):
        self.another_app = Flask(__name__)
        load_config_from_file(self.another_app, "testing.py")
        init_app(self.another_app)
        # Get file handler log, figured out by brute forcing
        r = self.another_app.logger.handlers[1]
        try:
            raise
        except:
            self.assertTrue(isinstance(r.formatter.formatException(sys.exc_info()), str))

    def test_load_config_from_file_IOError(self):
        app = Flask(__name__)
        load_config_from_file(app, "notfound.py")


class TestSandBoxedFlask(unittest.TestCase):
    def setUp(self):
        self.app = SandboxedFlask(__name__)

    def test_sandboxed_flask(self):
        rv = self.app.create_jinja_environment()
        self.assertFalse(rv.tests['odd'](4))


if __name__ == '__main__':
    unittest.main()
