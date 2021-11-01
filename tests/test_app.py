from os import environ
import sys
import unittest

from flask import Flask, render_template_string, session
import itsdangerous

import pytest

from coaster.app import (
    KeyRotationWrapper,
    RotatingKeySecureCookieSessionInterface,
    _additional_config,
    _config_loaders,
    init_app,
    load_config_from_file,
)
from coaster.logger import LocalVarFormatter
from coaster.logger import init_app as logger_init_app


class TestCoasterApp(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.another_app = Flask(__name__)

    def test_load_config_from_file(self):
        load_config_from_file(self.app, 'settings.py')
        assert self.app.config['SETTINGS_KEY'] == "settings"

    def test_load_config_from_file_json(self):
        load_config_from_file(self.app, 'settings.json', _config_loaders['json'])
        assert self.app.config['SETTINGS_KEY'] == "settings_json"

    def test_load_config_from_file_toml(self):
        load_config_from_file(self.app, 'settings.toml', _config_loaders['toml'])
        assert self.app.config['SETTINGS_KEY'] == "settings_toml"

    def test_load_config_from_file_yaml(self):
        load_config_from_file(self.app, 'settings.yaml', _config_loaders['yaml'])
        assert self.app.config['SETTINGS_KEY'] == "settings_yaml"

    def test_additional_settings_from_file(self):
        env = 'COASTER_ENV'
        environ[env] = "gibberish"
        assert _additional_config.get(environ[env]) is None
        for k, v in _additional_config.items():
            environ[env] = k
            assert _additional_config.get(environ[env]) == v

    def test_init_app(self):
        environ['FLASK_ENV'] = 'testing'
        init_app(self.app)
        assert self.app.config['SETTINGS_KEY'] == 'settings'
        assert self.app.config['TEST_KEY'] == 'test'

    def test_logging_handler(self):
        load_config_from_file(self.another_app, 'testing.py')
        logger_init_app(self.another_app)
        for handler in self.another_app.logger.handlers:
            try:
                raise Exception
            except Exception:  # noqa: B902 # skipcq: PYL-W0703
                formatter = handler.formatter
                if isinstance(formatter, LocalVarFormatter):
                    formatter.formatException(sys.exc_info())

    def test_load_config_from_file_ioerror(self):
        app = Flask(__name__)
        assert not load_config_from_file(app, 'notfound.py')
        assert not load_config_from_file(
            app, 'notfound.json', load=_config_loaders['json']
        )
        assert not load_config_from_file(
            app, 'notfound.toml', load=_config_loaders['toml']
        )
        assert not load_config_from_file(
            app, 'notfound.yaml', load=_config_loaders['yaml']
        )

    def test_current_auth(self):
        environ['FLASK_ENV'] = 'testing'
        init_app(self.app)
        with self.app.test_request_context():
            assert (
                render_template_string(
                    '{% if current_auth.is_authenticated %}Yes{% else %}No{% endif %}'
                )
                == 'No'
            )


def test_key_rotation_wrapper():
    payload = {'test': 'value'}

    secret_keys1 = ['key1', 'key2', 'key3']
    secret_keys2 = list(reversed(secret_keys1))

    # These serializers share the same secret keys in different orders of priority
    serializer1a = KeyRotationWrapper(itsdangerous.URLSafeSerializer, secret_keys1)
    serializer2a = KeyRotationWrapper(itsdangerous.URLSafeSerializer, secret_keys2)

    # These are truncated to drop the last secret key (which is the first of the other)
    serializer1b = KeyRotationWrapper(itsdangerous.URLSafeSerializer, secret_keys1[:-1])
    serializer2b = KeyRotationWrapper(itsdangerous.URLSafeSerializer, secret_keys2[:-1])

    out1 = serializer1a.dumps(payload)
    out1b = serializer1b.dumps(payload)
    out2 = serializer2a.dumps(payload)
    out2b = serializer2b.dumps(payload)

    assert out1 == out1b
    assert out2 == out2b
    assert out1 != out2
    # We'll ignore the b outputs from here onward since they are the same

    # The serializers can load their own output
    assert serializer1a.loads(out1) == payload
    assert serializer1b.loads(out1) == payload
    assert serializer2a.loads(out2) == payload
    assert serializer2b.loads(out2) == payload

    # The serializers that share a full set of secret keys can read each others' outputs
    assert serializer1a.loads(out2) == payload
    assert serializer2a.loads(out1) == payload

    # However, the serializers with missing secret keys will raise BadSignature
    with pytest.raises(itsdangerous.exc.BadSignature):
        serializer1b.loads(out2)
    with pytest.raises(itsdangerous.exc.BadSignature):
        serializer2b.loads(out1)

    # The KeyRotationWrapper has a safety catch for when a string secret is provided
    with pytest.raises(ValueError):
        KeyRotationWrapper(itsdangerous.URLSafeSerializer, 'secret_key')


def test_app_key_rotation():
    app = Flask(__name__)
    app.session_interface = RotatingKeySecureCookieSessionInterface()

    @app.route('/set')
    def route_set():
        session['test'] = 'value'
        return 'set'

    @app.route('/get')
    def route_get():
        return str(session.get('test') == 'value')

    app.config['SECRET_KEYS'] = ['key1', 'key2']
    app.config['SECRET_KEY'] = app.config['SECRET_KEYS'][0]

    with app.test_client() as c:
        rv = c.get('/set')
        assert 'Set-Cookie' in rv.headers
        rv = c.get('/get')
        assert 'Set-Cookie' not in rv.headers
        assert rv.data == b'True'

        # Rotate secret keys and confirm cookie still works
        app.config['SECRET_KEYS'] = ['key_new', 'key1']
        app.config['SECRET_KEY'] = app.config['SECRET_KEYS'][0]

        rv = c.get('/get')
        assert 'Set-Cookie' not in rv.headers  # Won't be set until amended
        assert rv.data == b'True'

        # Now change secret keys to something entirely new and confirm cookie is invalid
        app.config['SECRET_KEYS'] = ['new']
        app.config['SECRET_KEY'] = app.config['SECRET_KEYS'][0]

        rv = c.get('/get')
        assert rv.data == b'False'

    # We'll get a RuntimeError without a secret keys list
    del app.config['SECRET_KEYS']
    # SECRET_KEY is present but no longer consulted
    assert app.config['SECRET_KEY']
    with app.test_client() as c:
        rv = c.get('/set')
        assert rv.status_code == 500  # RuntimeError was raised
