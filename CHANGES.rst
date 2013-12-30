0.4.0
-----

* Moved utility functions into coaster.utils.
* Bugfix: make get_email_domain somewhat more reliable.
* Switched to using coaster.db in tests.
* New: MarkdownColumn composite column for Markdown content.
* Changed: JsonDict column will use PostgreSQL's native JSON type if
  the server is PostgreSQL >= 9.2.
* TimestampMixin now uses datetime.utcnow instead of func.now because
  the now() function in PostgreSQL returns local time with timezone,
  not UTC time, and discards the timezone component if the column
  doesn't store them. This made timestamps local, not in UTC.
* Database tests are now run against both SQLite3 and PostgreSQL.
* Bugfix: PermissionMixin was mutating inherited permissions.
* Bugfix: render_with no longer attempts to render pre-rendered responses.
* utils.make_name now takes caller-specified counter numbers.
* sqlalchemy.BaseNameMixin and BaseScopedNameMixin.make_name now take a reserved names list.
* New: utils.nullint, nullstr and nullunicode for returning int(v), str(v) and unicode(v) if v isn't false.

0.3.13
------

* short_title method in BaseScopedNameMixin.
* assets.require now raises AssetNotFound on missing assets.
* New: coaster.db.db is an instance of Flask-SQLAlchemy.

0.3.12
------

* Bugfix: Support single-char usernames.
* New feature: Labeled enumerations.
* Enhancement: load_models allows choice of permissions and takes additional
  permissions.
* Rewrote requestargs view decorator for efficiency and ease of use.
* New render_with view decorator.
* New gfm module for GitHub Flavoured Markdown.
* load_models now supports "redirect" models.
* Logging now looks for MAIL_DEFAULT_SENDER before DEFAULT_MAIL_SENDER.
* Compatibility with Flask 0.10 for SandboxedFlask.

0.3.11
------

* Bugfix: PermissionMixin.permissions() now checks if parent is not None.

0.3.10
------

* New sorted_timezones function.

0.3.9
-----

* New module for asset management, with testcases and documentation.
* coaster.logging.configure is now init_app in keeping with convention.

0.3.8
-----

* Updated documentation.
* New SQLAlchemy column types and helpers.
* Use SQL expressions to set url_id in scoped id classes.

0.3.7
-----

* Don't use declared_attr for the id, created_at and updated_at columns.
* Rename newid to buid but retain old name for compatibility.
* New requestargs view wrapper to make working with request.args easier.

0.3.6
-----

* New SandboxedFlask in coaster.app that uses Jinja's SandboxedEnvironment.

0.3.5
-----

* load_models now caches data to flask.g
* SQLAlchemy models now use declared_attr for all columns to work around a
  column duplication bug with joined table inheritance in SQLAlchemy < 0.8.
* Misc fixes.

0.3.4
-----

* get_next_url now takes a default parameter. Pass default=None to return None
  if no suitable next URL can be found
* get_next_url no longer looks in the session by default. Pass session=True to
  look in the session. This was added since popping next from session modifies
  the session.
* load_models accepts 'g.<name>' notation for parameters to indicate that the
  parameter should be available as g.<name>. The view function will get called
  with just <name> as usual.
* If the view requires permissions, load_models caches available permissions
  as g.permissions.

0.3.3
-----

* coaster.views.get_next_url now looks in the session for the next URL.

0.3.2
-----

* New coaster.app.init_app function moves away from passing configuration status
  in environment variables.

0.3.0
-----

* SQLAlchemy models now have a ``permissions`` method that ``load_models``
  looks up.

0.2.2
-----

* Added logging module

0.1
---

* First version
