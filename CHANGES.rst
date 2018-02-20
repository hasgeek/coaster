0.6.1
-----

* Renamed ``coaster.roles.set_roles`` to ``with_roles`` and added support for
  wrapping ``declared_attr`` and column properties
* Restructured roles to match current understanding of principals, actors and
  anchors
* Added SQLAlchemy column annotations
* Reorganised ``coaster.utils`` and ``coaster.sqlalchemy`` into sub-packages
* ``LabeledEnum`` now supports grouped values if declared as a set
* New: ``coaster.sqlalchemy.StateManager`` adds state management to models
* Discontinued: ``coaster.utils.*`` is no longer available directly as
  ``coaster.*``
* Discontinued: ``coaster.views.load_models`` no longer accepts the
  ``workflow`` parameter
* New: ``requestquery`` and ``requestform`` to complement
  ``coaster.views.requestargs``
* New: ``coaster.auth`` module with a ``current_auth`` proxy that provides
  a standardised API for login managers to use
* New: ``is_collection`` util for testing if an item is a collection data type
* New: ``coaster.views.classview`` provides a new take on organising views
  into a class


0.6.0
-----

* Removed deprecated ``coaster.app.configure``
* ``coaster.app.init_app`` now takes an optional environment, reading from the
  ``FLASK_ENV`` environment variable and defaulting to ``DEVELOPMENT``. This
  reverses the change introduced in version 0.3.2
* ``coaster.manage`` no longer accepts environment or calls ``init_for``.
  Apps must do this themselves
* ``coaster.manage`` now exposes Alembic migrations via Flask-Migrate instead
  of Flask-Alembic
* When using UUID primary keys in ``IdMixin``, a UUID is automatically
  generated the first time the ``id`` column is accessed, without the need
  to commit to the database
* The underlying implementaiton, ``auto_init_default``, is also available
  for use on other models
* The ``url_id`` property is now part of ``IdMixin``  and supports SQL queries
  as well. This makes it compatible with the support for ``url_name`` in
  ``load_models``
* New: ``shortuuid`` module exposed via the ``utils`` module, with ``suuid``,
  ``suuid2uuid`` and ``uuid2suuid`` functions
* ``buid`` reverts to using UUID4 instead of UUID1mc
* The deprecated ``newid`` alias for ``buid`` has now been removed
* New: ``UuidMixin`` that adds a UUID secondary key and complements ``IdMixin``
* ``BaseIdNameMixin`` now implements ``url_id_name`` (previously ``url_name``)
  as a hybrid property and has an additional ``url_name_suuid`` property.
  ``BaseScopedIdNameMixin`` has an upgraded ``url_id_name`` as well
* ``load_models`` no longer hardcodes for ``url_name``, instead accepting an
  optional ``urlcheck`` list parameter
* Added Python 3.6 compatibility
* Removed the unused ``nullstr`` and renamed ``nullunicode`` to ``nullstr``
* New: ``add_primary_relationship`` to define a primary child on parent models
* Added ``NoIdMixin`` that is BaseMixin minus the id column
* New: ``require_one_of`` util for functions that require any one of many
  parameters

0.5.2
-----

* Removed ``add_and_commit`` and associated tests
* ``failsafe_add`` now takes filters optionally, failing silently in case of
  error
* Added Slack error logging and better throttling for Slack and SMS
* New util: ``isoweek_datetime`` for week-based datetimes in reports
* New util: ``midnight_to_utc`` for midnight in any timezone converted to UTC

0.5.1
-----

* New util: ``uuid1mc`` generates a UUID1 with a random multicast MAC id
* New util: ``uuid1mc_from_datetime`` generates a UUID1 with a specific
  timestamp
* IdMixin now supports UUID primary keys
* Deprecated ``add_and_commit`` in favour of ``failsafe_add``
* New utils: ``uuid2buid`` and ``buid2uuid``
* Removed ``timestamp_columns`` (was deprecated in 0.4.3)
* Replaced ``py-bcrypt`` dependency with ``bcrypt``
* ``buid`` now uses UUID1 with random multicast MAC addresses instead of UUID4
* New util: ``unicode_http_header`` converts ASCII HTTP header strings to
  Unicode
* Error traceback in ``coaster.logging`` now includes request context and
  session cookie
* New: ``func.utcnow`` for reliable UTC timestamps generated in the database
* TimestampMixin now uses ``func.utcnow`` to move datetime generation
  server-side

0.5.0
-----

* ``Base(Scoped)?(Id)?NameMixin`` now disallows blank names by default. Bumped
  version number since this is a non-breaking incompatible change
* ``JsonDict`` now uses ``JSONB`` on PostgreSQL 9.4
* New ``CoordinatesMixin`` adds latitude and longitude columns
* Rudimentary NLP methods
* ``LabeledEnum`` now has ``keys()`` and ``values()`` methods as well
* Move the query class to ``IdMixin`` and ``TimestampMixin`` as they are used
  independently of BaseMixin
