0.3.7
-----

* Don't use declared_attr for the id, created_at and updated_at columns.

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
