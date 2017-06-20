# -*- coding: utf-8 -*-

from __future__ import absolute_import
from functools import wraps
import urlparse
import re
from flask import (session as request_session, request, url_for, json, Response,
    redirect, abort, g, current_app, render_template, jsonify)
from werkzeug.routing import BuildError
from werkzeug.datastructures import Headers
from werkzeug.exceptions import BadRequest
from werkzeug.wrappers import Response as WerkzeugResponse

__jsoncallback_re = re.compile(r'^[a-z$_][0-9a-z$_]*$', re.I)


def __index_url():
    try:
        return url_for('index')
    except BuildError:
        if request:
            return request.script_root
        else:
            return '/'


def __clean_external_url(url):
    if url.startswith('http://') or url.startswith('https://') or url.startswith('//'):
        # Do the domains and ports match?
        pnext = urlparse.urlsplit(url)
        preq = urlparse.urlsplit(request.url)
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
    query = request.environ.get('QUERY_STRING')
    if query:
        return url + '?' + query
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


def jsonp(*args, **kw):
    """
    Returns a JSON response with a callback wrapper, if asked for.
    """
    data = json.dumps(dict(*args, **kw),
        indent=None if request.is_xhr else 2)
    callback = request.args.get('callback', request.args.get('jsonp'))
    if callback and __jsoncallback_re.search(callback) is not None:
        data = callback + u'(' + data + u');'
        mimetype = 'application/javascript'
    else:
        mimetype = 'application/json'
    return Response(data, mimetype=mimetype)


class RequestTypeError(BadRequest, TypeError):
    """Exception that combines TypeError with BadRequest. Used by :func:`requestargs`."""
    pass


class RequestValueError(BadRequest, ValueError):
    """Exception that combines ValueError with BadRequest. Used by :func:`requestargs`."""
    pass


def requestargs(*vars):
    """
    Decorator that loads parameters from request.values if not specified in the
    function's keyword arguments. Usage::

        @requestargs('param1', ('param2', int), 'param3[]', ...)
        def function(param1, param2=0, param3=None):
            ...

    requestargs takes a list of parameters to pass to the wrapped function, with
    an optional filter (useful to convert incoming string request data into integers
    and other common types). If a required parameter is missing and your function does
    not specify a default value, Python will raise TypeError. requestargs recasts this
    as :exc:`RequestTypeError`, which returns HTTP 400 Bad Request.

    If the parameter name ends in ``[]``, requestargs will attempt to read a list from
    the incoming data. Filters are applied to each member of the list, not to the whole
    list.

    If the filter raises a ValueError, this is recast as a :exc:`RequestValueError`,
    which also returns HTTP 400 Bad Request.

    Tests::

        >>> from flask import Flask
        >>> app = Flask(__name__)
        >>>
        >>> @requestargs('p1', ('p2', int), ('p3[]', int))
        ... def f(p1, p2=None, p3=None):
        ...     return p1, p2, p3
        ...
        >>> f(p1=1)
        (1, None, None)
        >>> f(p1=1, p2=2)
        (1, 2, None)
        >>> f(p1='a', p2='b')
        ('a', 'b', None)
        >>> with app.test_request_context('/?p2=2'):
        ...     f(p1='1')
        ...
        ('1', 2, None)
        >>> with app.test_request_context('/?p3=1&p3=2'):
        ...     f(p1='1', p2='2')
        ...
        ('1', '2', [1, 2])
    """
    def inner(f):
        namefilt = [(name[:-2], filt, True) if name.endswith('[]') else (name, filt, False)
            for name, filt in
                [(v[0], v[1]) if isinstance(v, (list, tuple)) else (v, None) for v in vars]]

        @wraps(f)
        def decorated_function(**kw):
            for name, filt, is_list in namefilt:
                if name not in kw:
                    if request and name in request.values:
                        if filt is None:
                            if is_list:
                                kw[name] = request.values.getlist(name)
                            else:
                                kw[name] = request.values[name]
                        else:
                            try:
                                if is_list:
                                    kw[name] = [filt(v) for v in request.values.getlist(name)]
                                else:
                                    kw[name] = filt(request.values[name])
                            except ValueError, e:
                                raise RequestValueError(e)
            try:
                return f(**kw)
            except TypeError, e:
                raise RequestTypeError(e)
        return decorated_function
    return inner


