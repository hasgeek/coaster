"""Tests for app."""

import sys
import unittest
from os import environ

import itsdangerous
import pytest
from flask import Flask

from coaster.app import (
    KeyRotationWrapper,
    RotatingKeySecureCookieSessionInterface,
    _additional_config,
    _config_loaders,
    init_app,
    load_config_from_file,
)
from coaster.compat import render_template_string, session
from coaster.logger import LocalVarFormatter, init_app as logger_init_app


class TestCoasterApp(unittest.TestCase):
    """Test coaster.app."""

    def setUp(self) -> None:
        """Initialize unit tests."""
        self.app = Flask(__name__)
        self.another_app = Flask(__name__)

    def test_load_config_from_file(self) -> None:
        """Test for config loaded from Python file."""
        load_config_from_file(self.app, 'settings.py')
        assert self.app.config['SETTINGS_KEY'] == 'settings'

    def test_load_config_from_file_json(self) -> None:
        """Test for config loaded from JSON file."""
        load_config_from_file(self.app, 'settings.json', _config_loaders['json'].loader)
        assert self.app.config['SETTINGS_KEY'] == 'settings_json'

    def test_load_config_from_file_toml(self) -> None:
        """Test for config loaded from TOML file."""
        load_config_from_file(
            self.app,
            'settings.toml',
            _config_loaders['toml'].loader,
            text=_config_loaders['toml'].text,
        )
        assert self.app.config['SETTINGS_KEY'] == 'settings_toml'

    def test_load_config_from_file_yaml(self) -> None:
        """Test for config loaded from YAML file."""
        load_config_from_file(self.app, 'settings.yaml', _config_loaders['yaml'].loader)
        assert self.app.config['SETTINGS_KEY'] == 'settings_yaml'

    def test_additional_settings_from_file(self) -> None:
        """Test for config loaded against ENV var."""
        env = 'FLASK_ENV'
        environ[env] = "gibberish"
        assert _additional_config.get(environ[env]) is None
        for k, v in _additional_config.items():
            environ[env] = k
            assert _additional_config.get(environ[env]) == v

    def test_init_app(self) -> None:
        """Test that init_app loads settings.py by default."""
        environ['FLASK_ENV'] = 'testing'
        init_app(self.app)
        assert self.app.config['SETTINGS_KEY'] == 'settings'
        assert self.app.config['TEST_KEY'] == 'test'

    def test_init_app_config_py_toml(self) -> None:
        """Test that init_app loads from TOML file if asked to."""
        environ['FLASK_ENV'] = 'testing'
        init_app(self.app, ['py', 'toml'])
        assert self.app.config['SETTINGS_KEY'] == 'settings_toml'

    def test_init_app_config_toml_py(self) -> None:
        """Test that init_app respects loading order for settings files."""
        environ['FLASK_ENV'] = 'testing'
        init_app(self.app, ['toml', 'py'])
        assert self.app.config['SETTINGS_KEY'] == 'settings'

    def test_init_app_config_env(self) -> None:
        """Test for config loaded from environment vars."""
        environ['FLASK_SETTINGS_STR'] = 'env-var'
        environ['FLASK_SETTINGS_QSTR'] = '"qenv-var"'
        environ['FLASK_SETTINGS_INT'] = '2'
        environ['FLASK_SETTINGS_FLOAT'] = '3.1'
        environ['FLASK_SETTINGS_BOOL'] = 'false'
        environ['FLASK_SETTINGS_NONE'] = 'null'
        environ['FLASK_SETTINGS_DICT'] = '{"json": "dict"}'
        environ['FLASK_SETTINGS_DICT__str'] = 'string-in-dict'
        environ['FLASK_SETTINGS_DICT__list'] = '["list", "in", "dict"]'
        init_app(self.app, ['env'])
        assert self.app.config['SETTINGS_STR'] == 'env-var'
        assert self.app.config['SETTINGS_QSTR'] == 'qenv-var'
        assert self.app.config['SETTINGS_INT'] == 2
        assert self.app.config['SETTINGS_FLOAT'] == 3.1
        assert self.app.config['SETTINGS_BOOL'] is False
        assert self.app.config['SETTINGS_NONE'] is None
        assert self.app.config['SETTINGS_DICT'] == {
            'json': 'dict',
            'str': 'string-in-dict',
            'list': ['list', 'in', 'dict'],
        }

    def test_init_app_config_env_custom_prefix(self) -> None:
        """Test for config loaded from environment vars with a custom prefix."""
        environ['APP_SETTINGS_STR'] = 'env-var'
        environ['APP_SETTINGS_QSTR'] = '"qenv-var"'
        environ['APP_SETTINGS_INT'] = '2'
        environ['APP_SETTINGS_FLOAT'] = '3.1'
        environ['APP_SETTINGS_BOOL'] = 'false'
        environ['APP_SETTINGS_NONE'] = 'null'
        environ['APP_SETTINGS_DICT'] = '{"json": "dict"}'
        environ['APP_SETTINGS_DICT__str'] = 'string-in-dict'
        environ['APP_SETTINGS_DICT__list'] = '["list", "in", "dict"]'
        init_app(self.app, ['env'], env_prefix='APP')
        assert self.app.config['SETTINGS_STR'] == 'env-var'
        assert self.app.config['SETTINGS_QSTR'] == 'qenv-var'
        assert self.app.config['SETTINGS_INT'] == 2
        assert self.app.config['SETTINGS_FLOAT'] == 3.1
        assert self.app.config['SETTINGS_BOOL'] is False
        assert self.app.config['SETTINGS_NONE'] is None
        assert self.app.config['SETTINGS_DICT'] == {
            'json': 'dict',
            'str': 'string-in-dict',
            'list': ['list', 'in', 'dict'],
        }

    def test_init_app_config_env_overlapping_prefix(self) -> None:
        """When using multiple env prefixes, they must not overlap."""
        with pytest.raises(
            ValueError, match="Env prefix FLASK_APP is overlapping an earlier prefix"
        ):
            init_app(self.app, env_prefix=['FLASK', 'FLASK_APP'])
        with pytest.raises(
            ValueError, match="Env prefix FLASK is overlapping an earlier prefix"
        ):
            init_app(self.app, env_prefix=['FLASK_APP', 'FLASK'])
        # No error because no overlap when an underscore is suffixed
        init_app(self.app, env_prefix=['FLASK', 'FLASKAPP'])

    def test_init_app_config_env_multi_prefix(self) -> None:
        """Test for config loaded from environment vars with multiple prefixes."""
        environ['FLASK_SETTINGS_STR'] = "env-var"
        environ['FLASK_SETTINGS_QSTR'] = '"qenv-var"'
        environ['FLASK_SETTINGS_INT'] = "2"
        environ['APP_SETTINGS_INT'] = "3"
        environ['FLASK_SETTINGS_FLOAT'] = "3.1"
        environ['FLASK_SETTINGS_BOOL'] = "false"
        environ['FLASK_SETTINGS_NONE'] = "null"
        environ['FLASK_SETTINGS_DICT'] = '{"json": "dict"}'
        environ['FLASK_SETTINGS_DICT__str'] = "string-in-dict"
        environ['FLASK_SETTINGS_DICT__list'] = '["list", "in", "dict"]'
        environ['APP_SETTINGS_DICT__int'] = "3"
        init_app(self.app, ['env'], env_prefix=['FLASK', 'APP'])
        assert self.app.config['SETTINGS_STR'] == 'env-var'
        assert self.app.config['SETTINGS_QSTR'] == 'qenv-var'
        assert self.app.config['SETTINGS_INT'] == 3
        assert self.app.config['SETTINGS_FLOAT'] == 3.1
        assert self.app.config['SETTINGS_BOOL'] is False
        assert self.app.config['SETTINGS_NONE'] is None
        assert self.app.config['SETTINGS_DICT'] == {
            'json': 'dict',
            'str': 'string-in-dict',
            'list': ['list', 'in', 'dict'],
            'int': 3,
        }

    def test_init_app_config_unknown_type(self) -> None:
        """Config must use one of the known types."""
        with pytest.raises(
            ValueError, match="exotic is not a recognized type of config"
        ):
            init_app(self.app, ['exotic'])  # type: ignore[list-item]

    def test_logging_handler(self) -> None:
        """Test that a logging handler is installed."""
        load_config_from_file(self.another_app, 'testing.py')
        logger_init_app(self.another_app)
        for handler in self.another_app.logger.handlers:
            try:
                raise Exception  # pylint: disable=broad-exception-raised
            except Exception:  # noqa: BLE001  # pylint: disable=broad-except
                formatter = handler.formatter
                if isinstance(formatter, LocalVarFormatter):
                    formatter.formatException(sys.exc_info())

    def test_load_config_from_file_ioerror(self) -> None:
        """Test that load_config_from_file returns False if file is not found."""
        app = Flask(__name__)
        assert not load_config_from_file(app, 'notfound.py')
        assert not load_config_from_file(
            app, 'notfound.json', load=_config_loaders['json'].loader
        )
        assert not load_config_from_file(
            app, 'notfound.toml', load=_config_loaders['toml'].loader
        )
        assert not load_config_from_file(
            app, 'notfound.yaml', load=_config_loaders['yaml'].loader
        )

    def test_current_auth(self) -> None:
        """Test that current_auth is available in Jinja2."""
        environ['FLASK_ENV'] = 'testing'
        init_app(self.app)
        with self.app.test_request_context():
            assert (
                render_template_string(
                    '{% if current_auth.is_authenticated %}Yes{% else %}No{% endif %}'
                )
                == 'No'
            )


def test_key_rotation_wrapper() -> None:
    """Test key rotation wrapper."""
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
    with pytest.raises(itsdangerous.BadSignature):
        serializer1b.loads(out2)
    with pytest.raises(itsdangerous.BadSignature):
        serializer2b.loads(out1)

    # The KeyRotationWrapper has a safety catch for when a string secret is provided
    with pytest.raises(ValueError, match="Secret keys must be a list"):
        KeyRotationWrapper(
            itsdangerous.URLSafeSerializer,
            'secret_key',  # type: ignore[arg-type]
        )

    # If KeyRotationWrapper somehow loses its engines, we'll get a RuntimeError instead
    # of BadSignature:
    loads = serializer1a.loads
    serializer1a._engines = []  # pylint: disable=protected-access
    with pytest.raises(RuntimeError):
        loads(out1)


def test_app_key_rotation() -> None:
    """Test key rotation."""
    app = Flask(__name__)
    app.session_interface = RotatingKeySecureCookieSessionInterface()

    @app.route('/set')
    def route_set() -> str:
        session['test'] = 'value'
        return 'set'

    @app.route('/get')
    def route_get() -> str:
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
