# -*- coding: utf-8 -*-

from __future__ import absolute_import
from functools import wraps
import urlparse
import re
from flask import session as request_session, request, url_for, json, Response, redirect, abort, g
from werkzeug.routing import BuildError
from sqlalchemy.orm.exc import NoResultFound

__jsoncallback_re = re.compile(r'^[a-z$_][0-9a-z$_]*$', re.I)


def __index_url():
    try:
        return url_for('index')
    except BuildError:
        return '/'


def __clean_external_url(url):
    if url.startswith('http:') or url.startswith('https:') or url.startswith('//'):
        # Do the domains and ports match?
        pnext = urlparse.urlsplit(url)
        preq = urlparse.urlsplit(request.url)
        if pnext.hostname != preq.hostname or pnext.port != preq.port:
            return ''
    return url


#TODO: This needs tests
def get_current_url():
    """
    Return the current URL including the query string as a relative path.
    """
    url = url_for(request.endpoint, **request.view_args)
    query = request.environ.get('QUERY_STRING')
    if query:
        return url + '?' + query
    else:
        return url


__marker = []


#TODO: This needs tests
def get_next_url(referrer=False, external=False, session=False, default=__marker):
    """
    Get the next URL to redirect to. Don't return external URLs unless
    explicitly asked for. This is to protect the site from being an unwitting
    redirector to external URLs.

    This function looks for a ``next`` parameter in the request or in the session
    (depending on whether parameter ``session`` is True). If no ``next`` is present,
    it checks the referrer (if enabled), and finally returns either the provided
    default (which can be any value including ``None``) or ``url_for('index')``.
    If your app does not have a URL endpoint named ``index``, ``/`` is returned.
    """
    if session:
        next_url = request_session.pop('next', None) or request.args.get('next', '')
    else:
        next_url = request.args.get('next', '')
    if next_url and not external:
        next_url = __clean_external_url(next_url)
    if next_url:
        return next_url

    if default is __marker:
        usedefault = False
    else:
        usedefault = True

    if referrer and request.referrer:
        if external:
            return request.referrer
        else:
            return __clean_external_url(request.referrer) or (default if usedefault else __index_url())
    else:
        return (default if usedefault else __index_url())


#TODO: This needs tests
def jsonp(*args, **kw):
    """
    Returns a JSON response with a callback wrapper, if asked for.
    """
    data = json.dumps(dict(*args, **kw),
        indent=None if request.is_xhr else 2)
    callback = request.args.get('callback', request.args.get('jsonp'))
    if callback and __jsoncallback_re.search(callback) is not None:
        data = u'%s(' % callback + data + u');'
        mimetype = 'application/javascript'
    else:
        mimetype = 'application/json'
    return Response(data, mimetype=mimetype)


def requestargs(*vars):
    """
    Decorator that loads parameters from request.args if not specified in the function's keyword arguments.
    """
    def inner(f):
        @wraps(f)
        def decorated_function(**kw):
            for arg in vars:
                if isinstance(arg, (list, tuple)):
                    name = arg[0]
                    filt = arg[1]
                    if len(arg) == 3:
                        has_default = True
                        default = arg[3]
                    else:
                        has_default = False
                        default = None
                else:
                    name = arg
                    filt = None
                    has_default = False
                    default = None

                if name not in kw:
                    if name not in request.args:
                        if has_default:
                            kw[name] = default
                        else:
                            abort(400)
                    else:
                        if filt is None:
                            kw[name] = request.args[name]
                        else:
                            kw[name] = filt(request.args[name])
            return f(**kw)
        return decorated_function
    return inner


def load_model(model, attributes=None, parameter=None,
        workflow=False, kwargs=False, permission=None, addlperms=None):
    """
    Decorator to load a model given a query parameter.

    Typical usage::

        @app.route('/<profile>')
        @load_model(Profile, {'name': 'profile'}, 'profileob')
        def profile_view(profileob):
            # 'profileob' is now a Profile model instance. The load_model decorator replaced this:
            # profileob = Profile.query.filter_by(name=profile).first_or_404()
            return "Hello, %s" % profileob.name

    Using the same name for request and parameter makes code easier to understand::

        @app.route('/<profile>')
        @load_model(Profile, {'name': 'profile'}, 'profile')
        def profile_view(profile):
            return "Hello, %s" % profile.name

    ``load_model`` aborts with a 404 if no instance is found. ``load_model`` also
    recognizes queries to ``url_name`` of :class:`~coaster.sqlalchemy.BaseIdNameMixin`
    instances and will automatically load the model. TODO: that should be handled by
    the model, not here.

    :param model: The SQLAlchemy model to query. Must contain a ``query`` object
        (which is the default with Flask-SQLAlchemy)

    :param attributes: A dict of attributes (from the URL request) that will be
        used to query for the object. For each key:value pair, the key is the name of
        the column on the model and the value is the name of the request parameter that
        contains the data

    :param parameter: The name of the parameter to the decorated function via which
        the result is passed. Usually the same as the attribute. If the parameter name
        is prefixed with 'g.', the parameter is also made available as g.<parameter>

    :param workflow: If True, the method ``workflow()`` of the instance is
        called and the resulting workflow object is passed to the decorated
        function instead of the instance itself

    :param kwargs: If True, the original request parameters are passed to the decorated
        function as a ``kwargs`` parameter

    :param permission: If present, ``load_model`` calls the
        :meth:`~coaster.sqlalchemy.PermissionMixin.permissions` method of the
        retrieved object with ``g.user`` as a parameter. If ``permission`` is not
        present in the result, ``load_model`` aborts with a 403. ``g`` is the Flask
        request context object and you are expected to setup a request environment
        in which ``g.user`` is the currently logged in user. Flask-Lastuser does this
        automatically for you. The permission may be a string or a list of strings,
        in which case access is allowed if any of the listed permissions are available

    :param addlperms: Iterable or callable that returns an iterable containing additional
        permissions available to the user, apart from those granted by the models. In an app
        that uses Lastuser for authentication, passing ``lastuser.permissions`` will pass
        through permissions granted via Lastuser
    """
    return load_models((model, attributes, parameter),
        workflow=workflow, kwargs=kwargs, permission=permission, addlperms=addlperms)


