# -*- coding: utf-8 -*-

from os import environ
import sys
import unittest

from flask import Flask, render_template_string

from coaster.app import (
    SandboxedFlask,
    _additional_config,
    init_app,
    load_config_from_file,
)
from coaster.logger import LocalVarFormatter
from coaster.logger import init_app as logger_init_app


class TestCoasterUtils(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.another_app = Flask(__name__)

    def test_load_config_from_file(self):
        load_config_from_file(self.app, "settings.py")
        assert self.app.config['SETTINGS_KEY'] == "settings"

    def test_additional_settings_from_file(self):
        env = 'COASTER_ENV'
        environ[env] = "gibberish"
        assert _additional_config.get(environ[env]) is None
        for k, v in _additional_config.items():
            environ[env] = k
            assert _additional_config.get(environ[env]) == v

    def test_init_app(self):
        environ['FLASK_ENV'] = "testing"
        init_app(self.app)
        assert self.app.config['SETTINGS_KEY'] == "settings"
        assert self.app.config['TEST_KEY'] == "test"

    def test_logging_handler(self):
        load_config_from_file(self.another_app, "testing.py")
        logger_init_app(self.another_app)
        for handler in self.another_app.logger.handlers:
            try:
                raise Exception
            except Exception:  # skipcq: PYL-W0703
                formatter = handler.formatter
                if isinstance(formatter, LocalVarFormatter):
                    formatter.formatException(sys.exc_info())

    def test_load_config_from_file_ioerror(self):
        app = Flask(__name__)
        assert not load_config_from_file(app, "notfound.py")

    def test_current_auth(self):
        environ['FLASK_ENV'] = "testing"
        init_app(self.app)
        with self.app.test_request_context():
            assert (
                render_template_string(
                    '{% if current_auth.is_authenticated %}Yes{% else %}No{% endif %}'
                )
                == 'No'
            )


class TestSandBoxedFlask(unittest.TestCase):
    def setUp(self):
        self.app = SandboxedFlask(__name__)

    def test_sandboxed_flask_jinja(self):
        template = self.app.jinja_env.from_string("{{ obj.name }}, {{ obj._secret }}")

        class Test(object):
            def __init__(self, name, _secret):
                self.name = name
                self._secret = _secret

        obj = Test("Name", "secret")
        assert template.render(obj=obj) == "%s, " % (obj.name)
