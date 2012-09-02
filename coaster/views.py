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


def load_model(model, attributes=None, parameter=None,
        workflow=False, kwargs=False, permission=None):
    """
    Decorator to load a model given a parameter. load_model recognizes
    queries to url_name of BaseIdNameMixin instances and will automatically
    load the model. TODO: This should be handled by the model, not here.

    If workflow is True, workflow() for the last time in the chain is called and the
    resulting workflow object is passed instead of any of the requested parameters.

    If kwargs is True, the request parameters are passed as a 'kwargs' parameter.
    """
    return load_models((model, attributes, parameter),
        workflow=workflow, kwargs=kwargs, permission=permission)


def load_models(*chain, **kwargs):
    """
    Decorator to load a chain of models from the given parameters. load_models
    recognizes queries to url_name of BaseIdNameMixin and BaseScopedIdNameMixin
    instances and will automatically load the model. TODO: This should be
    handled by the model, not here.

    If workflow is True, workflow() for the last time in the chain is called and the
    resulting workflow object is passed instead of any of the requested parameters.

    If kwargs is True, the request parameters are passed as a 'kwargs' parameter.
    """
    def inner(f):
        @wraps(f)
        def decorated_function(**kw):
            permissions = None
            permission_required = kwargs.get('permission')
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
                        query = query.filter_by(**{model.url_id_attr: parts[0]})
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
                if permission_required and permission_required not in permissions:
                    abort(403)
                if kwargs.get('kwargs'):
                    return f(wf, kwargs=kw)
                else:
                    return f(wf)
            else:
                if permission_required and permission_required not in permissions:
                    abort(403)
                if kwargs.get('kwargs'):
                    return f(kwargs=kw, **result)
                else:
                    return f(**result)
        return decorated_function
    return inner