def load_models(*chain, **kwargs):
    """
    Decorator to load a chain of models from the given parameters. This works just like
    :func:`load_model` and accepts the same parameters, with some small differences.

    :param chain: The chain is a list of tuples of (``model``, ``attributes``, ``parameter``).
        Lists and tuples can be used interchangeably. All retrieved instances are passed as
        parameters to the decorated function

    :param workflow: Like with :func:`load_model`, ``workflow()`` is called on the last
        instance in the chain, and *only* the resulting workflow object is passed to the
        decorated function

    :param permission: Same as in :func:`load_model`, except
        :meth:`~coaster.sqlalchemy.PermissionMixin.permissions` is called on every instance
        in the chain and the retrieved permissions are passed as the second parameter to the
        next instance in the chain. This allows later instances to revoke permissions granted
        by earlier instances

    As an example, if a URL represents a hierarchy such as
    ``/<page>/<comment>``, the ``page`` can assign ``edit`` and ``delete`` permissions, while
    the ``comment`` can revoke ``edit`` and retain ``delete`` if the current user owns the page
    but not the comment.
    """
    def inner(f):
        @wraps(f)
        def decorated_function(**kw):
            permissions = None
            permission_required = kwargs.get('permission')
            if isinstance(permission_required, basestring):
                permission_required = set([permission_required])
            elif permission_required is not None:
                permission_required = set(permission_required)
            result = {}
            for model, attributes, parameter in chain:
                query = model.query
                url_check = False
                url_key = url_name = None
                for k, v in attributes.items():
                    if k == 'url_name' and hasattr(model, 'url_id_attr'):
                        url_key = v
                        url_name = kw.get(url_key)
                        parts = url_name.split('-')
                        try:
                            if request.method == 'GET':
                                url_check = True
                        except RuntimeError:
                            # We're not in a Flask request context, so there's no point
                            # trying to redirect to a correct URL
                            pass
                        try:
                            url_id = int(parts[0])
                        except ValueError:
                            abort(404)
                        query = query.filter_by(**{model.url_id_attr: url_id})
                    else:
                        if callable(v):
                            query = query.filter_by(**{k: v(result, kw)})
                        else:
                            if '.' in v:
                                first, attrs = v.split('.', 1)
                                val = result.get(first)
                                for attr in attrs.split('.'):
                                    val = getattr(val, attr)
                            else:
                                val = result.get(v, kw.get(v))
                            query = query.filter_by(**{k: val})
                try:
                    item = query.one()
                except NoResultFound:
                    abort(404)
                if permission_required:
                    permissions = item.permissions(g.user, inherited=permissions)
                    addlperms = kwargs.get('addlperms', [])
                    if callable(addlperms):
                        addlperms = addlperms()
                    permissions.update(addlperms)
                try:
                    g.permissions = permissions
                except RuntimeError:
                    pass
                if url_check:
                    if item.url_name != url_name:
                        # The url_name doesn't match.
                        # Redirect browser to same page with correct url_name.
                        view_args = dict(request.view_args)
                        view_args[url_key] = item.url_name
                        return redirect(url_for(request.endpoint, **view_args), code=302)
                if parameter.startswith('g.'):
                    parameter = parameter[2:]
                    setattr(g, parameter, item)
                result[parameter] = item
            if kwargs.get('workflow'):
                # Get workflow for the last item in the chain
                wf = item.workflow()
                if permission_required and not (permission_required & permissions):
                    abort(403)
                if kwargs.get('kwargs'):
                    return f(wf, kwargs=kw)
                else:
                    return f(wf)
            else:
                if permission_required and not (permission_required & permissions):
                    abort(403)
                if kwargs.get('kwargs'):
                    return f(kwargs=kw, **result)
                else:
                    return f(**result)
        return decorated_function
    return inner
