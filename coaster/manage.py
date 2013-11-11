# -*- coding: utf-8 -*-

from sys import stdout

import flask
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from flask.ext.script import Manager, prompt_bool, Shell
from flask.ext.script.commands import Clean, ShowUrls
from flask.ext.alembic import ManageMigrations


manager = Manager()
database = Manager(usage="Perform database operations")


def alembic_table_metadata():
    db = manager.db
    metadata = db.MetaData(bind=db.engine)
    alembic_version = db.Table('alembic_version', metadata,
        db.Column('version_num', db.Unicode(32), nullable=False))
    return metadata, alembic_version


class InitedMigrations(ManageMigrations):
    def run(self, args):
        if len(args) and not args[0].startswith('-'):
            manager.init_for(args[0])
        super(InitedMigrations, self).run(args[1:])


@manager.option('-p', '--path', default='alembic', help="Alembic path [default 'alembic']")
def set_alembic_revision(path=None):
    """Create/Update alembic table to latest revision number
    """
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
    "Drops database tables"
    manager.init_for(env)
    manager.db.engine.echo = True
    if prompt_bool("Are you sure you want to lose all your data?"):
        manager.db.drop_all()


@database.option('-e', '--env', default='dev', help="runtime environment [default 'dev']")
def create(env):
    "Creates database tables from sqlalchemy models"
    manager.init_for(env)
    manager.db.engine.echo = True
    manager.db.create_all()
    set_alembic_revision()


@manager.option('-e', '--env', default='dev', help="runtime environment [default 'dev']")
def sync_resources(env):
    "Syncs resources for the client on Lastuser server"
    manager.init_for(env)
    print "Syncing resources with Lastuser..."
    result = manager.app.lastuser.sync_resources()
    if 'error' in result:
        print "Error: " + result['error']
    else:
        print "Resources synced."

@manager.shell
def _make_context():
    manager.init_for('prod')
    return dict(app=manager.app, db=manager.db, init_for=manager.init_for, flask=flask)


def init_manager(app, db, init_for, **kwargs):
    """Initialise Manager

    :param app: Flask app object
    :parm db: db instance
    :param init_for: init_for function which is normally present in __init__.py of hgapp.
    """
    manager.app, manager.db, manager.init_for = app, db, init_for
    manager.add_command("db", database)
    manager.add_command("clean", Clean())
    manager.add_command("showurls", ShowUrls())
    manager.add_command("migrate", InitedMigrations())
    manager.add_command("shell", Shell(make_context=_make_context))
    return manager
