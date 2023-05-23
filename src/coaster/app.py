"""
App configuration
=================
"""

from __future__ import annotations

from collections import abc
from typing import NamedTuple
import json
import os
import types
import typing as t

from flask import Flask
from flask.json.provider import DefaultJSONProvider
from flask.sessions import SecureCookieSessionInterface
import itsdangerous

from . import logger
from .auth import current_auth
from .views import current_view

mod_toml: t.Optional[types.ModuleType] = None
mod_tomllib: t.Optional[types.ModuleType] = None
mod_tomli: t.Optional[types.ModuleType] = None
mod_yaml: t.Optional[types.ModuleType] = None

try:  # pragma: no cover
    import toml as mod_toml  # type: ignore[no-redef]
except ModuleNotFoundError:
    try:
        import tomllib as mod_tomllib  # type: ignore[no-redef]  # Python >= 3.11
    except ModuleNotFoundError:
        try:
            import tomli as mod_tomli  # type: ignore[no-redef]
        except ModuleNotFoundError:
            pass


try:  # pragma: no cover
    import yaml as mod_yaml
except ModuleNotFoundError:
    pass


__all__ = [
    'KeyRotationWrapper',
    'RotatingKeySecureCookieSessionInterface',
    'JSONProvider',
    'init_app',
]


class ConfigLoader(NamedTuple):
    """Configuration loader registry entry."""

    extn: t.Optional[str]
    loader: t.Optional[t.Callable]
    text: t.Optional[bool] = None


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
}
if mod_toml is not None:
    _config_loaders['toml'] = ConfigLoader(extn='.toml', loader=mod_toml.load)
elif mod_tomllib is not None:
    _config_loaders['toml'] = ConfigLoader(
        extn='.toml', loader=mod_tomllib.load, text=False
    )
elif mod_tomli is not None:
    _config_loaders['toml'] = ConfigLoader(
        extn='.toml', loader=mod_tomli.load, text=False
    )
if mod_yaml is not None:
    _config_loaders['yaml'] = ConfigLoader(extn='.yaml', loader=mod_yaml.safe_load)
    _config_loaders['yml'] = ConfigLoader(extn='.yml', loader=mod_yaml.safe_load)


_S = t.TypeVar('_S', bound=itsdangerous.Serializer)


class KeyRotationWrapper(t.Generic[_S]):  # pylint: disable=too-few-public-methods
    """
    Wrapper to support multiple secret keys in itsdangerous.

    The first secret key is used for all operations, but if it causes a BadSignature
    exception, the other secret keys are tried in order.

    :param cls: Signing class from itsdangerous (eg: URLSafeTimedSerializer)
    :param secret_keys: List of secret keys
    :param kwargs: Arguments to pass to each signer/serializer
    """

    def __init__(
        self,
        cls: t.Type[_S],
        secret_keys: t.List[str],
        **kwargs: t.Any,
    ) -> None:
        """Init key rotation wrapper."""
        if isinstance(secret_keys, str):  # type: ignore[unreachable]
            raise ValueError("Secret keys must be a list")
        if not secret_keys:
            raise ValueError("No secret keys in the list")
        self._engines = [cls(key, **kwargs) for key in secret_keys]

    def __getattr__(self, attr: str) -> t.Any:
        """Read a wrapped attribute."""
        item = getattr(self._engines[0], attr)
        return self._make_wrapper(attr) if callable(item) else item

    def _make_wrapper(self, attr: str) -> t.Callable:
        def wrapper(*args: t.Any, **kwargs: t.Any) -> t.Any:
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

    def get_signing_serializer(self, app: Flask) -> t.Optional[KeyRotationWrapper]:
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


class JSONProvider(DefaultJSONProvider):
    """Expand Flask's JSON provider to support the ``__json__`` protocol."""

    @staticmethod
    def default(o: t.Any) -> t.Any:
        """Expand default support to check for `__json__`."""
        if hasattr(o, '__json__'):
            return o.__json__()
        if isinstance(o, abc.Mapping):
            return dict(o)
        return DefaultJSONProvider.default(o)


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
    # Replace the default JSON provider if it isn't a custom one
    if app.json_provider_class is DefaultJSONProvider:
        app.json_provider_class = JSONProvider
        app.json = JSONProvider(app)
        app.jinja_env.policies['json.dumps_function'] = app.json.dumps
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
                text=_config_loaders[config_option].text,
            )

    # Load additional settings from the app's environment-specific config file(s): Flask
    # <2.3 sets ``ENV`` configuration variable based on ``FLASK_ENV`` environment
    # variable. FLASK_ENV is deprecated in Flask 2.2 and removed in 2.3, but Coaster
    # will fallback to reading ``FLASK_ENV`` from the environment.
    additional = _additional_config.get(
        (app.config.get('ENV', '') or os.environ.get('FLASK_ENV', '')).lower()
    )
    if additional:
        for config_option in config:
            if config_option != 'env':
                load_config_from_file(
                    app,
                    additional + t.cast(str, _config_loaders[config_option].extn),
                    load=_config_loaders[config_option].loader,
                    text=_config_loaders[config_option].text,
                )

    if init_logging:
        logger.init_app(app)


def load_config_from_file(
    app: Flask,
    filepath: str,
    load: t.Optional[t.Callable] = None,
    text: t.Optional[bool] = None,
) -> bool:
    """Load config from a specified file with a specified loader (default Python)."""
    try:
        if load is None:
            return app.config.from_pyfile(filepath)
        # The `text` parameter requires Flask 2.3. We still support Flask 2.2
        if text is not None:
            return app.config.from_file(  # type: ignore[attr-defined]
                filepath, load=load, text=text
            )
        return app.config.from_file(filepath, load=load)  # type: ignore[attr-defined]
    except OSError:
        app.logger.warning(
            "Did not find settings file %s for additional settings, skipping it",
            filepath,
        )
        return False
