# -*- coding: utf-8 -*-

"""
App management script
=====================

Coaster provides a Flask-Script-based manage.py with common management
functions. To use in your Flask app, create a ``manage.py`` with this
boilerplate::

    from coaster.manage import manager, init_manager
    from yourapp import app, db

    @manager.command
    def my_app_command()
        print "Hello!"

    if __name__ == "__main__":
        # If you have no custom commands, you can skip importing manager
        # and use the return value from init_manager
        manager = init_manager(app, db)
        manager.run()

To see all available commands::

    $ python manage.py --help
"""

from __future__ import absolute_import
from __future__ import print_function

from sys import stdout
import six
import flask
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from flask_script import Manager, prompt_bool, Shell
from flask_script.commands import Clean, ShowUrls
from flask_migrate import MigrateCommand


manager = Manager()


def alembic_table_metadata():
    db = manager.db
    metadata = db.MetaData(bind=db.engine)
    alembic_version = db.Table('alembic_version', metadata,
        db.Column('version_num', db.Unicode(32), nullable=False))
    return metadata, alembic_version


def set_alembic_revision(path=None):
    """Create/Update alembic table to latest revision number"""
    config = Config()
    try:
        config.set_main_option("script_location", path or "migrations")
        script = ScriptDirectory.from_config(config)
        head = script.get_current_head()
        # create alembic table
        metadata, alembic_version = alembic_table_metadata()
        metadata.create_all()
        item = manager.db.session.query(alembic_version).first()
        if item and item.version_num != head:
            item.version_num = head
        else:
            item = alembic_version.insert().values(version_num=head)
            item.compile()
            conn = manager.db.engine.connect()
            conn.execute(item)
        manager.db.session.commit()
        stdout.write("alembic head is set to %s \n" % head)
    except CommandError as e:
        stdout.write(e.message)


@manager.command
def dropdb():
    """Drop database tables"""
    manager.db.engine.echo = True
    if prompt_bool("Are you sure you want to lose all your data"):
        manager.db.drop_all()
        metadata, alembic_version = alembic_table_metadata()
        alembic_version.drop()
        manager.db.session.commit()


@manager.command
def createdb():
    """Create database tables from sqlalchemy models"""
    manager.db.engine.echo = True
    manager.db.create_all()
    set_alembic_revision()


@manager.command
def sync_resources():
    """Sync the client's resources with the Lastuser server"""
    print("Syncing resources with Lastuser...")
    resources = manager.app.lastuser.sync_resources()['results']

    for rname, resource in six.iteritems(resources):
        if resource['status'] == 'error':
            print("Error for %s: %s" % (rname, resource['error']))
        else:
            print("Resource %s %s..." % (rname, resource['status']))
            for aname, action in six.iteritems(resource['actions']):
                if action['status'] == 'error':
                    print("\tError for %s/%s: %s" % (rname, aname, action['error']))
                else:
                    print("\tAction %s/%s %s..." % (rname, aname, resource['status']))
    print("Resources synced...")


def shell_context():
    context = {'app': manager.app, 'db': manager.db, 'flask': flask}
    context.update(manager.context)
    return context


def init_manager(app, db, **kwargs):
    """
    Initialise Manager

    :param app: Flask app object
    :parm db: db instance
    :param kwargs: Additional keyword arguments to be made available as shell context
    """
    manager.app = app
    manager.db = db
    manager.context = kwargs
    manager.add_command('db', MigrateCommand)
    manager.add_command('clean', Clean())
    manager.add_command('showurls', ShowUrls())
    manager.add_command('shell', Shell(make_context=shell_context))
    manager.add_command('plainshell', Shell(make_context=shell_context,
        use_ipython=False, use_bpython=False))
    return manager
