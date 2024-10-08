"""App configuration."""

# pyright: reportMissingImports=false

from __future__ import annotations

import json
import os
import types
from collections.abc import Sequence
from typing import (
    Any,
    Callable,
    Generic,
    Literal,
    NamedTuple,
    NoReturn,
    Optional,
    TypeVar,
    Union,
    cast,
)
from typing_extensions import deprecated

import itsdangerous
from flask.json.provider import DefaultJSONProvider
from flask.sessions import (
    SecureCookieSessionInterface as FlaskSecureCookieSessionInterface,
)

try:
    from quart.sessions import (
        SecureCookieSessionInterface as QuartSecureCookieSessionInterface,
    )
except ModuleNotFoundError:
    QuartSecureCookieSessionInterface = FlaskSecureCookieSessionInterface  # type: ignore[assignment,misc]

from . import logger
from .auth import current_auth
from .compat import JSONProvider, SansIoApp
from .views import current_view

__all__ = [
    'FlaskRotatingKeySecureCookieSessionInterface',
    'JSONProvider',
    'KeyRotationWrapper',
    'QuartRotatingKeySecureCookieSessionInterface',
    'RotatingKeySecureCookieSessionInterface',
    'init_app',
]

# --- Optional config loaders ----------------------------------------------------------

mod_toml: Optional[types.ModuleType] = None
mod_tomllib: Optional[types.ModuleType] = None
mod_tomli: Optional[types.ModuleType] = None
mod_yaml: Optional[types.ModuleType] = None

try:
    import tomllib as mod_tomllib  # type: ignore[no-redef]  # Python >= 3.11
except ModuleNotFoundError:
    try:
        import toml as mod_toml  # type: ignore[no-redef,unused-ignore]
    except ModuleNotFoundError:
        try:  # noqa: SIM105
            import tomli as mod_tomli  # type: ignore[no-redef,unused-ignore]
        except ModuleNotFoundError:
            pass


try:  # noqa: SIM105
    import yaml as mod_yaml
except ModuleNotFoundError:
    pass


# --- Helpers --------------------------------------------------------------------------


class ConfigLoader(NamedTuple):
    """Configuration loader registry entry."""

    extn: Optional[str]
    loader: Optional[Callable]
    text: Optional[bool] = None


_additional_config = {
    'dev': 'development',
    'development': 'development',
    'test': 'testing',
    'testing': 'testing',
    'prod': 'production',
    'production': 'production',
}

_config_loaders: dict[str, ConfigLoader] = {
    'py': ConfigLoader(extn='.py', loader=None),
    'json': ConfigLoader(extn='.json', loader=json.load),
}
if mod_tomllib is not None:
    _config_loaders['toml'] = ConfigLoader(
        extn='.toml', loader=mod_tomllib.load, text=False
    )
elif mod_toml is not None:
    _config_loaders['toml'] = ConfigLoader(
        extn='.toml', loader=mod_toml.load, text=True
    )
elif mod_tomli is not None:
    _config_loaders['toml'] = ConfigLoader(
        extn='.toml', loader=mod_tomli.load, text=False
    )
if mod_yaml is not None:
    _config_loaders['yaml'] = ConfigLoader(extn='.yaml', loader=mod_yaml.safe_load)
    _config_loaders['yml'] = ConfigLoader(extn='.yml', loader=mod_yaml.safe_load)


_S = TypeVar('_S', bound='itsdangerous.Serializer[Any]')


_sentinel_keyrotation_exception = RuntimeError("KeyRotationWrapper has no engines.")


# --- Key rotation wrapper -------------------------------------------------------------


