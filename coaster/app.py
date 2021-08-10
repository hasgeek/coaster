"""
App configuration
=================
"""

from flask import Flask
from flask.sessions import SecureCookieSessionInterface
import itsdangerous

from . import logger
from .auth import current_auth
from .views import current_view

__all__ = [
    'KeyRotationWrapper',
    'RotatingKeySecureCookieSessionInterface',
    'Flask',
    'init_app',
]

_additional_config = {
    'dev': 'development.py',
    'development': 'development.py',
    'test': 'testing.py',
    'testing': 'testing.py',
    'prod': 'production.py',
    'production': 'production.py',
}


class KeyRotationWrapper:
    """
    Wrapper to support multiple secret keys in itsdangerous.

    The first secret key is used for all operations, but if it causes a BadSignature
    exception, the other secret keys are tried in order.

    :param cls: Signing class from itsdangerous (eg: URLSafeTimedSerializer)
    :param secret_keys: List of secret keys
    :param kwargs: Arguments to pass to each signer/serializer
    """

    def __init__(self, cls, secret_keys, **kwargs):
        if isinstance(secret_keys, str):
            raise ValueError("Secret keys must be a list")
        self._engines = [cls(key, **kwargs) for key in secret_keys]

    def __getattr__(self, attr):
        item = getattr(self._engines[0], attr)
        return self._make_wrapper(attr) if callable(item) else item

    def _make_wrapper(self, attr):
        def wrapper(*args, **kwargs):
            last = len(self._engines) - 1
            for counter, engine in enumerate(self._engines):
                try:
                    return getattr(engine, attr)(*args, **kwargs)
                except itsdangerous.exc.BadSignature:
                    if counter == last:
                        # We've run out of engines. Raise error to caller
                        raise

        return wrapper


class RotatingKeySecureCookieSessionInterface(SecureCookieSessionInterface):
    """Replaces the serializer with key rotation support"""

    def get_signing_serializer(self, app):
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


def init_app(app, init_logging=True):
    """
    Configure an app depending on the environment. Loads settings from a file
    named ``settings.py`` in the instance folder, followed by additional
    settings from one of ``development.py``, ``production.py`` or
    ``testing.py``. Typical usage::

        from flask import Flask
        import coaster.app

        app = Flask(__name__, instance_relative_config=True)
        coaster.app.init_app(app)  # Guess environment automatically

    :func:`init_app` also configures logging by calling
    :func:`coaster.logger.init_app`.

    :param app: App to be configured
    :param bool init_logging: Call `coaster.logger.init_app` (default `True`)
    """
    # Make current_auth available to app templates
    app.jinja_env.globals['current_auth'] = current_auth
    # Make the current view available to app templates
    app.jinja_env.globals['current_view'] = current_view
    # Disable Flask-SQLAlchemy events.
    # Apps that want it can turn it back on in their config
    app.config.setdefault('SQLALCHEMY_TRACK_MODIFICATIONS', False)
    # Load config from the app's settings.py
    load_config_from_file(app, 'settings.py')

    # Load additional settings from the app's environment-specific config file:
    # Flask sets ``ENV`` configuration variable based on ``FLASK_ENV`` environment
    # variable. So we can directly get it from ``app.config['ENV']``.
    # Lowercase because that's how flask defines it.
    # ref: https://flask.palletsprojects.com/en/1.1.x/config/#environment-and-debug-features
    additional = _additional_config.get(app.config['ENV'].lower())
    if additional:
        load_config_from_file(app, additional)

    if init_logging:
        logger.init_app(app)


def load_config_from_file(app, filepath):
    """Helper function to load config from a specified file"""
    try:
        app.config.from_pyfile(filepath)
        return True
    except OSError:
        app.logger.warning(
            "Did not find settings file %s for additional settings, skipping it",
            filepath,
        )
        return False