def load_model(model, attributes=None, parameter=None,
        workflow=False, kwargs=False, permission=None, addlperms=None, urlcheck=[]):
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

    ``load_model`` aborts with a 404 if no instance is found.

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

    :param list urlcheck: If an attribute in this list has been used to load an object, but
        the value of the attribute in the loaded object does not match the request argument,
        issue a redirect to the corrected URL. This is useful for attributes like
        ``url_id_name`` and ``url_name_suuid`` where the ``name`` component may change
    """
    return load_models((model, attributes, parameter),
        workflow=workflow, kwargs=kwargs, permission=permission, addlperms=addlperms, urlcheck=urlcheck)


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
        by earlier instances. As an example, if a URL represents a hierarchy such as
        ``/<page>/<comment>``, the ``page`` can assign ``edit`` and ``delete`` permissions,
        while the ``comment`` can revoke ``edit`` and retain ``delete`` if the current user
        owns the page but not the comment

    In the following example, load_models loads a Folder with a name matching the name in the
    URL, then loads a Page with a matching name and with the just-loaded Folder as parent.
    If the Page provides a 'view' permission to the current user (`g.user`), the decorated
    function is called::

        @app.route('/<folder_name>/<page_name>')
        @load_models(
            (Folder, {'name': 'folder_name'}, 'folder'),
            (Page, {'name': 'page_name', 'parent': 'folder'}, 'page'),
            permission='view')
        def show_page(folder, page):
            return render_template('page.html', folder=folder, page=page)
    """
    def inner(f):
        @wraps(f)
        def decorated_function(**kw):
            permissions = None
            permission_required = kwargs.get('permission')
            url_check_attributes = kwargs.get('urlcheck', [])
            if isinstance(permission_required, basestring):
                permission_required = set([permission_required])
            elif permission_required is not None:
                permission_required = set(permission_required)
            result = {}
            for models, attributes, parameter in chain:
                if not isinstance(models, (list, tuple)):
                    models = (models,)
                item = None
                for model in models:
                    query = model.query
                    url_check = False
                    url_check_paramvalues = {}
                    for k, v in attributes.items():
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
                        if k in url_check_attributes:
                            url_check = True
                            url_check_paramvalues[k] = (v, val)
                    item = query.first()
                    if item is not None:
                        # We found it, so don't look in additional models
                        break
                if item is None:
                    abort(404)

                if hasattr(item, 'redirect_view_args'):
                    # This item is a redirect object. Redirect to destination
                    view_args = dict(request.view_args)
                    view_args.update(item.redirect_view_args())
                    return redirect(url_for(request.endpoint, **view_args), code=302)

                if permission_required:
                    permissions = item.permissions(g.user, inherited=permissions)
                    addlperms = kwargs.get('addlperms') or []
                    if callable(addlperms):
                        addlperms = addlperms() or []
                    permissions.update(addlperms)
                if g:
                    g.permissions = permissions
                if url_check:
                    url_redirect = False
                    view_args = None
                    for k, v in url_check_paramvalues.items():
                        uparam, uvalue = v
                        if getattr(item, k) != uvalue:
                            url_redirect = True
                            if view_args is None:
                                view_args = dict(request.view_args)
                            view_args[uparam] = getattr(item, k)
                    if url_redirect:
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


__render_with_jsonp = jsonp  # So we can take a jsonp parameter in render_with


def _best_mimetype_match(available_list, accept_mimetypes, default=None):
    for use_mimetype, quality in accept_mimetypes:
        for mimetype in available_list:
            if use_mimetype.lower() == mimetype.lower():
                return use_mimetype
    return default