class KeyRotationWrapper(Generic[_S]):
    """
    Wrapper to support multiple secret keys in itsdangerous.

    The first secret key is used for all operations, but if it causes a BadSignature
    exception, the other secret keys are tried in order.

    :param cls: Signing class from itsdangerous (eg: URLSafeTimedSerializer)
    :param secret_keys: List of secret keys
    :param kwargs: Arguments to pass to each signer/serializer
    """

    @property
    def __class__(self) -> type:
        """Mimic wrapped engine's class."""
        if self._engines:
            return type(self._engines[0])
        return KeyRotationWrapper

    @__class__.setter
    def __class__(self, value: Any) -> NoReturn:
        # This setter is required for static type checkers
        raise TypeError("__class__ cannot be set.")

    def __init__(
        self,
        cls: type[_S],
        secret_keys: list[str],
        **kwargs: Any,
    ) -> None:
        """Init key rotation wrapper."""
        if isinstance(secret_keys, (str, bytes)):  # type: ignore[unreachable]
            raise ValueError("Secret keys must be a list")
        if not secret_keys:
            raise ValueError("No secret keys in the list")
        self._engines = [cls(key, **kwargs) for key in secret_keys]

    def __getattr__(self, name: str) -> Any:
        """Read a wrapped attribute."""
        item = getattr(self._engines[0], name)
        return self._make_wrapper(name) if callable(item) else item

    def _make_wrapper(self, name: str) -> Callable:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            saved_exc: Exception = _sentinel_keyrotation_exception
            for engine in self._engines:
                try:
                    return getattr(engine, name)(*args, **kwargs)
                except itsdangerous.BadSignature as exc:  # noqa: PERF203
                    saved_exc = exc
            # We've run out of engines and all of them reported BadSignature.
            # If there were no engines, the sentinel RuntimeError exception is used
            raise saved_exc

        return wrapper


def _get_signing_serializer(
    self: Union[
        FlaskRotatingKeySecureCookieSessionInterface,
        QuartRotatingKeySecureCookieSessionInterface,
    ],
    app: SansIoApp,
) -> Optional[KeyRotationWrapper]:
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


class FlaskRotatingKeySecureCookieSessionInterface(FlaskSecureCookieSessionInterface):
    """Replaces the serializer with key rotation support."""

    get_signing_serializer = _get_signing_serializer  # type: ignore[assignment]


class QuartRotatingKeySecureCookieSessionInterface(QuartSecureCookieSessionInterface):
    """Replaces the serializer with key rotation support."""

    get_signing_serializer = _get_signing_serializer  # type: ignore[assignment]


# Flask version is also available with an unprefixed name
RotatingKeySecureCookieSessionInterface = deprecated(
    "Renamed to FlaskRotatingKeySecureCookieSessionInterface"
)(FlaskRotatingKeySecureCookieSessionInterface)

# --- App init utilities ---------------------------------------------------------------


