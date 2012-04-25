# -*- coding: utf-8 -*-

from __future__ import absolute_import
from functools import wraps
import urlparse
import re
from flask import request, url_for, json, Response

__jsoncallback_re = re.compile(r'^[a-z$_][0-9a-z$_]*$', re.I)


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
            # Do the domains match?
            if urlparse.urlsplit(next_url).hostname != urlparse.urlsplit(request.url).hostname:
                next_url = ''
    if referrer:
        return next_url or request.referrer or url_for('index')
    else:
        return next_url or url_for('index')


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


def load_model(model, attributes=None, parameter=None, workflow=False):
    """
    Decorator to load a model given a parameter.
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
                for k, v in attributes.items():
                    query = query.filter_by(**{k: result.get(v, kw.get(v))})
                item = query.first_or_404()
                result[parameter] = item
            if workflow:
                # Get workflow for the last item in the chain
                wf = item.workflow()
                return f(wf)
            else:
                return f(**result)
        return decorated_function
    return inner


def load_models(workflow=False, *args):
    return load_model(args, workflow=workflow)
