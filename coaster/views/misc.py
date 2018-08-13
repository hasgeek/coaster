# -*- coding: utf-8 -*-

"""
Miscellaneous view helpers
--------------------------

Helper functions for view handlers.

All items in this module can be imported directly from :mod:`coaster.views`.
"""

from __future__ import absolute_import
import re
from six.moves.urllib.parse import urlsplit
from flask import session as request_session, request, url_for, json, Response, current_app

__all__ = ['get_current_url', 'get_next_url', 'jsonp']

__jsoncallback_re = re.compile(r'^[a-z$_][0-9a-z$_]*$', re.I)


def __index_url():
    if request:
        return request.script_root or '/'
    else:
        return '/'


def __clean_external_url(url):
    if url.startswith(('http://', 'https://', '//')):
        # Do the domains and ports match?
        pnext = urlsplit(url)
        preq = urlsplit(request.url)
        if pnext.port != preq.port:
            return ''
        if not (pnext.hostname == preq.hostname or pnext.hostname.endswith('.' + preq.hostname)):
            return ''
    return url


def get_current_url():
    """
    Return the current URL including the query string as a relative path. If the app uses subdomains,
    return an absolute path
    """
    if current_app.config.get('SERVER_NAME') and (
            # Check current hostname against server name, ignoring port numbers, if any (split on ':')
            request.environ['HTTP_HOST'].split(':', 1)[0] != current_app.config['SERVER_NAME'].split(':', 1)[0]):
        return request.url

    url = url_for(request.endpoint, **request.view_args)
    query = request.query_string
    if query:
        return url + '?' + query.decode()
    else:
        return url


__marker = []


def get_next_url(referrer=False, external=False, session=False, default=__marker):
    """
    Get the next URL to redirect to. Don't return external URLs unless
    explicitly asked for. This is to protect the site from being an unwitting
    redirector to external URLs. Subdomains are okay, however.

    This function looks for a ``next`` parameter in the request or in the session
    (depending on whether parameter ``session`` is True). If no ``next`` is present,
    it checks the referrer (if enabled), and finally returns either the provided
    default (which can be any value including ``None``) or the script root
    (typically ``/``).
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


def jsonp(*args, **kw):
    """
    Returns a JSON response with a callback wrapper, if asked for.
    Consider using CORS instead, as JSONP makes the client app insecure.
    See the :func:`~coaster.views.decorators.cors` decorator.
    """
    data = json.dumps(dict(*args, **kw), indent=2)
    callback = request.args.get('callback', request.args.get('jsonp'))
    if callback and __jsoncallback_re.search(callback) is not None:
        data = callback + u'(' + data + u');'
        mimetype = 'application/javascript'
    else:
        mimetype = 'application/json'
    return Response(data, mimetype=mimetype)
