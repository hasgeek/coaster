"""
App configuration
=================
"""

from typing import NamedTuple
import json
import typing as t

from flask import Flask
from flask.sessions import SecureCookieSessionInterface
import itsdangerous

import toml
import yaml

from . import logger
from .auth import current_auth
from .views import current_view

__all__ = [
    'KeyRotationWrapper',
    'RotatingKeySecureCookieSessionInterface',
    'Flask',
    'init_app',
]


class ConfigLoader(NamedTuple):
    """Configuration loader registry entry."""

    extn: t.Optional[str]
    loader: t.Optional[t.Callable]


_additional_config = {
    'dev': 'development',
    'development': 'development',
    'test': 'testing',
    'testing': 'testing',
    'prod': 'production',
    'production': 'production',
}

_config_loaders: t.Dict[str, ConfigLoader] = {
    'py': ConfigLoader(extn='.py', loader=None),
    'json': ConfigLoader(extn='.json', loader=json.load),
    'toml': ConfigLoader(extn='.toml', loader=toml.load),
    'yaml': ConfigLoader(extn='.yaml', loader=yaml.safe_load),
    'yml': ConfigLoader(extn='.yml', loader=yaml.safe_load),
}


class KeyRotationWrapper:  # pylint: disable=too-few-public-methods
    """
    Wrapper to support multiple secret keys in itsdangerous.

    The first secret key is used for all operations, but if it causes a BadSignature
    exception, the other secret keys are tried in order.

    :param cls: Signing class from itsdangerous (eg: URLSafeTimedSerializer)
    :param secret_keys: List of secret keys
    :param kwargs: Arguments to pass to each signer/serializer
    """

    def __init__(self, cls, secret_keys, **kwargs):
        """Init key rotation wrapper."""
        if isinstance(secret_keys, str):
            raise ValueError("Secret keys must be a list")
        self._engines = [cls(key, **kwargs) for key in secret_keys]

    def __getattr__(self, attr):
        """Read a wrapped attribute."""
        item = getattr(self._engines[0], attr)
        return self._make_wrapper(attr) if callable(item) else item

    def _make_wrapper(self, attr):
        def wrapper(*args, **kwargs):
            saved_exc = None
            for engine in self._engines:
                try:
                    return getattr(engine, attr)(*args, **kwargs)
                except itsdangerous.BadSignature as exc:
                    saved_exc = exc
            # We've run out of engines.
            raise saved_exc

        return wrapper


class RotatingKeySecureCookieSessionInterface(SecureCookieSessionInterface):
    """Replaces the serializer with key rotation support."""

    def get_signing_serializer(self, app):
        """Return serializers wrapped for key rotation."""
        if not app.config.get('SECRET_KEYS'):
            return None
        signer_kwargs = {
            'key_derivation': self.key_derivation,
            'digest_method': self.digest_method,
        }

        return KeyRotationWrapper(
            itsdangerous.URLSafeTimedSerializer,
            app.config['SECRET_KEYS'],
            salt=self.salt,
            serializer=self.serializer,
            signer_kwargs=signer_kwargs,
        )


def init_app(
    app: Flask, config: t.Optional[t.List[str]] = None, init_logging: bool = True
) -> None:
    """
    Configure an app depending on the environment.

    Loads settings from a file named ``settings.py`` in the instance folder, followed
    by additional settings from one of ``development.py``, ``production.py`` or
    ``testing.py``. Can also load from JSON, TOML or YAML files if requested. Typical
    usage::

        from flask import Flask
        import coaster.app

        app = Flask(__name__, instance_relative_config=True)
        # Any one of the following lines. Runtime environment will be as per FLASK_ENV
        coaster.app.init_app(app)  # Load config from Python files
        coaster.app.init_app(app, config=['json'])  # Load config from JSON files
        coaster.app.init_app(app, config=['toml'])  # Load config from TOML files
        coaster.app.init_app(app, config=['yaml'])  # Load config from YAML files
        coaster.app.init_app(app, config=['py', 'toml'])  # Both Python & TOML config

    :func:`init_app` also configures logging by calling
    :func:`coaster.logger.init_app`.

    :param app: App to be configured
    :param config: Types of config files, one or more of of ``py`` (default), ``json``,
        ``toml`` and ``yaml``
    :param bool init_logging: Call `coaster.logger.init_app` (default `True`)
    """
    if not config:
        config = ['env', 'py']
    # Make current_auth available to app templates
    app.jinja_env.globals['current_auth'] = current_auth
    # Make the current view available to app templates
    app.jinja_env.globals['current_view'] = current_view
    # Disable Flask-SQLAlchemy events.
    # Apps that want it can turn it back on in their config
    app.config.setdefault('SQLALCHEMY_TRACK_MODIFICATIONS', False)
    # Load config from the app's settings[.py]
    for config_option in config:
        if config_option == 'env':
            app.config.from_prefixed_env()  # type: ignore[attr-defined]
        elif config_option not in _config_loaders:
            raise ValueError(f"{config_option} is not a recognized type of config")
        else:
            load_config_from_file(
                app,
                'settings' + t.cast(str, _config_loaders[config_option].extn),
                load=_config_loaders[config_option].loader,
            )

    # Load additional settings from the app's environment-specific config file(s):
    # Flask <2.3 sets ``ENV`` configuration variable based on ``FLASK_ENV`` environment
    # variable. FLASK_ENV is deprecated in Flask 2.2 and will be removed in 2.3. Apps
    # must be updated to prefer config from env.
    additional = _additional_config.get(app.config.get('ENV', '').lower())
    if additional:
        for config_option in config:
            if config_option != 'env':
                load_config_from_file(
                    app,
                    additional + t.cast(str, _config_loaders[config_option].extn),
                    load=_config_loaders[config_option].loader,
                )

    if init_logging:
        logger.init_app(app)


def load_config_from_file(
    app: Flask, filepath: str, load: t.Optional[t.Callable] = None
) -> bool:
    """Load config from a specified file with a specified loader (default Python)."""
    try:
        if load is None:
            app.config.from_pyfile(filepath)
        else:
            app.config.from_file(filepath, load=load)  # type: ignore[attr-defined]
        return True
    except OSError:
        app.logger.warning(
            "Did not find settings file %s for additional settings, skipping it",
            filepath,
        )
        return False