def render_with(template, json=False, jsonp=False):
    """
    Decorator to render the wrapped method with the given template (or dictionary
    of mimetype keys to templates, where the template is a string name of a template
    file or a callable that returns a Response). The method's return value must be
    a dictionary and is passed to the template as parameters. Callable templates get
    a single parameter with the method's return value. Usage::

        @app.route('/myview')
        @render_with('myview.html')
        def myview():
            return {'data': 'value'}

        @app.route('/myview_with_json')
        @render_with('myview.html', json=True)
        def myview_no_json():
            return {'data': 'value'}

        @app.route('/otherview')
        @render_with({
            'text/html': 'otherview.html',
            'text/xml': 'otherview.xml'})
        def otherview():
            return {'data': 'value'}

        @app.route('/404view')
        @render_with('myview.html')
        def myview():
            return {'error': '404 Not Found'}, 404

        @app.route('/headerview')
        @render_with('myview.html')
        def myview():
            return {'data': 'value'}, 200, {'X-Header': 'Header value'}

    When a mimetype is specified and the template is not a callable, the response is
    returned with the same mimetype. Callable templates must return Response objects
    to ensure the correct mimetype is set.

    If a dictionary of templates is provided and does not include a handler for ``*/*``,
    render_with will attempt to use the handler for (in order) ``text/html``, ``text/plain``
    and the various JSON types, falling back to rendering the value into a unicode string.

    If the method is called outside a request context, the wrapped method's original
    return value is returned. This is meant to facilitate testing and should not be
    used to call the method from within another view handler as the presence of a
    request context will trigger template rendering.

    Rendering may also be suspended by calling the view handler with ``_render=False``.

    render_with provides JSON and JSONP handlers for the ``application/json``,
    ``text/json`` and ``text/x-json`` mimetypes if ``json`` or ``jsonp`` is True
    (default is False).

    :param template: Single template, or dictionary of MIME type to templates. If the
        template is a callable, it is called with the output of the wrapped function
    :param json: Helper to add a JSON handler (default is False)
    :param jsonp: Helper to add a JSONP handler (if True, also provides JSON, default is False)
    """
    if jsonp:
        templates = {
            'application/json': __render_with_jsonp,
            'text/json': __render_with_jsonp,
            'text/x-json': __render_with_jsonp,
            }
    elif json:
        templates = {
            'application/json': jsonify,
            'text/json': jsonify,
            'text/x-json': jsonify,
            }
    else:
        templates = {}
    if isinstance(template, basestring):
        templates['text/html'] = template
    elif isinstance(template, dict):
        templates.update(template)
    else:  # pragma: no cover
        raise ValueError("Expected string or dict for template")

    default_mimetype = '*/*'
    if '*/*' not in templates:
        templates['*/*'] = unicode
        default_mimetype = 'text/plain'
        for mimetype in ('text/html', 'text/plain', 'application/json', 'text/json', 'text/x-json'):
            if mimetype in templates:
                templates['*/*'] = templates[mimetype]
                default_mimetype = mimetype  # Remember which mimetype's handler is serving for */*
                break

    template_mimetypes = templates.keys()
    template_mimetypes.remove('*/*')  # */* messes up matching, so supply it only as last resort

    def inner(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Check if we need to bypass rendering
            render = kwargs.pop('_render', True)

            # Get the result
            result = f(*args, **kwargs)

            # Is the result a Response object? Don't attempt rendering
            if isinstance(result, (Response, WerkzeugResponse, current_app.response_class)):
                return result

            # Did the result include status code and headers?
            if isinstance(result, tuple):
                resultset = result
                result = resultset[0]
                if len(resultset) > 1:
                    status_code = resultset[1]
                else:
                    status_code = None
                if len(resultset) > 2:
                    headers = Headers(resultset[2])
                else:
                    headers = Headers()
            else:
                status_code = None
                headers = Headers()

            if len(templates) > 1:  # If we have more than one template handler
                if 'Vary' in headers:
                    vary_values = [item.strip() for item in headers['Vary'].split(',')]
                    if 'Accept' not in vary_values:
                        vary_values.append('Accept')
                    headers['Vary'] = ', '.join(vary_values)
                else:
                    headers['Vary'] = 'Accept'

            # Find a matching mimetype between Accept headers and available templates
            use_mimetype = None
            if render and request:
                # We do not use request.accept_mimetypes.best_match because it turns out to
                # be buggy: it returns the least match instead of the best match.
                # use_mimetype = request.accept_mimetypes.best_match(template_mimetypes, '*/*')
                use_mimetype = _best_mimetype_match(template_mimetypes, request.accept_mimetypes, '*/*')

            # Now render the result with the template for the mimetype
            if use_mimetype is not None:
                if callable(templates[use_mimetype]):
                    rendered = templates[use_mimetype](result)
                    if isinstance(rendered, Response):
                        if status_code is not None:
                            rendered.status_code = status_code
                        if headers is not None:
                            rendered.headers.extend(headers)
                    else:
                        rendered = current_app.response_class(
                            rendered,
                            status=status_code,
                            headers=headers,
                            mimetype=default_mimetype if use_mimetype == '*/*' else use_mimetype)
                else:  # Not a callable mimetype. Render as a jinja2 template
                    rendered = current_app.response_class(
                        render_template(templates[use_mimetype], **result),
                        status=status_code or 200, headers=headers,
                        mimetype=default_mimetype if use_mimetype == '*/*' else use_mimetype)
                return rendered
            else:
                return result
        return decorated_function
    return inner
