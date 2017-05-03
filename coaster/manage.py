# -*- coding: utf-8 -*-

from sys import stdout

import flask
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from flask_script import Manager, prompt_bool, Shell
from flask_script.commands import Clean, ShowUrls
from flask_alembic import ManageMigrations


manager = Manager()
database = Manager(usage="Perform database operations")


def alembic_table_metadata():
    db = manager.db
    metadata = db.MetaData(bind=db.engine)
    alembic_version = db.Table('alembic_version', metadata,
        db.Column('version_num', db.Unicode(32), nullable=False))
    return metadata, alembic_version


class InitedMigrations(ManageMigrations):
    """Perform Alembic database migration operations"""
    def run(self, args):
        if len(args) and not args[0].startswith('-'):
            manager.init_for(args[0])
        super(InitedMigrations, self).run(args[1:])


def set_alembic_revision(path=None):
    """Create/Update alembic table to latest revision number"""
    config = Config()
    try:
        config.set_main_option("script_location", path or "alembic")
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
    except CommandError, e:
        stdout.write(e.message)


@database.option('-e', '--env', default='dev', help="runtime environment [default 'dev']")
def drop(env):
    "Drop database tables"
    manager.init_for(env)
    manager.db.engine.echo = True
    if prompt_bool("Are you sure you want to lose all your data"):
        manager.db.drop_all()


@database.option('-e', '--env', default='dev', help="runtime environment [default 'dev']")
def create(env):
    "Create database tables from sqlalchemy models"
    manager.init_for(env)
    manager.db.engine.echo = True
    manager.db.create_all()
    set_alembic_revision()


@manager.option('-e', '--env', default='dev', help="runtime environment [default 'dev']")
def sync_resources(env):
    """Sync the client's resources with the Lastuser server"""
    manager.init_for(env)
    print "Syncing resources with Lastuser..."
    resources = manager.app.lastuser.sync_resources()['results']

    for rname, resource in resources.iteritems():
        if resource['status'] == 'error':
            print "Error for %s: %s" % (rname, resource['error'])
        else:
            print "Resource %s %s..." % (rname, resource['status'])
            for aname, action in resource['actions'].iteritems():
                if action['status'] == 'error':
                    print "\tError for %s/%s: %s" % (rname, aname, action['error'])
                else:
                    print "\tAction %s/%s %s..." % (rname, aname, resource['status'])
    print "Resources synced..."


@manager.option('-e', '--env', default='dev', help="shell environment [default 'dev']")
def shell(env, no_ipython=False, no_bpython=False):
    """Initiate a Python shell"""
    def _make_context():
        manager.init_for(env)
        context = dict(app=manager.app, db=manager.db, init_for=manager.init_for, flask=flask)
        context.update(manager.context)
        return context
    Shell(make_context=_make_context).run(no_ipython=no_ipython, no_bpython=no_bpython)


@manager.option('-e', '--env', default='dev', help="shell environment [default 'dev']")
def plainshell(env):
    """Initiate a plain Python shell"""
    return shell(env, no_ipython=True, no_bpython=True)


def init_manager(app, db, init_for, **kwargs):
    """
    Initialise Manager

    :param app: Flask app object
    :parm db: db instance
    :param init_for: init_for function which is normally present in __init__.py of hgapp
    :param kwargs: Additional keyword arguments to be made available as shell context
    """
    manager.app, manager.db, manager.init_for = app, db, init_for
    manager.context = kwargs
    manager.add_command("db", database)
    manager.add_command("clean", Clean())
    manager.add_command("showurls", ShowUrls())
    manager.add_command("migrate", InitedMigrations())
    return manager
