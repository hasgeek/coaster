# -*- coding: utf-8 -*-

from os import environ
import sys


def configure(app, env):
    """
    Configure an app depending on the environment.
    """
    try:
        app.config.from_pyfile('settings.py')
    except IOError:
        # FIXME: Can we print to sys.stderr in production? Should this go to
        # logs instead?
        print >> sys.stderr, ("Please create a settings.py file in the instance "
                             "folder by customizing settings-sample.py")

    additional = {
        'dev': 'development.py',
        'development': 'development.py',
        'test': 'testing.py',
        'testing': 'testing.py',
        'prod': 'production.py',
        'production': 'production.py',
    }.get(environ.get(env))

    if additional:
        try:
            app.config.from_pyfile(additional)
        except IOError:
            print >> sys.stderr, "Unable to locate additional settings file %s" % additional
