# -*- coding: utf-8 -*-

"""
App configuration
=================
"""

from __future__ import absolute_import, print_function

from os import environ
import sys

from flask import Flask, g, get_flashed_messages, request, session, url_for

from jinja2.sandbox import SandboxedEnvironment as BaseSandboxedEnvironment

from . import logger
from .auth import current_auth
from .views import current_view

try:
    from flask.helpers import _tojson_filter
except ImportError:
    from flask.json import tojson_filter as _tojson_filter

__all__ = ['SandboxedFlask', 'init_app']

_additional_config = {
    'dev': 'development.py',
    'development': 'development.py',
    'test': 'testing.py',
    'testing': 'testing.py',
    'prod': 'production.py',
    'production': 'production.py',
}


class SandboxedEnvironment(BaseSandboxedEnvironment):
    """
    Works like a regular Jinja2 sandboxed environment but has some
    additional knowledge of how Flask's blueprint works, so that it can
    prepend the name of the blueprint to referenced templates if necessary.
    """

    def __init__(self, app, **options):
        if 'loader' not in options:
            options['loader'] = app.create_global_jinja_loader()
        BaseSandboxedEnvironment.__init__(self, **options)
        self.app = app


class SandboxedFlask(Flask):
    """
    Flask with a sandboxed_ Jinja2 environment, for when your app's templates
    need sandboxing. Useful when your app works with externally provided
    templates::

        from coaster.app import SandboxedFlask
        app = SandboxedFlask(__name__)

    .. _sandboxed: http://jinja.pocoo.org/docs/2.9/sandbox/
    """

    def create_jinja_environment(self):
        """Creates the Jinja2 environment based on :attr:`jinja_options`
        and :meth:`select_jinja_autoescape`.  Since 0.7 this also adds
        the Jinja2 globals and filters after initialization.  Override
        this function to customize the behavior.
        """
        options = dict(self.jinja_options)
        if 'autoescape' not in options:
            options['autoescape'] = self.select_jinja_autoescape
        rv = SandboxedEnvironment(self, **options)
        rv.globals.update(
            url_for=url_for,
            get_flashed_messages=get_flashed_messages,
            config=self.config,  # FIXME: Sandboxed templates shouldn't access full config
            # request, session and g are normally added with the
            # context processor for efficiency reasons but for imported
            # templates we also want the proxies in there.
            request=request,
            session=session,
            g=g,  # FIXME: Similarly with g: no access for sandboxed templates
        )
        rv.filters['tojson'] = _tojson_filter
        return rv


def init_app(app):
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
    # ref: https://flask.palletsprojects.com/en/1.1.x/config/#environment-and-debug-features
    env = app.config.get('ENV', 'production')
    additional = _additional_config.get(
        env.lower()
    )  # Lowercase because that's how we define it
    if additional:
        load_config_from_file(app, additional)

    logger.init_app(app)


def load_config_from_file(app, filepath):
    """Helper function to load config from a specified file"""
    try:
        app.config.from_pyfile(filepath)
        return True
    except IOError:
        # TODO: Can we print to sys.stderr in production? Should this go to
        # logs instead?
        print(
            "Did not find settings file {filepath} for additional settings, skipping it".format(
                filepath=filepath
            ),
            file=sys.stderr,
        )
        return False
