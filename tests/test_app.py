# -*- coding: utf-8 -*-

import unittest
from os import environ
import sys
from flask import Flask
from coaster.app import _additional_config, configure, load_config_from_file, SandboxedFlask
from coaster.logging import init_app, LocalVarFormatter


class TestCoasterUtils(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.another_app = Flask(__name__)

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

    def test_logging_handler(self):
        load_config_from_file(self.another_app, "testing.py")
        init_app(self.another_app)
        for handler in self.another_app.logger.handlers:
            try:
                raise
            except:
                formatter = handler.formatter
                if isinstance(formatter, LocalVarFormatter):
                    formatter.formatException(sys.exc_info())

    def test_load_config_from_file_IOError(self):
        app = Flask(__name__)
        self.assertFalse(load_config_from_file(app, "notfound.py"))


class TestSandBoxedFlask(unittest.TestCase):
    def setUp(self):
        self.app = SandboxedFlask(__name__)

    def test_sandboxed_flask_jinja(self):
        template = self.app.jinja_env.from_string("{{ obj.name }}, {{ obj._secret }}")

        class Test:
            def __init__(self, name, _secret):
                self.name = name
                self._secret = _secret

        obj = Test("Name", "secret")
        self.assertEqual(template.render(obj=obj), "%s, " % (obj.name))


if __name__ == '__main__':
    unittest.main()
