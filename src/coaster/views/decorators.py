"""
View decorators
---------------

Decorators for view handlers.

All items in this module can be imported directly from :mod:`coaster.views`.
"""

from functools import wraps
import typing as t

from flask import (
    Response,
    abort,
    current_app,
    g,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.datastructures import Headers
from werkzeug.exceptions import BadRequest
from werkzeug.wrappers import Response as WerkzeugResponse

import typing_extensions as te

from .. import typing as tc  # pylint: disable=reimported
from ..auth import add_auth_attribute, current_auth
from ..utils import is_collection
from .misc import ensure_sync, jsonp

__all__ = [
    'RequestTypeError',
    'RequestValueError',
    'requestargs',
    'requestquery',
    'requestform',
    'requestbody',
    'load_model',
    'load_models',
    'render_with',
    'cors',
    'requires_permission',
]


class RequestTypeError(BadRequest, TypeError):
    """Exception that combines TypeError with BadRequest."""


class RequestValueError(BadRequest, ValueError):
    """Exception that combines ValueError with BadRequest."""


def requestargs(
    *args: t.Union[str, t.Tuple[str, t.Callable[[str], t.Any]]],
    source: t.Union[
        te.Literal['values'],
        te.Literal['form'],
        te.Literal['query'],
        te.Literal['body'],
    ] = 'values',
):
    """
    Decorate a function to load parameters from the request if not supplied directly.

    Usage::

        @requestargs('param1', ('param2', int), 'param3[]', ...)
        def function(param1, param2=0, param3=None):
            ...

    :func:`requestargs` takes a list of parameters to pass to the wrapped function, with
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
        >>> with app.test_request_context('/?p2=100&p3=1&p3=2'):
        ...     f(p1='1', p2=200)
        ...
        ('1', 200, [1, 2])
    """

    def decorator(f: tc.WrappedFunc) -> tc.WrappedFunc:
        """Apply config to wrapped function."""
        namefilt: t.List[t.Tuple[str, t.Optional[t.Callable[[str], t.Any]], bool]] = [
            (name[:-2], filt, True) if name.endswith('[]') else (name, filt, False)
            for name, filt in [
                (a[0], a[1]) if isinstance(a, (list, tuple)) else (a, None)
                for a in args
            ]
        ]

        if source == 'query':

            def datasource() -> t.Tuple[t.Any, bool]:
                return (request.args, True) if request else ({}, False)

        elif source == 'form':

            def datasource() -> t.Tuple[t.Any, bool]:
                return (request.form, True) if request else ({}, False)

        elif source == 'body':

            def datasource() -> t.Tuple[t.Any, bool]:
                if not request:
                    return ({}, False)
                return (
                    (request.json, False) if request.is_json else (request.form, True)
                )

        elif source == 'values':

            def datasource() -> t.Tuple[t.Any, bool]:
                return (request.values, True) if request else ({}, False)

        else:
            raise TypeError("Unknown data source")

        @wraps(f)
        def wrapper(*args, **kw) -> t.Any:
            """Wrap a view to insert keyword arguments."""
            values, has_gettype = datasource()
            for name, filt, is_list in namefilt:
                # Process name if
                # (a) it's not in the function's parameters, and
                # (b) is in the form/query
                if name not in kw and name in values:
                    try:
                        if is_list:
                            if has_gettype:
                                kw[name] = values.getlist(name, type=filt)
                            else:
                                if filt:
                                    kw[name] = [filt(_v) for _v in values[name]]
                                else:
                                    kw[name] = values[name]
                        else:
                            if has_gettype:
                                kw[name] = values.get(name, type=filt)
                            else:
                                if filt:
                                    kw[name] = filt(values[name])
                                else:
                                    kw[name] = values[name]
                    except ValueError as e:
                        raise RequestValueError(str(e)) from e
            try:
                return ensure_sync(f)(*args, **kw)
            except TypeError as e:
                raise RequestTypeError(str(e)) from e

        return t.cast(tc.WrappedFunc, wrapper)

    return decorator


def requestquery(*args) -> tc.ReturnDecorator:
    """Like :func:`requestargs`, but loads from request.args (the query string)."""
    return requestargs(*args, source='query')


def requestform(*args) -> tc.ReturnDecorator:
    """Like :func:`requestargs`, but loads from request.form (the form submission)."""
    return requestargs(*args, source='form')


def requestbody(*args) -> tc.ReturnDecorator:
    """Like :func:`requestargs`, but loads from form or JSON basis content type."""
    return requestargs(*args, source='body')


def load_model(  # pylint: disable=too-many-arguments
    model,
    attributes=None,
    parameter=None,
    kwargs=False,
    permission=None,
    addlperms=None,
    urlcheck=(),
):
    """
    Decorate a view to load a model given a query parameter.

    Typical usage::

        @app.route('/<profile>')
        @load_model(Profile, {'name': 'profile'}, 'profileob')
        def profile_view(profileob):
            # 'profileob' is now a Profile model instance.
            # The load_model decorator replaced this:
            # profileob = Profile.query.filter_by(name=profile).first_or_404()
            return f"Hello, {profileob.name}"

    Using the same name for request and parameter makes code easier to understand::

        @app.route('/<profile>')
        @load_model(Profile, {'name': 'profile'}, 'profile')
        def profile_view(profile):
            return f"Hello, {profile.name}"

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

    :param kwargs: If True, the original request parameters are passed to the decorated
        function as a ``kwargs`` parameter

    :param permission: If present, ``load_model`` calls the
        :meth:`~coaster.sqlalchemy.PermissionMixin.permissions` method of the
        retrieved object with ``current_auth.actor`` as a parameter. If
        ``permission`` is not present in the result, ``load_model`` aborts with
        a 403. The permission may be a string or a list of strings, in which
        case access is allowed if any of the listed permissions are available

    :param addlperms: Iterable or callable that returns an iterable containing
        additional permissions available to the user, apart from those granted by the
        models. In an app that uses Lastuser for authentication, passing
        ``lastuser.permissions`` will pass through permissions granted via Lastuser

    :param list urlcheck: If an attribute in this list has been used to load an object,
        but the value of the attribute in the loaded object does not match the request
        argument, issue a redirect to the corrected URL. This is useful for attributes
        like ``url_id_name`` and ``url_name_uuid_b58`` where the ``name`` component may
        change
    """
    return load_models(
        (model, attributes, parameter),
        kwargs=kwargs,
        permission=permission,
        addlperms=addlperms,
        urlcheck=urlcheck,
    )


def load_models(*chain, **kwargs):
    """
    Decorator to load a chain of models from the given parameters. This works just like
    :func:`load_model` and accepts the same parameters, with some small differences.

    :param chain: The chain is a list of tuples of (``model``, ``attributes``,
        ``parameter``). Lists and tuples can be used interchangeably. All retrieved
        instances are passed as parameters to the decorated function

    :param permission: Same as in :func:`load_model`, except
        :meth:`~coaster.sqlalchemy.PermissionMixin.permissions` is called on every
        instance in the chain and the retrieved permissions are passed as the second
        parameter to the next instance in the chain. This allows later instances to
        revoke permissions granted by earlier instances. As an example, if a URL
        represents a hierarchy such as ``/<page>/<comment>``, the ``page`` can assign
        ``edit`` and ``delete`` permissions, while the ``comment`` can revoke ``edit``
        and retain ``delete`` if the current user owns the page but not the comment

    In the following example, load_models loads a Folder with a name matching the name
    in the URL, then loads a Page with a matching name and with the just-loaded Folder
    as parent. If the Page provides a 'view' permission to the current user, the
    decorated function is called::

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
        def decorated_function(*args, **kw):
            permissions = None
            permission_required = kwargs.get('permission')
            url_check_attributes = kwargs.get('urlcheck', [])
            if isinstance(permission_required, str):
                permission_required = {permission_required}
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
                    location = url_for(request.endpoint, **view_args)
                    if request.query_string:
                        location = location + '?' + request.query_string.decode()
                    return redirect(location, code=307)

                if permission_required:
                    permissions = item.permissions(
                        current_auth.actor, inherited=permissions
                    )
                    addlperms = kwargs.get('addlperms') or []
                    if callable(addlperms):
                        addlperms = addlperms() or []
                    permissions.update(addlperms)
                if g:  # XXX: Deprecated
                    g.permissions = permissions
                if request:
                    add_auth_attribute('permissions', permissions)
                if (
                    url_check and request.method == 'GET'
                ):  # Only do urlcheck redirects on GET requests
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
                        location = url_for(request.endpoint, **view_args)
                        if request.query_string:
                            location = location + '?' + request.query_string.decode()
                        return redirect(location, code=302)
                if parameter.startswith('g.'):
                    parameter = parameter[2:]
                    setattr(g, parameter, item)
                result[parameter] = item
            if permission_required and not permission_required & permissions:
                abort(403)
            if kwargs.get('kwargs'):
                return ensure_sync(f)(*args, kwargs=kw, **result)
            return ensure_sync(f)(*args, **result)

        return decorated_function

    return inner


def _best_mimetype_match(available_list, accept_mimetypes, default=None):
    for use_mimetype, _quality in accept_mimetypes:
        for mimetype in available_list:
            if use_mimetype.lower() == mimetype.lower():
                return use_mimetype.lower()
    return default


def dict_jsonify(param):
    """
    Convert the parameter into a dictionary before calling jsonify, if it's not already
    one
    """
    if not isinstance(param, dict):
        param = dict(param)
    return jsonify(param)


def dict_jsonp(param):
    """
    Convert the parameter into a dictionary before calling jsonp, if it's not already
    one
    """
    if not isinstance(param, dict):
        param = dict(param)
    return jsonp(param)


def render_with(template=None, json=False, jsonp=False):  # pylint: disable=W0621
    """
    Decorator to render the wrapped function with the given template (or dictionary
    of mimetype keys to templates, where the template is a string name of a template
    file or a callable that returns a Response). The function's return value must be
    a dictionary and is passed to the template as parameters. Callable templates get
    a single parameter with the function's return value. Usage::

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
    render_with will attempt to use the handler for (in order) ``text/html``,
    ``text/plain`` and the various JSON types, falling back to rendering the value into
    a unicode string.

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
    :param jsonp: Helper to add a JSONP handler (if True, also provides JSON, default
        is False)
    """
    if jsonp:
        templates = {
            'application/json': dict_jsonp,
            'application/javascript': dict_jsonp,
        }
    elif json:
        templates = {'application/json': dict_jsonify}
    else:
        templates = {}
    if isinstance(template, str):
        templates['text/html'] = template
    elif isinstance(template, dict):
        templates.update(template)
    elif template is None and (json or jsonp):
        pass
    else:  # pragma: no cover
        raise ValueError("Expected string or dict for template")

    default_mimetype = '*/*'
    if '*/*' not in templates:
        templates['*/*'] = str
        default_mimetype = 'text/plain'
        for mimetype in ('text/html', 'text/plain', 'application/json'):
            if mimetype in templates:
                templates['*/*'] = templates[mimetype]
                default_mimetype = (
                    mimetype  # Remember which mimetype's handler is serving for */*
                )
                break

    template_mimetypes = list(templates.keys())
    template_mimetypes.remove(
        '*/*'
    )  # */* messes up matching, so supply it only as last resort

    def inner(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Check if we need to bypass rendering
            render = kwargs.pop('_render', True)

            # Get the result
            result = ensure_sync(f)(*args, **kwargs)

            # Is the result a Response object? Don't attempt rendering
            if isinstance(
                result, (Response, WerkzeugResponse, current_app.response_class)
            ):
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
                # We do not use request.accept_mimetypes.best_match because it turns out
                # to be buggy: it returns the least match instead of the best match.
                # Previously:
                # use_mimetype = request.accept_mimetypes.best_match(template_mimetypes,
                #     '*/*')
                use_mimetype = _best_mimetype_match(
                    template_mimetypes, request.accept_mimetypes, '*/*'
                )

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
                            mimetype=default_mimetype
                            if use_mimetype == '*/*'
                            else use_mimetype,
                        )
                else:  # Not a callable mimetype. Render as a jinja2 template
                    rendered = current_app.response_class(
                        render_template(templates[use_mimetype], **result),
                        status=status_code or 200,
                        headers=headers,
                        mimetype=default_mimetype
                        if use_mimetype == '*/*'
                        else use_mimetype,
                    )
                return rendered
            return result

        return decorated_function

    return inner


def cors(
    origins: t.Union[te.Literal['*'], t.Container[str], t.Callable[[str], bool]],
    methods: t.Iterable[str] = (
        'OPTIONS',
        'HEAD',
        'GET',
        'POST',
        'DELETE',
        'PATCH',
        'PUT',
    ),
    headers: t.Iterable[str] = (
        'Accept',
        'Accept-Language',
        'Content-Language',
        'Content-Type',
        'X-Requested-With',
    ),
    max_age: t.Optional[int] = None,
) -> tc.ReturnDecorator:
    """
    Add CORS headers to the decorated view function.

    :param origins: Allowed origins (see below)
    :param methods: A list of allowed HTTP methods
    :param headers: A list of allowed HTTP headers
    :param max_age: Duration in seconds for which the CORS response may be cached

    The :obj:`origins` parameter may be one of:

    1. A callable that receives the origin as a parameter.
    2. A list of origins.
    3. ``*``, indicating that this resource is accessible by any origin.

    Example use::

        from flask import Flask, Response
        from coaster.views import cors

        app = Flask(__name__)

        @app.route('/any')
        @cors('*')
        def any_origin():
            return Response()

        @app.route('/static', methods=['GET', 'POST'])
        @cors(
            ['https://hasgeek.com'],
            methods=['GET', 'POST'],
            headers=['Content-Type', 'X-Requested-With'],
            max_age=3600)
        def static_list():
            return Response()

        def check_origin(origin):
            # check if origin should be allowed
            return True

        @app.route('/callable', methods=['GET'])
        @cors(check_origin)
        def callable_function():
            return Response()
    """

    def decorator(f: tc.WrappedFunc) -> tc.WrappedFunc:
        @wraps(f)
        def wrapper(*args, **kwargs) -> WerkzeugResponse:
            origin = request.headers.get('Origin')
            if not origin or origin == 'null':
                if request.method == 'OPTIONS':
                    abort(400)
                # If no Origin header is supplied, CORS checks don't apply
                return make_response(ensure_sync(f)(*args, **kwargs))

            if request.method not in methods:
                abort(405)

            if origins == '*':
                pass
            elif is_collection(origins) and origin in origins:  # type: ignore[operator]
                pass
            elif callable(origins) and origins(origin):
                pass
            else:
                abort(403)

            if request.method == 'OPTIONS':
                # pre-flight request
                resp = Response()
            else:
                resp = make_response(ensure_sync(f)(*args, **kwargs))

            resp.headers['Access-Control-Allow-Origin'] = origin
            resp.headers['Access-Control-Allow-Methods'] = ', '.join(methods)
            resp.headers['Access-Control-Allow-Headers'] = ', '.join(headers)
            if max_age:
                resp.headers['Access-Control-Max-Age'] = str(max_age)
            # Add 'Origin' to the Vary header since response will vary by origin
            resp.vary.add('Origin')  # type: ignore[union-attr]

            return resp

        wrapper.provide_automatic_options = False  # type: ignore[attr-defined]
        wrapper.required_methods = ['OPTIONS']  # type: ignore[attr-defined]

        return t.cast(tc.WrappedFunc, wrapper)

    return decorator


def requires_permission(permission: t.Union[str, t.Set[str]]) -> tc.ReturnDecorator:
    """
    Decorate to require a permission to be present in ``current_auth.permissions``.

    Aborts with ``403 Forbidden`` if the permission is not present.

    The decorated view will have an ``is_available`` method that can be called
    to perform the same test.

    :param permission: Permission that is required. If a collection type is
        provided, any one permission must be available
    """

    def decorator(f: tc.WrappedFunc) -> tc.WrappedFunc:
        def is_available_here() -> bool:
            if not current_auth.permissions:
                return False
            if isinstance(permission, (set, frozenset)):
                return bool(current_auth.permissions & permission)
            return permission in current_auth.permissions

        def is_available(context=None) -> bool:
            result = is_available_here()
            if result and hasattr(f, 'is_available'):
                # We passed, but we're wrapping another test, so ask there as well
                return f.is_available(context)
            return result

        @wraps(f)
        def wrapper(*args, **kwargs) -> t.Any:
            add_auth_attribute('login_required', True)
            if not is_available_here():
                abort(403)
            return ensure_sync(f)(*args, **kwargs)

        wrapper.requires_permission = permission  # type: ignore[attr-defined]
        wrapper.is_available = is_available  # type: ignore[attr-defined]
        return t.cast(tc.WrappedFunc, wrapper)

    return decorator
