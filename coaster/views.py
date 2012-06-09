# -*- coding: utf-8 -*-

from __future__ import absolute_import
from functools import wraps
import urlparse
import re
from flask import request, url_for, json, Response, redirect
from werkzeug.routing import BuildError

__jsoncallback_re = re.compile(r'^[a-z$_][0-9a-z$_]*$', re.I)


def __index_url():
    try:
        return url_for('index')
    except BuildError:
        return '/'


#TODO: This needs tests
def get_next_url(referrer=False, external=False):
    """
    Get the next URL to redirect to. Don't return external URLs unless
    explicitly asked for. This is to protect the site from being an unwitting
    redirector to external URLs.
    """
    next_url = request.args.get('next', '')
    if not external:
        if next_url.startswith('http:') or next_url.startswith('https:') or next_url.startswith('//'):
            # Do the domains and ports match?
            pnext = urlparse.urlsplit(next_url)
            preq = urlparse.urlsplit(request.url)
            if pnext.hostname != preq.hostname or pnext.port != preq.port:
                next_url = ''
    if referrer:
        return next_url or request.referrer or __index_url()
    else:
        return next_url or __index_url()


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


def load_model(model, attributes=None, parameter=None, workflow=False, kwargs=False):
    """
    Decorator to load a model given a parameter. load_model recognizes
    queries to url_name of BaseIdNameMixin instances and will automatically
    load the model. FIXME: This should be handled by the model, not here.

    If workflow is True, workflow() for the last time in the chain is called and the
    resulting workflow object is passed instead of any of the requested parameters.

    If kwargs is True, the request parameters are passed as a 'kwargs' parameter.
    """
    if isinstance(model, (list, tuple)):
        chain = model
    else:
        if attributes is None or parameter is None:
            raise ValueError('attributes and parameter are needed to load a model.')
        chain = [[model, attributes, parameter]]

    def inner(f):
        @wraps(f)
        def decorated_function(**kw):
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
                        if request.method == 'GET':
                            url_check = True
                        query = query.filter_by(**{model.url_id_attr: parts[0]})
                    else:
                        query = query.filter_by(**{k: result.get(v, kw.get(v))})
                item = query.first_or_404()
                if url_check:
                    if item.url_name != url_name:
                        # The url_name doesn't match.
                        # Redirect browser to same page with correct url_name.
                        view_args = dict(request.view_args)
                        view_args[url_key] = item.url_name
                        return redirect(url_for(request.endpoint, **view_args), code=302)
                result[parameter] = item
            if workflow:
                # Get workflow for the last item in the chain
                wf = item.workflow()
                if kwargs:
                    return f(wf, kwargs=kw)
                else:
                    return f(wf)
            else:
                if kwargs:
                    return f(kwargs=kw, **result)
                else:
                    return f(**result)
        return decorated_function
    return inner


def load_models(*args, **kwargs):
    return load_model(args, workflow=kwargs.get('workflow', False), kwargs=kwargs.get('kwargs', False))
