"""View decorators."""

# spell-checker:ignore requestargs
from __future__ import annotations

from collections.abc import Awaitable, Collection, Container, Iterable, Mapping
from functools import wraps
from inspect import iscoroutinefunction
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Literal,
    Optional,
    Protocol,
    TypeVar,
    Union,
    cast,
    overload,
)
from typing_extensions import ParamSpec

from flask import (
    Response,
    abort,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from flask.typing import ResponseReturnValue
from werkzeug.datastructures import Headers, MIMEAccept
from werkzeug.exceptions import BadRequest
from werkzeug.wrappers import Response as WerkzeugResponse

from ..auth import add_auth_attribute, current_auth
from ..compat import BaseResponse, ensure_sync, flask_g, quart_g
from ..utils import InspectableSet, is_collection

__all__ = [
    'ReturnRenderWith',
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

ReturnRenderWithData = Mapping[str, object]
ReturnRenderWithResponse = Union[WerkzeugResponse, ReturnRenderWithData]
ReturnRenderWithHeaders = Union[list[tuple[str, str]], dict[str, str], Headers]
ReturnRenderWith = Union[
    ReturnRenderWithResponse,
    tuple[ReturnRenderWithData, ReturnRenderWithHeaders],
    tuple[ReturnRenderWithData, int],
    tuple[ReturnRenderWithData, int, ReturnRenderWithHeaders],
]
_VP = ParamSpec('_VP')  # View parameters as accepted by the decorated view
_VR = TypeVar('_VR', bound=Any)  # View return value
_VR_co = TypeVar('_VR_co', covariant=True)  # View covariant return type


class RequestTypeError(BadRequest, TypeError):
    """Exception that combines TypeError with BadRequest."""


class RequestValueError(BadRequest, ValueError):
    """Exception that combines ValueError with BadRequest."""


def requestargs(
    *args: Union[str, tuple[str, Callable[[str], Any]]],
    source: Literal['values', 'form', 'query', 'body'] = 'values',
) -> Callable[[Callable[_VP, _VR_co]], Callable[_VP, _VR_co]]:
    """
    Decorate a function to load parameters from the request if not supplied directly.

    Usage::

        @requestargs('param1', ('param2', int), 'param3[]', ...)
        def function(param1, param2=0, param3=None): ...

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

    def decorator(f: Callable[_VP, _VR_co]) -> Callable[_VP, _VR_co]:
        """Apply config to wrapped function."""
        namefilt: list[tuple[str, Optional[Callable[[str], Any]], bool]] = [
            (name[:-2], filt, True) if name.endswith('[]') else (name, filt, False)
            for name, filt in [
                (a[0], a[1]) if isinstance(a, (list, tuple)) else (a, None)
                for a in args
            ]
        ]

        if source == 'query':

            def datasource() -> tuple[Any, bool]:
                return (request.args, True) if request else ({}, False)

        elif source == 'form':

            def datasource() -> tuple[Any, bool]:
                return (request.form, True) if request else ({}, False)

        elif source == 'body':

            def datasource() -> tuple[Any, bool]:
                if not request:
                    return ({}, False)
                return (
                    (request.json, False) if request.is_json else (request.form, True)
                )

        elif source == 'values':

            def datasource() -> tuple[Any, bool]:
                return (request.values, True) if request else ({}, False)

        else:
            raise TypeError("Unknown data source")

        @wraps(f)
        def wrapper(*args: _VP.args, **kwargs: _VP.kwargs) -> _VR_co:
            """Wrap a view to insert keyword arguments."""
            values, has_gettype = datasource()
            for name, filt, is_list in namefilt:
                # Process name if
                # (a) it's not in the function's parameters, and
                # (b) is in the form/query
                if name not in kwargs and name in values:
                    try:
                        if is_list:
                            if has_gettype:
                                kwargs[name] = values.getlist(name, type=filt)
                            else:
                                if filt:
                                    kwargs[name] = [filt(_v) for _v in values[name]]
                                else:
                                    kwargs[name] = values[name]
                        else:
                            if has_gettype:
                                kwargs[name] = values.get(name, type=filt)
                            else:
                                if filt:
                                    kwargs[name] = filt(values[name])
                                else:
                                    kwargs[name] = values[name]
                    except ValueError as e:
                        raise RequestValueError(str(e)) from e
            try:
                return ensure_sync(f)(*args, **kwargs)
            except TypeError as e:
                raise RequestTypeError(str(e)) from e

        return wrapper

    return decorator


def requestquery(
    *args: Union[str, tuple[str, Callable[[str], Any]]],
) -> Callable[[Callable[_VP, _VR_co]], Callable[_VP, _VR_co]]:
    """Like :func:`requestargs`, but loads from request.args (the query string)."""
    return requestargs(*args, source='query')


def requestform(
    *args: Union[str, tuple[str, Callable[[str], Any]]],
) -> Callable[[Callable[_VP, _VR_co]], Callable[_VP, _VR_co]]:
    """Like :func:`requestargs`, but loads from request.form (the form submission)."""
    return requestargs(*args, source='form')


def requestbody(
    *args: Union[str, tuple[str, Callable[[str], Any]]],
) -> Callable[[Callable[_VP, _VR_co]], Callable[_VP, _VR_co]]:
    """Like :func:`requestargs`, but loads from form or JSON basis content type."""
    return requestargs(*args, source='body')


def load_model(
    model: Union[type[Any], list[type[Any]], tuple[type[Any], ...]],
    attributes: dict[str, Union[str, Callable[[dict, dict], Any]]],
    parameter: str,
    kwargs: bool = False,
    permission: Optional[Union[str, set[str]]] = None,
    addlperms: Optional[Union[Iterable[str], Callable[[], Iterable[str]]]] = None,
    urlcheck: Collection[str] = (),
) -> Callable[[Callable[..., _VR]], Callable[..., Union[_VR, BaseResponse]]]:
    """
    Decorate a view to load a model given a query parameter.

    Typical usage::

        @app.route('/<profile>')
        @load_model(Profile, {'name': 'profile'}, 'profileob')
        def profile_view(profileob: Profile) -> ResponseReturnValue:
            # 'profileob' is now a Profile model instance.
            # The load_model decorator replaced this:
            # profileob = Profile.query.filter_by(name=profile).first_or_404()
            return f"Hello, {profileob.name}"

    Using the same name for request and parameter makes code easier to understand::

        @app.route('/<profile>')
        @load_model(Profile, {'name': 'profile'}, 'profile')
        def profile_view(profile: Profile) -> ResponseReturnValue:
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


def load_models(
    *chain: tuple[
        Union[type[Any], list[type[Any]], tuple[type[Any], ...]],
        dict[str, Union[str, Callable[[dict, dict], Any]]],
        str,
    ],
    permission: Optional[Union[str, set[str]]] = None,
    **config,
) -> Callable[[Callable[..., _VR]], Callable[..., Union[_VR, BaseResponse]]]:
    """
    Load a chain of models from the given parameters.

    This works just like :func:`load_model` and accepts the same parameters, with some
    small differences.

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
            permission='view',
        )
        def show_page(folder: Folder, page: Page) -> ResponseReturnValue:
            return render_template('page.html', folder=folder, page=page)
    """

    def decorator(f: Callable[..., _VR]) -> Callable[..., Union[_VR, BaseResponse]]:
        @wraps(f)
        def wrapper(*args, **kwargs) -> Union[_VR, BaseResponse]:
            view_args: Optional[dict[str, Any]]
            request_endpoint: str = request.endpoint  # type: ignore[assignment]
            permissions: Optional[set[str]] = None
            permission_required = (
                {permission}
                if isinstance(permission, str)
                else set(permission)
                if permission is not None
                else None
            )
            url_check_attributes = config.get('urlcheck', [])
            result: dict[str, Any] = {}
            for models, attributes, parameter in chain:
                if not isinstance(models, (list, tuple)):
                    models = (models,)
                item = None
                url_check = False
                url_check_paramvalues: dict[str, tuple[Union[str, Callable], Any]] = {}
                for model in models:
                    query = model.query
                    for k, v in attributes.items():
                        if callable(v):
                            val = v(result, kwargs)
                            query = query.filter_by(**{k: val})
                        else:
                            if '.' in v:
                                first, attrs = v.split('.', 1)
                                val = result.get(first)
                                for attr in attrs.split('.'):
                                    val = getattr(val, attr)
                            else:
                                val = result.get(v, kwargs.get(v))
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
                    view_args = dict(request.view_args or {})
                    view_args.update(item.redirect_view_args())
                    location = url_for(request_endpoint, **view_args)
                    if request.query_string:
                        location = location + '?' + request.query_string.decode()
                    return redirect(location, code=307)

                if permission_required:
                    permissions = item.permissions(
                        current_auth.actor, inherited=permissions
                    )
                    if permissions is None:
                        permissions = set()
                    addlperms = config.get('addlperms') or []
                    if callable(addlperms):
                        addlperms = addlperms() or []
                    permissions.update(addlperms)
                if g := (quart_g or flask_g):  # XXX: Deprecated
                    g.permissions = permissions
                if request:
                    add_auth_attribute('permissions', InspectableSet(permissions))
                if url_check and request.method == 'GET':
                    # Only do url_check redirects on GET requests
                    url_redirect = False
                    view_args = None
                    for k2, v2 in url_check_paramvalues.items():
                        uparam, uvalue = v2
                        if (vvalue := getattr(item, k2)) != uvalue:
                            url_redirect = True
                            if view_args is None:
                                view_args = dict(request.view_args or {})
                            if isinstance(uparam, str):
                                view_args[uparam] = vvalue
                    if url_redirect:
                        if view_args is None:
                            location = url_for(request_endpoint)
                        else:
                            location = url_for(request_endpoint, **view_args)
                        if request.query_string:
                            location = location + '?' + request.query_string.decode()
                        return redirect(location, code=302)
                if parameter.startswith('g.') and g:
                    parameter = parameter[2:]
                    setattr(g, parameter, item)
                result[parameter] = item
            if permission_required and (
                permissions is None or not permission_required & permissions
            ):
                abort(403)
            if config.get('kwargs'):
                return ensure_sync(f)(*args, kwargs=kwargs, **result)
            return ensure_sync(f)(*args, **result)

        return wrapper

    return decorator


def _best_mimetype_match(
    available_list: list[str], accept_mimetypes: MIMEAccept, default: str
) -> str:
    for acceptable_mimetype, _quality in accept_mimetypes:
        acceptable_mimetype = acceptable_mimetype.lower()
        for available_mimetype in available_list:
            if acceptable_mimetype == available_mimetype.lower():
                return available_mimetype
    return default


def render_with(
    template: Union[
        dict[str, Union[str, Callable[[ReturnRenderWithData], ResponseReturnValue]]],
        str,
        None,
    ] = None,
    json: bool = False,
) -> Callable[[Callable[_VP, ReturnRenderWith]], Callable[_VP, WerkzeugResponse]]:
    """
    Render the view's dict output with a MIMEtype-specific renderer.

    Accepts a single Jinja2 template, or a dictionary of mimetypes and their templates
    or callables. If a template filename is provided, the view's return type must be a
    dictionary and is passed to ``render_template`` as context. If a callable is
    provided, the view's result is passed in as a single parameter. The view may return
    a status code or headers as in Flask views. These are not passed to the callable
    and will be applied to the response from the callable. Usage::

        @app.route('/myview')
        @render_with('myview.html')
        def myview():
            return {'data': 'value'}


        @app.route('/myview_with_json')
        @render_with('myview.html', json=True)
        def myview_no_json():
            return {'data': 'value'}


        @app.route('/otherview')
        @render_with(
            {
                'text/html': 'otherview.html',
                'text/xml': 'otherview.xml',
            }
        )
        def otherview():
            return {'data': 'value'}


        @app.route('/404view')
        @render_with('myview.html')
        def myview():
            return {'error': '404 Not Found'}, 404


        @app.route('/headerview')
        @render_with('myview.html')
        def myview():
            return {'data': 'value'}, {'X-Header': 'Header value'}

    When a mimetype is specified and the template is not a callable, the response is
    returned with the same mimetype. Callable must return Response objects with the
    correct mimetype.

    If a dictionary of templates is provided and does not include a handler for ``*/*``,
    render_with will attempt to use the handler for (in order) ``text/html``,
    ``text/plain`` and ``application/json``, falling back to rendering the value as a
    string.

    If the decorated view is called outside a request context, the return value will
    not be rendered. Rendering may also be skipped within a request context by passing
    a keyword argument ``_render=False``.

    :param template: Single template, or dictionary of MIME type to templates/callables
    :param json: Respond to ``application/json`` with a JSON response (default False)

    .. deprecated:: 0.7.0
        render_with no longer has a shorthand for JSONP. If still required, specify a
        template handler as ``{'text/javascript': coaster.views.jsonp}``
    """
    templates: dict[
        str, Union[str, Callable[[ReturnRenderWithData], ResponseReturnValue]]
    ]
    default_mimetype: Optional[str] = None
    templates = {'application/json': jsonify} if json else {}
    if isinstance(template, str):
        templates['*/*'] = template
    elif isinstance(template, dict):
        templates.update(template)
    elif template is None and json:
        pass
    else:  # pragma: no cover
        raise ValueError("Expected string or dict for template")

    if '*/*' not in templates:
        templates['*/*'] = str
        default_mimetype = 'text/plain'
        for candidate_default in ('text/html', 'text/plain', 'application/json'):
            if candidate_default in templates:
                templates['*/*'] = templates[candidate_default]
                # Remember which mimetype's handler is serving for */*
                default_mimetype = candidate_default
                break

    template_mimetypes = list(templates.keys())
    # */* messes up matching, so supply it only as last resort
    template_mimetypes.remove('*/*')

    def decorator(
        f: Callable[_VP, ReturnRenderWith],
    ) -> Callable[_VP, WerkzeugResponse]:
        @wraps(f)
        def wrapper(*args: _VP.args, **kwargs: _VP.kwargs) -> WerkzeugResponse:
            # Check if we need to bypass rendering
            render = kwargs.pop('_render', True)

            # Get the result
            result = ensure_sync(f)(*args, **kwargs)

            if not render or not request:
                # Return value is not a BaseResponse here
                return result  # type: ignore[return-value]

            # Is the result a Response object? Don't attempt rendering
            if isinstance(result, WerkzeugResponse):
                return result

            headers: Optional[ReturnRenderWithHeaders]
            status_code: Optional[int]

            # Did the result include status code and headers?
            if isinstance(result, tuple):
                resultset = result
                result = resultset[0]
                len_resultset = len(resultset)
                status_code = None
                headers = None
                if len_resultset == 1:
                    raise TypeError(
                        "View's response is an unexpected single-element tuple"
                    )
                if len_resultset == 2:
                    status_or_headers = resultset[1]
                    if isinstance(status_or_headers, (Headers, dict, tuple, list)):
                        status_code = None
                        headers = Headers(status_or_headers)
                    else:
                        status_code = status_or_headers
                        headers = None
                elif len(resultset) == 3:
                    status_code = resultset[1]
                    headers = resultset[2]
                else:
                    raise TypeError("View's response is an oversized tuple")
            else:
                status_code = None
                headers = None

            # Set Vary: Accept if there is more than one way to render the result
            vary_accept = len(templates) > 1

            # Find a matching mimetype between Accept headers and available templates
            # We do not use request.accept_mimetypes.best_match because it turns out
            # to be buggy: it returns the least match instead of the best match.
            # This does not appear to be fixed as of Werkzeug 2.3
            accept_mimetype = _best_mimetype_match(
                template_mimetypes, request.accept_mimetypes, '*/*'
            )
            # Previously:
            # accept_mimetype = request.accept_mimetypes.best_match(
            #     template_mimetypes, '*/*'
            # )

            # Now render the result with the template for the mimetype
            use_template = templates[accept_mimetype]
            if callable(use_template):
                response = make_response(use_template(result))
            else:
                if TYPE_CHECKING:
                    assert isinstance(use_template, str)  # nosec B101
                    assert isinstance(result, dict)  # nosec B101
                response = make_response(render_template(use_template, **result))
                if accept_mimetype == '*/*':
                    if default_mimetype is not None:
                        response.mimetype = default_mimetype
                else:
                    response.mimetype = accept_mimetype
            if status_code is not None:
                response.status_code = status_code
            if headers is not None:
                response.headers.extend(headers)
            if vary_accept:
                response.vary.add('Accept')
            return response

        return wrapper

    return decorator


class CorsDecoratorProtocol(Protocol):
    @overload
    def __call__(
        self, __decorated: Callable[_VP, Awaitable[ResponseReturnValue]]
    ) -> Callable[_VP, Awaitable[BaseResponse]]: ...

    @overload
    def __call__(
        self, __decorated: Callable[_VP, ResponseReturnValue]
    ) -> Callable[_VP, BaseResponse]: ...


def cors(
    origins: Union[Literal['*'], Container[str], Callable[[str], bool]],
    methods: Iterable[str] = (
        'OPTIONS',
        'HEAD',
        'GET',
        'POST',
        'DELETE',
        'PATCH',
        'PUT',
    ),
    headers: Iterable[str] = (
        'Accept',
        'Accept-Language',
        'Content-Language',
        'Content-Type',
        'X-Requested-With',
    ),
    max_age: Optional[int] = None,
) -> CorsDecoratorProtocol:
    """
    Add CORS headers to the decorated view function.

    :param origins: Allowed origins (see below)
    :param methods: A list of allowed HTTP methods
    :param headers: A list of allowed HTTP headers
    :param max_age: Duration in seconds for which the CORS response may be cached

    The :obj:`origins` parameter may be one of:

    1. A callable that receives the origin as a parameter and returns True/False.
    2. A list of origins.
    3. Literal['*'], indicating that this resource is accessible by any origin.

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
            max_age=3600,
        )
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

    @overload
    def decorator(
        f: Callable[_VP, Awaitable[ResponseReturnValue]],
    ) -> Callable[_VP, Awaitable[BaseResponse]]: ...

    @overload
    def decorator(
        f: Callable[_VP, ResponseReturnValue],
    ) -> Callable[_VP, BaseResponse]: ...

    def decorator(
        f: Union[
            Callable[_VP, ResponseReturnValue],
            Callable[_VP, Awaitable[ResponseReturnValue]],
        ],
    ) -> Union[Callable[_VP, BaseResponse], Callable[_VP, Awaitable[BaseResponse]]]:
        def check_origin() -> Optional[str]:
            origin = request.headers.get('Origin')
            if not origin or origin == 'null':
                if request.method == 'OPTIONS':
                    abort(400)
                return None

            if request.method not in methods:
                abort(405)

            if not (
                origins == '*'
                or (
                    is_collection(origins) and origin in origins  # type: ignore[operator]
                )
                or (callable(origins) and origins(origin))
            ):
                abort(403)
            return origin

        def set_headers(origin: str, resp: BaseResponse) -> BaseResponse:
            resp.headers['Access-Control-Allow-Origin'] = origin
            resp.headers['Access-Control-Allow-Methods'] = ', '.join(methods)
            resp.headers['Access-Control-Allow-Headers'] = ', '.join(headers)
            if max_age:
                resp.headers['Access-Control-Max-Age'] = str(max_age)
            # Add 'Origin' to the Vary header since response will vary by origin
            resp.vary.add('Origin')

            return resp

        if iscoroutinefunction(f):

            @wraps(f)
            async def wrapper(*args: _VP.args, **kwargs: _VP.kwargs) -> BaseResponse:
                origin = check_origin()
                if origin is None:
                    # If no Origin header is supplied, CORS checks don't apply
                    return make_response(await f(*args, **kwargs))
                if request.method == 'OPTIONS':
                    # pre-flight request
                    resp = Response()
                else:
                    resp = make_response(await f(*args, **kwargs))
                return set_headers(origin, resp)

        else:

            @wraps(f)
            def wrapper(*args: _VP.args, **kwargs: _VP.kwargs) -> BaseResponse:
                origin = check_origin()
                if origin is None:
                    # If no Origin header is supplied, CORS checks don't apply
                    return make_response(f(*args, **kwargs))
                if request.method == 'OPTIONS':
                    # pre-flight request
                    resp = Response()
                else:
                    resp = make_response(f(*args, **kwargs))
                return set_headers(origin, resp)

        wrapper.provide_automatic_options = False  # type: ignore[attr-defined]
        wrapper.required_methods = ['OPTIONS']  # type: ignore[attr-defined]

        return wrapper

    return decorator


def requires_permission(
    permission: Union[str, set[str]],
) -> Callable[[Callable[_VP, _VR_co]], Callable[_VP, _VR_co]]:
    """
    Decorate to require a permission to be present in ``current_auth.permissions``.

    Aborts with ``403 Forbidden`` if the permission is not present.

    The decorated view will have an ``is_available`` method that can be called
    to perform the same test.

    :param permission: Permission that is required. If a collection type is
        provided, any one permission must be available
    """

    def decorator(f: Callable[_VP, _VR_co]) -> Callable[_VP, _VR_co]:
        def is_available_here() -> bool:
            if not current_auth.permissions:
                return False
            if isinstance(permission, (set, frozenset)):
                return bool(current_auth.permissions & permission)
            return permission in current_auth.permissions

        def is_available(context: Optional[Any] = None) -> bool:
            result = is_available_here()
            if result and hasattr(f, 'is_available'):
                # We passed, but we're wrapping another test, so ask there as well
                return f.is_available(context)
            return result

        if iscoroutinefunction(f):

            @wraps(f)
            async def async_wrapper(*args: _VP.args, **kwargs: _VP.kwargs) -> Any:
                add_auth_attribute('login_required', True)
                if not is_available_here():
                    abort(403)
                return await f(*args, **kwargs)

            # Fix return type hint
            wrapper = cast(Callable[_VP, _VR_co], async_wrapper)
        else:

            @wraps(f)
            def wrapper(*args: _VP.args, **kwargs: _VP.kwargs) -> _VR_co:
                add_auth_attribute('login_required', True)
                if not is_available_here():
                    abort(403)
                return f(*args, **kwargs)

        wrapper.requires_permission = permission  # type: ignore[attr-defined]
        wrapper.is_available = is_available  # type: ignore[attr-defined]
        return wrapper

    return decorator