* ``LabeledEnum`` now takes an ``__order__`` specification
* New ``word_count`` util returns word count for HTML documents
* New ``for_tsquery`` formats text queries to PostgreSQL to_tsquery parameters
* New ``get`` and ``upsert`` methods in ``Base(Scoped)NameMixin``
* ``render_with`` no longer enables JSON handler by default; now gracefully
  handles ``*/*`` requests
* ``manage.py``'s shell now allows additional context to be made available in
  ``locals()``
* ``coaster.db`` now provides a custom SQLAlchemy session with additional
  helper methods, starting with one: ``add_and_commit``, which rolls back if
  the commit fails
* Removed ``one_or_none`` in favor of SQLAlchemy's implementation of the same
  in 1.0.9
* New ``is_url_for`` decorator in UrlForMixin

0.4.3
-----

* Initial work on Fluentd logging
* New util: ``base_domain_matches`` compares if two domains have the same base
  domain
* ``utils.make_name`` now returns ASCII slugs instead of Unicode slugs
* New: ``domain_namespace_match`` function
* ``coaster.gfm.markdown`` now supports optional HTML markup
* Deprecated ``sqlalchemy.timestamp_columns``, introducing
  ``make_timestamp_columns``
* ``sorted_timezones`` now includes both country name and timezone name
* Base query now has a ``notempty()`` method that is more efficient than
  ``bool(count())``
* New util: ``deobfuscate_email`` deobfuscates common email obfuscation
  patterns

0.4.2
-----

* ``NameTitle`` namedtuple and support in ``LabeledEnum`` for
  ``(value, name, title)``
* Provide UglifyJS minifier to webassets via the UglipyJS wrapper
* ``BaseScopedNameMixin``'s ``make_title`` now uses ``short_title`` as source

0.4.1
-----

* ``views.get_next_url`` now considers subdomains as non-external
* ``sqlalchemy.BaseMixin`` now provides a new query class with ``one_or_none``
* Coaster now requires all dependencies used by submodules. They are no longer
  optional
* LabeledEnums now have a ``get()`` method to emulate dictionaries

0.4.0
-----

* Moved utility functions into ``coaster.utils``
* Bugfix: make ``get_email_domain`` somewhat more reliable
* Switched to using ``coaster.db`` in tests
* New: ``MarkdownColumn`` composite column for Markdown content
* Changed: ``JsonDict`` column will use PostgreSQL's native JSON type if
  the server is PostgreSQL >= 9.2
* ``TimestampMixin`` now uses ``datetime.utcnow`` instead of ``func.now``
  because the ``now()`` function in PostgreSQL returns local time with
  timezone, not UTC time, and discards the timezone component if the column
  doesn't store them. This made timestamps local, not in UTC unless the server
  was also in UTC
* Database tests are now run against both SQLite3 and PostgreSQL
* Bugfix: ``PermissionMixin`` was mutating inherited permissions
* Bugfix: ``render_with`` no longer attempts to render pre-rendered responses
* ``utils.make_name`` now takes caller-specified counter numbers
* ``sqlalchemy.BaseNameMixin`` and ``BaseScopedNameMixin.make_name`` now take a
  reserved names list
* New: ``utils.nullint``, ``nullstr`` and ``nullunicode`` for returning
  ``int(v)``, ``str(v)`` and ``unicode(v)`` if ``v`` isn't false

0.3.13
------

* ``short_title`` method in ``BaseScopedNameMixin``
* ``assets.require`` now raises ``AssetNotFound`` on missing assets
* New: ``coaster.db.db`` is an instance of Flask-SQLAlchemy

0.3.12
------

* Bugfix: Support single-char usernames
* New feature: Labeled enumerations
* Enhancement: ``load_models`` allows choice of permissions and takes
  additional permissions
* Rewrote ``requestargs`` view decorator for efficiency and ease of use
* New ``render_with`` view decorator
* New gfm module for GitHub Flavoured Markdown
* ``load_models`` now supports "redirect" models
* Logging now looks for ``MAIL_DEFAULT_SENDER`` before ``DEFAULT_MAIL_SENDER``
* Compatibility with Flask 0.10 for SandboxedFlask

0.3.11
------

* Bugfix: ``PermissionMixin.permissions()`` now checks if parent is not None

0.3.10
------

* New ``sorted_timezones`` function

0.3.9
-----

* New module for asset management, with testcases and documentation.
* ``coaster.logging.configure`` is now ``init_app`` in keeping with convention

0.3.8
-----

* Updated documentation
* New SQLAlchemy column types and helpers
* Use SQL expressions to set ``url_id`` in scoped id classes

0.3.7
-----

* Don't use ``declared_attr`` for the ``id``, ``created_at`` and ``updated_at``
  columns
* Rename ``newid`` to ``buid`` but retain old name for compatibility
* New ``requestargs`` view wrapper to make working with ``request.args``
  easier

0.3.6
-----

* New ``SandboxedFlask`` in ``coaster.app`` that uses Jinja's
  ``SandboxedEnvironment``

0.3.5
-----

* ``load_models`` now caches data to ``flask.g``
* SQLAlchemy models now use ``declared_attr`` for all columns to work around a
  column duplication bug with joined table inheritance in SQLAlchemy < 0.8
* Misc fixes

0.3.4
-----

* ``get_next_url`` now takes a default parameter. Pass ``default=None`` to
  return ``None`` if no suitable next URL can be found
* ``get_next_url`` no longer looks in the session by default. Pass
  ``session=True`` to look in the session. This was added since popping
  ``next`` from session modifies the session, which shouldn't happen in a
  ``get`` function
* ``load_models`` accepts ``g.<name>`` notation for parameters to indicate
  that the parameter should be available as ``g.<name>``. The view function
  will get called with just ``<name>`` as usual
* If the view requires permissions, ``load_models`` caches available
* permissions as ``g.permissions``

0.3.3
-----

* ``coaster.views.get_next_url`` now looks in the session for the next URL

0.3.2
-----

* New ``coaster.app.init_app`` function moves away from passing configuration
  status in environment variables

0.3.0
-----

* SQLAlchemy models now have a ``permissions`` method that ``load_models``
  looks up

0.2.2
-----

* Added logging module

0.1
---

* First version
