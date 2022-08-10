"""
Miscellaneous view helpers
--------------------------

Helper functions for view handlers.

All items in this module can be imported directly from :mod:`coaster.views`.
"""

from urllib.parse import urlsplit
import asyncio
import re
import typing as t

from flask import Response, current_app, json, request
from flask import session as request_session
from flask import url_for
from werkzeug.exceptions import MethodNotAllowed, NotFound
from werkzeug.routing import RequestRedirect

try:
    from asgiref.sync import async_to_sync
except ImportError:  # pragma: no cover
    async_to_sync = None  # type: ignore[assignment, misc]

from .. import typing as tc  # pylint: disable=reimported

__all__ = ['get_current_url', 'get_next_url', 'jsonp', 'endpoint_for']

__jsoncallback_re = re.compile(r'^[a-z$_][0-9a-z$_]*$', re.I)


def _index_url():
    if request:
        return request.script_root or '/'
    return '/'


def _clean_external_url(
    url: str, allowed_schemes: t.Container[str] = ('http', 'https')
) -> str:
    """Allow external URLs if they match current request's hostname."""
    # Do the domains and ports match?
    pnext = urlsplit(url)
    preq = urlsplit(request.url)
    if pnext.scheme and pnext.scheme.lower() not in allowed_schemes:
        # Not an allowed scheme, quit
        return ''
    if pnext.port is not None and pnext.port != preq.port:
        # Port doesn't match, quit
        return ''
    if (
        pnext.hostname is not None
        and preq.hostname is not None
        and not (
            pnext.hostname == preq.hostname
            or pnext.hostname.endswith('.' + preq.hostname)
        )
    ):
        # Hostname is not same or subdomain, quit
        return ''
    # All tests passed, so return URL
    return url


def get_current_url() -> str:
    """
    Return the current URL including the query string as a relative path.

    If the app uses subdomains, return an absolute path.
    """
    if current_app.config.get('SERVER_NAME') and (
        # Check current hostname against server name, ignoring port numbers, if any
        # (split on ':')
        request.environ['HTTP_HOST'].split(':', 1)[0]
        != current_app.config['SERVER_NAME'].split(':', 1)[0]
    ):
        return request.url

    url = (
        url_for(request.endpoint, **request.view_args)
        if request.endpoint is not None  # Will be None in a 404 handler
        else request.url
    )
    query = request.query_string
    if query:
        return url + '?' + query.decode()
    return url


__marker = object()


def get_next_url(
    referrer=False, external=False, session=False, default=__marker
) -> str:
    """
    Get the next URL to redirect to.

    Don't return external URLs unless explicitly asked for. This is to protect the site
    from being an unwitting redirector to external URLs. Subdomains are okay, however.

    This function looks for a ``next`` parameter in the request or in the session
    (depending on whether parameter ``session`` is True). If no ``next`` is present, it
    checks the referrer (if enabled), and finally returns either the provided default
    (which can be any value including ``None``) or the script root (typically ``/``).
    """
    if session:
        next_url = request_session.pop('next', None) or request.args.get('next', '')
    else:
        next_url = request.args.get('next', '')
    if next_url and not external:
        next_url = _clean_external_url(next_url)
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
            return _clean_external_url(request.referrer) or (
                default if usedefault else _index_url()
            )
    else:
        return default if usedefault else _index_url()


def jsonp(*args, **kw):
    """
    Return a JSON response with a callback wrapper, if asked for.

    .. deprecated:: 0.7.0
        Switch to CORS as JSONP makes the client app insecure. See the
        :func:`~coaster.views.decorators.cors` decorator.
    """
    data = json.dumps(dict(*args, **kw), indent=2)
    callback = request.args.get('callback', request.args.get('jsonp'))
    if callback and __jsoncallback_re.search(callback) is not None:
        data = callback + '(' + data + ');'
        mimetype = 'application/javascript'
    else:
        mimetype = 'application/json'
    return Response(data, mimetype=mimetype)


def endpoint_for(
    url: str,
    method: t.Optional[str] = None,
    return_rule: bool = False,
    follow_redirects: bool = True,
) -> t.Tuple[t.Optional[str], t.Dict[str, t.Any]]:  # TODO: Union for rule in return
    """
    Retrieve endpoint or rule and view arguments given an absolute URL.

    Requires a current request context to determine runtime environment.

    :param str method: HTTP method to use (defaults to GET)
    :param bool return_rule: Return the URL rule instead of the endpoint name
    :param bool follow_redirects: Follow redirects to final endpoint
    :return: Tuple of endpoint name or URL rule or `None`, view arguments
    """
    parsed_url = urlsplit(url)
    if not parsed_url.netloc:
        # We require an absolute URL
        return None, {}

    # Take the current runtime environment...
    environ = dict(request.environ)
    # ...but replace the HTTP host with the URL's host...
    environ['HTTP_HOST'] = parsed_url.netloc
    # ...and the path with the URL's path (after discounting the app path, if not
    # hosted at root).
    environ['PATH_INFO'] = parsed_url.path[len(environ.get('SCRIPT_NAME', '')) :]
    # Create a new request with this environment...
    url_request = current_app.request_class(environ)
    # ...and a URL adapter with the new request.
    url_adapter = current_app.create_url_adapter(url_request)

    # Run three hostname tests, one of which must pass:

    # 1. Does the URL map have host matching enabled? If so, the URL adapter will
    # validate the hostname.
    if current_app.url_map.host_matching:
        pass

    # 2. If not, does the domain match? url_adapter.server_name will prefer
    # app.config['SERVER_NAME'], but if that is not specified, it will take it from the
    # environment.
    elif parsed_url.netloc == url_adapter.server_name:
        pass

    # 3. If subdomain matching is enabled, does the subdomain match?
    elif current_app.subdomain_matching and parsed_url.netloc.endswith(
        '.' + url_adapter.server_name
    ):
        pass

    # If no test passed, we don't have a matching endpoint.
    else:
        return None, {}

    # Now retrieve the endpoint or rule, watching for redirects or resolution failures
    try:
        return url_adapter.match(parsed_url.path, method, return_rule=return_rule)
    except RequestRedirect as r:
        # A redirect typically implies `/folder` -> `/folder/`
        # This will not be a redirect response from a view, since the view isn't being
        # called
        if follow_redirects:
            return endpoint_for(
                r.new_url,
                method=method,
                return_rule=return_rule,
                follow_redirects=follow_redirects,
            )
    except (NotFound, MethodNotAllowed):
        pass
    # If we got here, no endpoint was found.
    return None, {}


def ensure_sync(func: tc.WrappedFunc) -> tc.WrappedFunc:
    """Help use Flask's ensure_sync outside a request context."""
    if current_app:
        return current_app.ensure_sync(func)

    if not asyncio.iscoroutinefunction(func):
        return func

    if async_to_sync is not None:
        return async_to_sync(func)  # type: ignore[return-value]

    return lambda *args, **kwargs: (  # type: ignore[return-value,unreachable]
        asyncio.run(func(*args, **kwargs))
    )
