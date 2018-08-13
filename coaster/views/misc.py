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
from werkzeug.urls import url_parse
from werkzeug.routing import RequestRedirect
from werkzeug.exceptions import HTTPException
from flask import session as request_session, request, url_for, json, Response, current_app
from flask.globals import _app_ctx_stack, _request_ctx_stack

__all__ = ['get_current_url', 'get_next_url', 'jsonp', 'endpoint_for']

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


# Adapted from https://stackoverflow.com/a/19637175
def endpoint_for(url, method=None, return_rule=False, follow_redirects=True, subdomains=True):
    """
    Given an absolute URL, retrieve the matching endpoint name (or rule).

    :param str method: HTTP method to use (defaults to GET)
    :param bool return_rule: Return the URL rule instead of the endpoint name
    :param bool follow_redirects: Follow redirects to final endpoint
    :return: Endpoint name or URL rule, or `None` if not found
    """
    appctx = _app_ctx_stack.top
    reqctx = _request_ctx_stack.top
    if appctx is None:
        raise RuntimeError("Application context is required but not present.")

    url_adapter = appctx.url_adapter
    if url_adapter is None and reqctx is not None:
        url_adapter = reqctx.url_adapter
    if url_adapter is None:
        raise RuntimeError("Application was not able to create a URL "
                           "adapter for request-independent URL matching. "
                           "You might be able to fix this by setting "
                           "the SERVER_NAME config variable.")

    def recursive_match(url):
        """
        Returns a match or None. If a redirect is encountered and must be followed,
        calls self with the new URL.
        """
        # We use Werkzeug's url_parse instead of Python's urlparse
        # because this is what Flask uses.
        parsed_url = url_parse(url)
        if not parsed_url.netloc:
            return
        if parsed_url.netloc != url_adapter.server_name and not (
                parsed_url.netloc.endswith('.' + url_adapter.server_name)):
            return

        try:
            endpoint_or_rule, view_args = url_adapter.match(parsed_url.path, method, return_rule=return_rule)
            return endpoint_or_rule
        except RequestRedirect as r:
            if follow_redirects:
                return recursive_match(r.new_url)
        except HTTPException as e:
            pass

    return recursive_match(url)
