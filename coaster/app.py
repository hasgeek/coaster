# -*- coding: utf-8 -*-

from os import environ
import sys
from warnings import warn
import coaster.logging


_additional_config = {
    'dev': 'development.py',
    'development': 'development.py',
    'test': 'testing.py',
    'testing': 'testing.py',
    'prod': 'production.py',
    'production': 'production.py',
    }


def configure(app, env):
    """
    Configure an app depending on the environment.
    """
    warn("This function is deprecated. Please use init_app function", DeprecationWarning)
    init_app(app, environ.get(env))


def init_app(app, env):
    """
    Configure an app depending on the environment.
    """
    load_config_from_file(app, 'settings.py')

    additional = _additional_config.get(env)
    if additional:
        load_config_from_file(app, additional)

    coaster.logging.configure(app)


def load_config_from_file(app, filepath):
    try:
        app.config.from_pyfile(filepath)
    except IOError:
        # TODO: Can we print to sys.stderr in production? Should this go to
        # logs instead?
        print >> sys.stderr, "Did not find settings file %s" % filepath