def init_app(
    app: SansIoApp,
    config: Optional[list[Literal['env', 'py', 'json', 'toml', 'yaml']]] = None,
    *,
    env_prefix: Optional[Union[str, Sequence[str]]] = None,
    init_logging: bool = True,
) -> None:
    """
    Configure an app depending on the runtime environment.

    Loads settings from environment variables, Python files or JSON/YAML/TOML files,
    allowing for additional files and environment prefixes based on the ``FLASK_ENV``
    environment variable. Flask 2.3 drops support for ``FLASK_ENV``, but this function
    continues to support it. Typical usage::

        from flask import Flask
        import coaster.app

        app = Flask(__name__, instance_relative_config=True)
        # Any one of the following lines. Runtime environment will be as per FLASK_ENV
        coaster.app.init_app(app)  # Load config from environment and Python files
        coaster.app.init_app(app, config=['json'])  # Load config from JSON files
        coaster.app.init_app(app, config=['toml'])  # Load config from TOML files
        coaster.app.init_app(app, config=['yaml'])  # Load config from YAML files
        coaster.app.init_app(app, config=['py', 'toml'])  # Both Python & TOML config
        coaster.app.init_app(app, config=['env'], env_prefix=['FLASK', 'FLASK_EXTRA'])

    When using the file loaders, additional files named ``testing.*``, ``development.*``
    or ``production.*`` will be loaded depending on the value of ``FLASK_ENV``.

    :func:`init_app` also configures logging by calling
    :func:`coaster.logger.init_app` unless ``init_logging`` is False.

    :param app: App to be configured
    :param config: Types of config sources, one or more of of ``env``, ``py``, ``json``,
        ``toml`` and ``yaml``
    :param bool init_logging: Call `coaster.logger.init_app` (default `True`)

    .. note::
        YAML support requires PyYAML_. TOML requires toml_ with Flask 2.2, or tomli_
        with Flask 2.3, or Python's inbuilt tomllib_ with Flask 2.3 and Python 3.11+.
        tomli_ and tomllib_ are not compatible with Flask 2.2 as they require the file
        to be opened in binary mode, an optional flag introduced in Flask 2.3.

    .. _PyYAML: https://pypi.org/project/PyYAML/
    .. _toml: https://pypi.org/project/toml/
    .. _tomli: https://pypi.org/project/tomli/
    .. _tomllib: https://docs.python.org/3/library/tomllib.html
    """
    if not config:
        config = ['env', 'py']
    # Replace the default JSON provider if it isn't a custom one
    if app.json_provider_class is DefaultJSONProvider:  # Quart uses Flask's default
        app.json_provider_class = JSONProvider
        app.json = JSONProvider(app)
        app.jinja_env.policies['json.dumps_function'] = app.json.dumps
    # Make current_auth available to app templates
    if 'current_auth' not in app.jinja_env.globals:
        # Don't override if the app installed a custom proxy
        app.jinja_env.globals['current_auth'] = current_auth
    # Make the current view available to app templates
    app.jinja_env.globals['current_view'] = current_view
    # Disable Flask-SQLAlchemy events.
    # Apps that want it can turn it back on in their config
    app.config.setdefault('SQLALCHEMY_TRACK_MODIFICATIONS', False)
    # Load config from the app's settings[.py]
    for config_option in config:
        if config_option == 'env':
            if env_prefix is None:
                # Use Flask or Quart's default env prefix
                app.config.from_prefixed_env()
            elif isinstance(env_prefix, str):
                # Use the app's requested env prefix
                app.config.from_prefixed_env(env_prefix)
            else:
                # Load config for each of the requested prefixes, checking for overlaps
                # in prefix names
                used_prefixes: set[str] = set()
                for prefix in env_prefix:
                    if any(
                        prefix.startswith(used + '_') for used in used_prefixes
                    ) or any(used.startswith(prefix + '_') for used in used_prefixes):
                        raise ValueError(
                            f"Env prefix {prefix} is overlapping an earlier prefix"
                        )
                    app.config.from_prefixed_env(prefix)
                    used_prefixes.add(prefix)
        elif config_option not in _config_loaders:
            raise ValueError(f"{config_option} is not a recognized type of config")
        else:
            load_config_from_file(
                app,
                'settings' + cast(str, _config_loaders[config_option].extn),
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
                    additional + cast(str, _config_loaders[config_option].extn),
                    load=_config_loaders[config_option].loader,
                    text=_config_loaders[config_option].text,
                )

    if init_logging:
        logger.init_app(app, _warning_stacklevel=3)


def load_config_from_file(
    app: SansIoApp,
    filepath: str,
    load: Optional[Callable] = None,
    text: Optional[bool] = None,
) -> bool:
    """Load config from a specified file with a specified loader (default Python)."""
    try:
        if load is None:
            return app.config.from_pyfile(filepath)
        # The `text` parameter was introduced in Flask 2.3, but its default value
        # may change in a future release, so we only supply a value if we have a bool
        if text is not None:
            return app.config.from_file(filepath, load=load, text=text)
        return app.config.from_file(filepath, load=load)
    except OSError:
        app.logger.warning(
            "Did not find settings file %s for additional settings, skipping it",
            filepath,
        )
        return False
