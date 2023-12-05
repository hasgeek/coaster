"""
Class-based views
-----------------

Group related views into a class for easier management.
"""

from __future__ import annotations

import typing as t
import typing_extensions as te
from functools import partial, update_wrapper, wraps
from inspect import getattr_static, iscoroutinefunction
from typing import cast, overload

from flask import abort, g, has_app_context, make_response, redirect, request
from flask.typing import ResponseReturnValue

try:  # Flask >= 3.0  # pragma: no cover
    from flask.sansio.app import App as FlaskApp
    from flask.sansio.blueprints import Blueprint, BlueprintSetupState
except ModuleNotFoundError:  # Flask < 3.0
    from flask import Blueprint, Flask as FlaskApp
    from flask.blueprints import BlueprintSetupState

from furl import furl
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.orm.descriptor_props import SynonymProperty
from sqlalchemy.orm.properties import RelationshipProperty
from werkzeug.local import LocalProxy
from werkzeug.routing import Map as WzMap, Rule as WzRule
from werkzeug.wrappers import Response as BaseResponse

from .. import typing as tc  # pylint: disable=reimported
from ..auth import add_auth_attribute, current_auth
from ..sqlalchemy import Query, UrlForMixin
from ..typing import MethodProtocol, WrappedFunc
from ..utils import InspectableSet
from .misc import ensure_sync

__all__ = [
    # Functions
    'rulejoin',
    'current_view',
    # View base classes
    'ClassView',
    'ModelView',
    # View decorators
    'route',
    'viewdata',
    # Mixin classes
    'url_change_check',
    'requires_roles',
    'UrlChangeCheck',
    'UrlForView',
    'InstanceLoader',
]

# --- Types and protocols --------------------------------------------------------------

#: Type for URL rules in classviews
RouteRuleOptions = t.Dict[str, t.Any]
ViewMethodType = t.TypeVar('ViewMethodType', bound='ViewMethod')
ClassViewSubtype = t.TypeVar('ClassViewSubtype', bound='ClassView')
ClassViewType: te.TypeAlias = t.Type[ClassViewSubtype]
ModelType = te.TypeVar('ModelType', default=t.Any)

P = te.ParamSpec('P')
P2 = te.ParamSpec('P2')
R_co = t.TypeVar('R_co', covariant=True)
R2_co = t.TypeVar('R2_co', covariant=True)


# These protocols are used for decorator helpers that return an overloaded decorator
# https://typing.readthedocs.io/en/latest/source/protocols.html#callback-protocols
# https://stackoverflow.com/a/56635360/78903
class RouteDecoratorProtocol(te.Protocol):
    """Protocol for the decorator returned by ``@route(...)``."""

    @t.overload
    def __call__(self, __decorated: ClassViewType) -> ClassViewType:
        ...

    @t.overload
    def __call__(self, __decorated: ViewMethod[P, R_co]) -> ViewMethod[P, R_co]:
        ...

    @t.overload
    def __call__(
        self, __decorated: MethodProtocol[te.Concatenate[t.Any, P], R_co]
    ) -> ViewMethod[P, R_co]:
        ...

    def __call__(  # skipcq: PTC-W0049
        self,
        __decorated: t.Union[
            ClassViewType,
            MethodProtocol[te.Concatenate[t.Any, P], R_co],
            ViewMethod[P, R_co],
        ],
    ) -> t.Union[ClassViewType, ViewMethod[P, R_co]]:
        ...


class ViewDataDecoratorProtocol(te.Protocol):
    """Protocol for the decorator returned by ``@viewdata(...)``."""

    @t.overload
    def __call__(self, __decorated: ViewMethod[P, R_co]) -> ViewMethod[P, R_co]:
        ...

    @t.overload
    def __call__(
        self, __decorated: MethodProtocol[te.Concatenate[t.Any, P], R_co]
    ) -> ViewMethod[P, R_co]:
        ...

    def __call__(  # skipcq: PTC-W0049
        self,
        __decorated: t.Union[
            MethodProtocol[te.Concatenate[t.Any, P], R_co], ViewMethod[P, R_co]
        ],
    ) -> ViewMethod[P, R_co]:
        ...


class InitAppCallback(te.Protocol):
    """Protocol for a callable that gets a callback from ClassView.init_app."""

    def __call__(
        self,
        app: t.Union[FlaskApp, Blueprint],
        rule: str,
        endpoint: str,
        view_func: t.Callable,
        **options,
    ) -> t.Any:
        ...


class ViewFuncProtocol(te.Protocol):  # pylint: disable=too-few-public-methods
    """Protocol for view functions that store context in the function's namespace."""

    wrapped_func: t.Callable
    view_class: ClassViewType
    view: ViewMethod
    __call__: t.Callable


# --- Class views and utilities --------------------------------------------------------


def _get_arguments_from_rule(
    rule: str, endpoint: str, options: t.Dict[str, t.Any], url_map: WzMap
) -> t.List[str]:
    """Get arguments from a URL rule."""
    obj = WzRule(rule, endpoint=endpoint, **options)
    obj.bind(url_map)
    return list(obj.arguments)


def route(rule: str, **options) -> RouteDecoratorProtocol:
    """
    Decorate :class:`ClassView` and its methods to define a URL routing rule.

    Accepts the same parameters that Flask's ``app.``:meth:`~flask.Flask.route`
    accepts. See :class:`ClassView` for usage notes.
    """

    @t.overload
    def decorator(decorated: ClassViewType) -> ClassViewType:
        ...

    @t.overload
    def decorator(decorated: ViewMethod[P, R_co]) -> ViewMethod[P, R_co]:
        ...

    @t.overload
    def decorator(
        decorated: MethodProtocol[te.Concatenate[t.Any, P], R_co]
    ) -> ViewMethod[P, R_co]:
        ...

    def decorator(
        decorated: t.Union[
            ClassViewType,
            MethodProtocol[te.Concatenate[t.Any, P], R_co],
            ViewMethod[P, R_co],
        ]
    ) -> t.Union[ClassViewType, ViewMethod[P, R_co]]:
        # Are we decorating a ClassView? If so, annotate the ClassView and return it
        if isinstance(decorated, type) and issubclass(decorated, ClassView):
            if '__routes__' not in decorated.__dict__:
                decorated.__routes__ = []
            decorated.__routes__.append((rule, options))
            return decorated

        return ViewMethod(decorated, rule=rule, rule_options=options)

    return decorator


def viewdata(
    **kwargs,
) -> ViewDataDecoratorProtocol:
    """
    Decorate view to add additional data alongside :func:`route`.

    This data is accessible as the ``data`` attribute on the view handler.
    """

    @t.overload
    def decorator(decorated: ViewMethod[P, R_co]) -> ViewMethod[P, R_co]:
        ...

    @t.overload
    def decorator(
        decorated: MethodProtocol[te.Concatenate[t.Any, P], R_co]
    ) -> ViewMethod[P, R_co]:
        ...

    def decorator(
        decorated: t.Union[
            ViewMethod[P, R_co], MethodProtocol[te.Concatenate[t.Any, P], R_co]
        ]
    ) -> ViewMethod[P, R_co]:
        return ViewMethod(decorated, data=kwargs)

    return decorator


def rulejoin(class_rule: str, method_rule: str) -> str:
    """
    Join URL paths from routing rules on a class and its methods.

    Used internally by :class:`ClassView` to combine rules from the :func:`route`
    decorators on the class and on the individual view handler methods::

        >>> rulejoin('/', '')
        '/'
        >>> rulejoin('/', 'first')
        '/first'
        >>> rulejoin('/first', '/second')
        '/second'
        >>> rulejoin('/first', 'second')
        '/first/second'
        >>> rulejoin('/first/', 'second')
        '/first/second'
        >>> rulejoin('/first/<second>', '')
        '/first/<second>'
        >>> rulejoin('/first/<second>', 'third')
        '/first/<second>/third'
    """
    if method_rule.startswith('/'):
        return method_rule
    return (
        class_rule
        + ('' if class_rule.endswith('/') or not method_rule else '/')
        + method_rule
    )


class ViewMethod(t.Generic[P, R_co]):  # pylint: disable=too-many-instance-attributes
    """Internal object created by the :func:`route` and :func:`viewdata` functions."""

    name: str
    endpoint: str
    func: t.Callable[te.Concatenate[t.Any, P], R_co]
    wrapped_func: t.Callable
    view_func: t.Callable

    def __init__(
        self,
        decorated: t.Union[
            t.Callable[te.Concatenate[t.Any, P], R_co], ViewMethod[P, R_co]
        ],
        rule: t.Optional[str] = None,
        rule_options: t.Optional[t.Dict[str, t.Any]] = None,
        data: t.Optional[t.Dict[str, t.Any]] = None,
    ) -> None:
        if rule is not None:
            self.routes = [(rule, rule_options or {})]
        else:
            self.routes = []
        self.data = data or {}
        self.endpoints: t.Set[str] = set()

        # Are we decorating another ViewHelper? If so, copy routes and func from it.
        if isinstance(decorated, ViewMethod):
            self.routes.extend(decorated.routes)
            newdata = dict(decorated.data)
            newdata.update(self.data)
            self.data = newdata
            self.func = decorated.func
        else:
            self.func = decorated

        self.name = self.func.__name__
        # self.endpoint will change in __set_name__
        self.endpoint = self.name
        self.__doc__ = self.func.__doc__  # pylint: disable=W0201

    def reroute(
        self,
        f: t.Union[
            ViewMethod[P2, R2_co], MethodProtocol[te.Concatenate[t.Any, P2], R2_co]
        ],
    ) -> ViewMethod[P2, R2_co]:
        """Replace a view handler in a subclass while keeping its URL route rules."""
        cls = cast(t.Type[ViewMethod], self.__class__)
        r: ViewMethod[P2, R2_co] = cls(f, data=self.data)
        r.routes = self.routes
        return r

    def copy_for_subclass(self) -> te.Self:
        """Make a copy of this ViewHandler, for use in a subclass."""
        # Like reroute, but just a copy
        r = self.__class__(self.func, data=self.data)
        r.routes = self.routes
        # Don't copy wrapped_func, as it will be re-wrapped by init_app
        r.endpoint = self.endpoint
        return r

    def __set_name__(self, owner: t.Type, name: str) -> None:
        # This is almost always the existing value acquired from func.__name__
        self.name = name
        # We can't use `.` as a separator because Flask uses that to identify blueprint
        # endpoints. Instead, we construct this to be `ViewClass_method_name`
        self.endpoint = owner.__name__ + '_' + self.name

    @overload
    def __get__(self, obj: None, _cls: t.Type) -> te.Self:
        ...

    @overload
    def __get__(self, obj: t.Any, _cls: t.Type) -> ViewHandler[P, R_co]:
        ...

    def __get__(
        self, obj: t.Optional[t.Any], _cls: t.Type
    ) -> t.Union[te.Self, ViewHandler[P, R_co]]:
        if obj is None:
            return self
        return ViewHandler(self, obj)

    def __call__(  # pylint: disable=no-self-argument
        __self, self: ClassViewSubtype, *args: P.args, **kwargs: P.kwargs
    ) -> R_co:
        return __self.func(self, *args, **kwargs)

    def init_app(
        self,
        app: t.Union[FlaskApp, Blueprint],
        cls: t.Type[ClassView],
        callback: t.Optional[InitAppCallback] = None,
    ) -> None:
        """
        Register routes for a given app and :class:`ClassView` class.

        At the time of this call, we will always be in the view class even if we were
        originally defined in a base class. :meth:`ClassView.init_app` ensures this.
        :meth:`init_app` therefore takes the liberty of adding additional attributes to
        ``self``:

        * :attr:`wrapped_func`: The function wrapped with all decorators added by the
            class
        * :attr:`view_func`: The view function registered as a Flask view handler
        * :attr:`endpoints`: The URL endpoints registered to this view handler
        """

        def view_func(**view_args) -> BaseResponse:
            this = cast(ViewFuncProtocol, view_func)
            # view_func does not make any reference to variables from init_app to avoid
            # creating a closure. Instead, the code further below sticks all relevant
            # variables into view_func's namespace.

            # Instantiate the view class. We depend on its __init__ requiring no
            # parameters
            viewinst = this.view_class()
            # Declare ourselves (the ViewHandler) as the current view. The wrapper makes
            # equivalence tests possible, such as ``self.current_handler == self.index``
            viewinst.current_handler = ViewHandler(
                # Mypy is incorrectly applying the descriptor protocol to a non-class's
                # dict, and therefore concluding this.view.__get__() -> ViewHandler,
                # instead of this.view just remaining a ViewHelper, sans descriptor call
                # https://github.com/python/mypy/issues/15822
                this.view,  # type: ignore[arg-type]
                viewinst,
            )
            # Place view arguments in the instance, in case they are needed outside the
            # dispatch process
            viewinst.view_args = view_args
            # Place the view instance on the request stack for :obj:`current_view` to
            # discover
            if g:
                g._current_view = viewinst  # pylint: disable=protected-access
            # Call the view instance's dispatch method. View classes can customise this
            # for desired behaviour.
            return viewinst.dispatch_request(this.wrapped_func, view_args)

        # Decorate the wrapped view function with the class's desired decorators.
        # Mixin classes may provide their own decorators, and all of them will be
        # applied. The oldest defined decorators (from mixins) will be applied first,
        # and the class's own decorators last. Within the list of decorators, we reverse
        # the list again, so that a list specified like this:
        #
        #     __decorators__ = [first, second]
        #
        # Has the same effect as writing this:
        #
        #     @first
        #     @second
        #     def myview(self):
        #         pass
        wrapped_func = self.func
        for base in reversed(cls.__mro__):
            if '__decorators__' in base.__dict__:
                for decorator in reversed(base.__dict__['__decorators__']):
                    wrapped_func = decorator(wrapped_func)
                    wrapped_func.__name__ = self.name  # See below

        # Make view_func resemble the underlying view handler method...
        view_func = update_wrapper(view_func, wrapped_func)
        # ...but give view_func the name of the method in the class (self.name),
        # self.name will differ from __name__ only if the view handler method
        # was defined outside the class and then added to the class with a
        # different name.
        view_func.__name__ = self.name

        # Stick `wrapped_func` and `cls` into view_func to avoid creating a closure.
        view_func.wrapped_func = wrapped_func  # type: ignore[attr-defined]
        view_func.view_class = cls  # type: ignore[attr-defined]
        view_func.view = self  # type: ignore[attr-defined]

        # Keep a copy of these functions (we already have self.func)
        self.wrapped_func = wrapped_func
        self.view_func = view_func

        for class_rule, class_options in cls.__routes__:
            for method_rule, method_options in self.routes:
                use_options = dict(method_options)
                use_options.update(class_options)
                endpoint = use_options.pop('endpoint', self.endpoint)
                self.endpoints.add(endpoint)
                use_rule = rulejoin(class_rule, method_rule)
                app.add_url_rule(use_rule, endpoint, view_func, **use_options)
                if callback:
                    callback(app, use_rule, endpoint, view_func, **use_options)


class ViewHandler(t.Generic[P, R_co]):
    """Wrapper for a view method in an instance of the view class."""

    def __init__(
        self,
        view: ViewMethod[P, R_co],
        obj: ClassViewSubtype,
    ) -> None:
        # obj is the ClassView instance
        self._view = view
        self._obj = obj

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R_co:
        """Treat this like a call to the original method and not to the view."""
        # As per the __decorators__ spec, we call .func, not .wrapped_func
        return self._view.func(self._obj, *args, **kwargs)

    def __getattr__(self, name: str) -> t.Any:
        return getattr(self._view, name)

    def __eq__(self, other: t.Any) -> bool:
        if isinstance(other, ViewHandler):
            return self._view == other._view and self._obj == other._obj
        return NotImplemented

    def is_available(self) -> bool:
        """Indicate whether this view is available in the current context."""
        if hasattr(self._view.wrapped_func, 'is_available'):
            return self._view.wrapped_func.is_available(self._obj)
        return True


class ClassView:
    """
    Base class for defining a collection of views that are related to each other.

    Subclasses may define methods decorated with :func:`route`. When :meth:`init_app` is
    called, these will be added as routes to the app.

    Typical use::

        @route('/')
        class IndexView(ClassView):
            @viewdata(title="Homepage")
            @route('')
            def index():
                return render_template('index.html.jinja2')

            @route('about')
            @viewdata(title="About us")
            def about():
                return render_template('about.html.jinja2')

        IndexView.init_app(app)

    The :func:`route` decorator on the class specifies the base rule, which is prefixed
    to the rule specified on each view method. This example produces two view handlers,
    for ``/`` and ``/about``. Multiple :func:`route` decorators may be used in both
    places.

    The :func:`viewdata` decorator can be used to specify additional data, and may
    appear either before or after the :func:`route` decorator, but only adjacent to it.
    Data specified here is available as the :attr:`data` attribute on the view handler,
    or at runtime in templates as ``current_view.current_handler.data``.

    A rudimentary CRUD view collection can be assembled like this::

        @route('/doc/<name>')
        class DocumentView(ClassView):
            @route('')
            @render_with('mydocument.html.jinja2', json=True)
            def view(self, name):
                document = MyDocument.query.filter_by(name=name).first_or_404()
                return document.current_access()

            @route('edit', methods=['POST'])
            @requestform('title', 'content')
            def edit(self, name, title, content):
                document = MyDocument.query.filter_by(name=name).first_or_404()
                document.title = title
                document.content = content
                return 'edited!'

        DocumentView.init_app(app)

    See :class:`ModelView` for a better way to build views around a model.
    """

    # If the class did not get a @route decorator, provide a fallback route
    __routes__: t.ClassVar[t.List[t.Tuple[str, RouteRuleOptions]]] = [('', {})]

    #: Track all the views registered in this class
    __views__: t.ClassVar[t.Collection[str]] = frozenset()

    #: Subclasses may define decorators here. These will be applied to every
    #: view handler in the class, but only when called as a view and not
    #: as a Python method.
    __decorators__: t.ClassVar[t.List[t.Callable[[t.Callable], t.Callable]]] = []

    #: Indicates whether meth:`is_available` should simply return `True`
    #: without conducting a test. Subclasses should not set this flag. It will
    #: be set by :meth:`init_app` if any view handler is missing an
    #: ``is_available`` method, as it implies that view is always available.
    is_always_available: t.ClassVar[bool] = False

    #: When a view is called, this will point to the current view handler,
    #: an instance of :class:`ViewHandler`.
    current_handler: ViewHandler

    #: When a view is called, this will be replaced with a dictionary of
    #: arguments to the view.
    view_args: t.Dict[str, t.Any] = {}

    def __eq__(self, other: t.Any) -> bool:
        return type(other) is type(self)

    def __ne__(self, other: t.Any) -> bool:
        return type(other) is not type(self)

    def dispatch_request(
        self, view: t.Callable[..., ResponseReturnValue], view_args: t.Dict[str, t.Any]
    ) -> BaseResponse:
        """
        View dispatcher that calls before_request, the view, and then after_request.

        Subclasses may override this to provide a custom flow. :class:`ModelView` does
        this to insert a model loading phase.

        :param view: View method wrapped in specified decorators. The dispatcher must
            call this
        :param dict view_args: View arguments, to be passed on to the view method
        """
        # Call the :meth:`before_request` method
        resp = ensure_sync(self.before_request)()
        if resp:
            return ensure_sync(self.after_request)(make_response(resp))
        # Call the view handler method, then pass the response to :meth:`after_response`
        return ensure_sync(self.after_request)(
            make_response(ensure_sync(view)(self, **view_args))
        )

    def before_request(self) -> t.Optional[ResponseReturnValue]:
        """
        Process request before the view handler.

        This method is called after the app's ``before_request`` handlers, and before
        the class's view method. Subclasses and mixin classes may define their own
        :meth:`before_request` to pre-process requests. This method receives context via
        `self`, in particular via :attr:`current_handler` and :attr:`view_args`.
        """
        return None

    def after_request(self, response: BaseResponse) -> BaseResponse:
        """
        Process response returned by view.

        This method is called with the response from the view handler method. It must
        return a valid response object. Subclasses and mixin classes may override this
        to perform any necessary post-processing::

            class MyView(ClassView):
                ...
                def after_request(self, response):
                    response = super().after_request(response)
                    ...  # Process here
                    return response

        :param response: Response from the view handler method
        :return: Response object
        """
        return response

    def is_available(self) -> bool:
        """
        Return `True` if *any* view handler in the class is currently available.

        Tests by calling the `is_available` method of each view.
        """
        return self.is_always_available or any(
            getattr(self, _v).is_available() for _v in self.__views__
        )

    @classmethod
    def add_route_for(cls, _name: str, rule: str, **options) -> None:
        """
        Add a route for an existing method or view.

        Useful for modifying routes that a subclass inherits from a base class::

            class BaseView(ClassView):
                def latent_view(self):
                    return 'latent-view'

                @route('other')
                def other_view(self):
                    return 'other-view'

            @route('/path')
            class SubView(BaseView):
                pass

            SubView.add_route_for('latent_view', 'latent')
            SubView.add_route_for('other_view', 'another')
            SubView.init_app(app)

            # Created routes:
            # /path/latent -> SubView.latent (added)
            # /path/other -> SubView.other (inherited)
            # /path/another -> SubView.other (added)

        :param _name: Name of the method or view on the class
        :param rule: URL rule to be added
        :param options: Additional options for :meth:`~flask.Flask.add_url_rule`
        """
        attr = getattr_static(cls, _name)
        if attr is None:
            raise AttributeError(_name)
        viewh = t.cast(ViewMethod, route(rule, **options)(attr))
        setattr(cls, _name, viewh)
        viewh.__set_name__(cls, _name)
        if _name not in cls.__views__:
            cls.__views__ = frozenset(cls.__views__) | {_name}

    def __init_subclass__(cls) -> None:
        """Copy views from base classes into the subclass."""
        view_names = set()
        processed = set()
        for base in cls.__mro__:
            for name, attr in base.__dict__.items():
                if name in processed:
                    continue
                processed.add(name)
                if isinstance(attr, ViewMethod):
                    if base != cls:
                        # Copy ViewHandler instances into subclasses. We know an attr
                        # with the same name doesn't exist in the subclass because it
                        # was processed first in the MRO and added to the processed set.
                        # FIXME: If this handler is registered with an app because the
                        # base class is not a mixin, it may be a conflicting route.
                        # init_app on both classes will be called in the future, so it
                        # needs a guard condition there. How will the guard work?
                        attr = attr.copy_for_subclass()
                        setattr(cls, name, attr)
                        attr.__set_name__(cls, name)
                    view_names.add(name)
        cls.__views__ = frozenset(view_names)
        # Set is_always_available attr in the subclass. init_app may change this to
        # True after confirming that any of the view handlers _after wrapping_ with
        # local decorators remains always available.
        cls.is_always_available = False
        super().__init_subclass__()

    @classmethod
    def init_app(
        cls,
        app: t.Union[FlaskApp, Blueprint],
        callback: t.Optional[InitAppCallback] = None,
    ) -> None:
        """
        Register views on an app.

        If :attr:`callback` is specified, it will be called after
        ``app.``:meth:`~flask.Flask.add_url_rule`, with app and the same parameters.
        """
        for name in cls.__views__:
            attr = getattr(cls, name)
            attr.init_app(app, cls, callback=callback)
            if not hasattr(attr.wrapped_func, 'is_available'):
                cls.is_always_available = True


class ModelView(ClassView, t.Generic[ModelType]):
    """
    Base class for constructing views around a model.

    Functionality is provided via mixin classes that must precede :class:`ModelView` in
    base class order. Two mixins are provided: :class:`UrlForView` and
    :class:`InstanceLoader`. Sample use::

        @route('/doc/<document>')
        class DocumentView(UrlForView, InstanceLoader, ModelView):
            model = Document
            route_model_map = {
                'document': 'name'
                }

            @route('')
            @render_with(json=True)
            def view(self):
                return self.obj.current_access()

        Document.views.main = DocumentView
        DocumentView.init_app(app)

    Views will not receive view arguments, unlike in :class:`ClassView`. If necessary,
    they are available as `self.view_args`.
    """

    #: The model that is being handled by this ModelView (autoset from Generic arg)
    model: t.ClassVar[t.Type]
    #: A loaded object of the model's type
    obj: ModelType

    #: A mapping of URL rule variables to attributes on the model. For example,
    #: if the URL rule is ``/<parent>/<document>``, the attribute map can be::
    #:
    #:     model = MyModel
    #:     route_model_map = {
    #:         'document': 'name',       # Map 'document' in URL to MyModel.name
    #:         'parent': 'parent.name',  # Map 'parent' to MyModel.parent.name
    #:         }
    #:
    #: The :class:`InstanceLoader` mixin class will convert this mapping into
    #: SQLAlchemy attribute references to load the instance object.
    route_model_map: t.ClassVar[t.Dict[str, str]] = {}

    def __init__(self, obj: t.Optional[ModelType] = None) -> None:
        super().__init__()
        self.obj = obj  # type: ignore[assignment]

    def __init_subclass__(cls) -> None:
        """Extract model from generic args and set on cls if unset."""
        if getattr(cls, 'model', None) is None:  # Allow a base/mixin class to set it
            for base in te.get_original_bases(cls):
                origin_base = t.get_origin(base)
                if origin_base is ModelView:
                    (model_type,) = t.get_args(base)
                    if model_type is not t.Any:
                        cls.model = model_type
                    break
        super().__init_subclass__()

    def __eq__(self, other: t.Any) -> bool:
        return type(other) is type(self) and other.obj == self.obj

    def __ne__(self, other: t.Any) -> bool:
        return not self.__eq__(other)

    def dispatch_request(
        self, view: t.Callable[..., ResponseReturnValue], view_args: t.Dict[str, t.Any]
    ) -> BaseResponse:
        """
        Dispatch a view.

        Calls :meth:`before_request`, :meth:`load`, the view, and then
        :meth:`after_request`.

        :param view: View method wrapped in specified decorators
        :param dict view_args: View arguments, to be passed on to :meth:`load` but not
            to the view
        """
        # Call the :meth:`before_request` method
        resp = ensure_sync(self.before_request)()
        if resp:
            return ensure_sync(self.after_request)(make_response(resp))
        # Load the database model
        resp = ensure_sync(self.load)(**view_args)
        if resp:
            return ensure_sync(self.after_request)(make_response(resp))
        # Call the view handler method, then pass the response to :meth:`after_response`
        return ensure_sync(self.after_request)(make_response(ensure_sync(view)(self)))

    load: t.Callable[..., t.Optional[ResponseReturnValue]]

    def load(  # type: ignore[no-redef]
        self, **view_args
    ) -> t.Optional[ResponseReturnValue]:
        """
        Load the database object given view parameters.

        The default implementation calls :meth:`loader` and sets the return value as
        :attr:`obj`. It then calls :meth:`after_loader` to process this object. This
        behaviour is considered legacy as an implementation that processes interim
        objects like redirects cannot ascribe a clear data type to :attr:`obj`. New
        implementations must override :meth:`load` and be responsible for setting
        :attr:`obj`.
        """
        self.obj = self.loader(**view_args)  # type: ignore[assignment]
        # Trigger pre-view processing of the loaded object
        return self.after_loader()

    loader: t.Callable[..., t.Optional[ModelType]]

    def loader(  # type: ignore[no-redef]  # pragma: no cover
        self, **view_args
    ) -> t.Optional[ModelType]:
        """
        Load database object and return it.

        Subclasses or mixin classes must override this method to provide a model
        instance loader. The return value of this method will be placed at
        ``self.obj``.

        An implementation that returns an interim object for further processing in
        :meth:`after_loader` should instead override :meth:`load` so that :attr:`obj`
        can be declared to be a well defined type.

        :return: Object instance loaded from database
        """
        raise NotImplementedError("View class is missing a loader method")

    def after_loader(  # pylint: disable=useless-return
        self,
    ) -> t.Optional[t.Any]:
        """Process loaded value after :meth:`loader` is called (deprecated)."""
        # Determine permissions available on the object for the current actor,
        # but only if the view method has a requires_permission decorator
        if hasattr(self.current_handler.wrapped_func, 'requires_permission'):
            if isinstance(self.obj, tuple):
                perms = None
                for subobj in self.obj:
                    if hasattr(subobj, 'permissions'):
                        perms = subobj.permissions(current_auth.actor, perms)
                perms = InspectableSet(perms or set())
            elif hasattr(self.obj, 'current_permissions'):
                # current_permissions always returns an InspectableSet
                perms = self.obj.current_permissions
            else:
                perms = InspectableSet()
            add_auth_attribute('permissions', perms)
        return None


def requires_roles(roles: t.Set) -> tc.ReturnDecorator:
    """Decorate to require specific roles in a :class:`ModelView` view."""

    def decorator(f: tc.WrappedFunc) -> tc.WrappedFunc:
        def is_available_here(context: ModelView) -> bool:
            return context.obj.roles_for(current_auth.actor).has_any(roles)

        def is_available(context: ModelView) -> bool:
            result = is_available_here(context)
            if result and hasattr(f, 'is_available'):
                # We passed, but we're wrapping another test, so ask there as well
                return f.is_available(context)
            return result

        def validate(context: ModelView) -> None:
            add_auth_attribute('login_required', True)
            if not is_available_here(context):
                abort(403)

        @wraps(f)
        def wrapper(self: ModelView, *args, **kwargs) -> t.Any:
            validate(self)
            return f(self, *args, **kwargs)

        @wraps(f)
        async def async_wrapper(self: ModelView, *args, **kwargs) -> t.Any:
            validate(self)
            return await f(self, *args, **kwargs)

        use_wrapper = async_wrapper if iscoroutinefunction(f) else wrapper
        use_wrapper.requires_roles = roles  # type: ignore[attr-defined]
        use_wrapper.is_available = is_available  # type: ignore[attr-defined]
        return cast(tc.WrappedFunc, use_wrapper)

    return decorator


class UrlForView:  # pylint: disable=too-few-public-methods
    """
    Mixin class that registers view handler methods with as views on the model.

    This mixin must be used with :class:`ModelView`, and the model must be based on
    :class:`~coaster.sqlalchemy.mixins.UrlForMixin`.
    """

    @classmethod
    def init_app(
        cls,
        app: t.Union[FlaskApp, Blueprint],
        callback: t.Optional[InitAppCallback] = None,
    ) -> None:
        """Register view on an app."""

        def register_view_on_model(  # pylint: disable=too-many-arguments
            cls: t.Type[ClassView],
            callback: t.Optional[InitAppCallback],
            app: t.Union[FlaskApp, Blueprint],
            rule: str,
            endpoint: str,
            view_func: t.Callable,
            **options: t.Any,
        ) -> None:
            def register_paths_from_app(
                reg_app: FlaskApp,
                reg_rule: str,
                reg_endpoint: str,
                reg_options: t.Dict[str, t.Any],
            ) -> None:
                # Only pass in the attrs that are included in the rule.
                # 1. Extract list of variables from the rule
                rulevars = _get_arguments_from_rule(
                    reg_rule, reg_endpoint, reg_options, reg_app.url_map
                )
                # Make a subset of cls.route_model_map with the required variables
                params = {
                    v: cast(t.Type[ModelView], cls).route_model_map[v]
                    for v in rulevars
                    if v in cast(t.Type[ModelView], cls).route_model_map
                }
                # Register endpoint with the view function's name, endpoint name and
                # parameters
                cast(
                    t.Type[UrlForMixin], cast(t.Type[ModelView], cls).model
                ).register_endpoint(
                    action=view_func.__name__,
                    endpoint=reg_endpoint,
                    app=reg_app,
                    roles=getattr(view_func, 'requires_roles', None),
                    paramattrs=params,
                )
                cast(
                    t.Type[UrlForMixin], cast(t.Type[ModelView], cls).model
                ).register_view_for(
                    app=reg_app,
                    action=view_func.__name__,
                    classview=cls,
                    attr=view_func.__name__,
                )

            def blueprint_postprocess(state: BlueprintSetupState) -> None:
                if state.url_prefix is not None:
                    reg_rule = '/'.join(
                        (state.url_prefix.rstrip('/'), rule.lstrip('/'))
                    )
                else:
                    reg_rule = rule
                if state.subdomain:
                    reg_options = dict(options)
                    reg_options.setdefault('subdomain', state.subdomain)
                else:
                    reg_options = options
                reg_endpoint = f'{state.name_prefix}.{state.name}.{endpoint}'.lstrip(
                    '.'
                )
                register_paths_from_app(state.app, reg_rule, reg_endpoint, reg_options)

            if isinstance(app, FlaskApp):
                register_paths_from_app(app, rule, endpoint, options)
            elif isinstance(app, Blueprint):
                app.record(blueprint_postprocess)
            else:
                raise TypeError(f"App must be Flask or Blueprint: {app!r}")
            if callback:  # pragma: no cover
                callback(app, rule, endpoint, view_func, **options)

        assert issubclass(cls, ClassView)  # nosec B101
        super().init_app(  # type: ignore[misc]
            app, callback=partial(register_view_on_model, cls, callback)
        )


def url_change_check(f: WrappedFunc) -> WrappedFunc:
    """
    Decorate view in a :class:`ModelView` to check for a change in URL.

    This decorator checks the URL of the loaded object in ``self.obj`` against the URL
    in the request (using ``self.obj.url_for(__name__)``). If the URLs do not match and
    the request is a ``GET``, it issues a redirect to the correct URL. Usage::

        @route('/doc/<document>')
        class MyModelView(UrlForView, InstanceLoader, ModelView):
            model = MyModel
            route_model_map = {'document': 'url_id_name'}

            @route('')
            @url_change_check
            @render_with(json=True)
            def view(self):
                return self.obj.current_access()

    If the decorator is required for all view handlers in the class, use
    :class:`UrlChangeCheck`.

    This decorator will only consider the URLs to be different if:

    * Schemes differ (``http`` vs ``https`` etc)
    * Hostnames differ (apart from a case difference, as user agents use lowercase)
    * Paths differ

    The current URL's query will be copied to the redirect URL. The URL fragment
    (``#target_id``) is not available to the server and will be lost.
    """

    def validate(context: ModelView) -> t.Optional[ResponseReturnValue]:
        if request.method == 'GET' and context.obj is not None:
            correct_url = furl(context.obj.url_for(f.__name__, _external=True))
            stripped_url = correct_url.copy().remove(
                username=True, password=True, port=True, query=True, fragment=True
            )
            request_url = furl(request.base_url).remove(
                username=True, password=True, port=True, query=True, fragment=True
            )
            # What's different? If it's a case difference in hostname, or different
            # port number, username, password, query or fragment, ignore. For any
            # other difference (scheme, hostname or path), do a redirect.
            if stripped_url != request_url:
                # TODO: Decide if this should be 302 (default) or 301
                return redirect(
                    str(correct_url.set(query=request.query_string.decode()))
                )
        return None

    @wraps(f)
    def wrapper(self: ModelView, *args, **kwargs) -> t.Any:
        retval = validate(self)
        if retval is not None:
            return retval
        return f(self, *args, **kwargs)

    @wraps(f)
    async def async_wrapper(self: ModelView, *args, **kwargs) -> t.Any:
        retval = validate(self)
        if retval is not None:
            return retval
        return await f(self, *args, **kwargs)

    return cast(tc.WrappedFunc, async_wrapper if iscoroutinefunction(f) else wrapper)


class UrlChangeCheck:  # pylint: disable=too-few-public-methods
    """
    Check for changed URLs in a :class:`ModelView`.

    Mixin class for :class:`ModelView` and :class:`UrlForMixin` that applies the
    :func:`url_change_check` decorator to all view handler methods. Subclasses
    :class:`UrlForView`, which it depends on to register the view with the
    model so that URLs can be generated. Usage::

        @route('/doc/<document>')
        class MyModelView(UrlChangeCheck, InstanceLoader, ModelView):
            model = MyModel
            route_model_map = {'document': 'url_id_name'}

            @route('')
            @render_with(json=True)
            def view(self):
                return self.obj.current_access()
    """

    __decorators__: t.List[t.Callable[[t.Callable], t.Callable]] = [url_change_check]


class InstanceLoader:  # pylint: disable=too-few-public-methods
    """
    Mixin class for :class:`ModelView` that loads an instance.

    This class provides a :meth:`loader` that attempts to load an instance of the model
    based on attributes in the :attr:`~ModelView.route_model_map` dictionary. It will
    traverse relationships (many-to-one or one-to-one) and perform a SQL ``JOIN`` with
    the target class.

    .. deprecated:: 0.7.0
        This loader adds needless complexity. You are recommended to implement a loader
        method directly.
    """

    route_model_map: t.ClassVar[t.Dict[str, str]]
    model: t.ClassVar[t.Type]
    query: t.ClassVar[t.Optional[Query]] = None

    def loader(self, **view_args) -> t.Any:
        """Load instance based on view arguments."""
        # pylint: disable=too-many-nested-blocks
        if any(name in self.route_model_map for name in view_args):
            # We have a URL route attribute that matches one of the model's attributes.
            # Attempt to load the model instance
            filters = {
                self.route_model_map[key]: value
                for key, value in view_args.items()
                if key in self.route_model_map
            }

            query = self.query or self.model.query
            joined_models = set()
            for name, value in filters.items():
                if '.' in name:
                    # Did we get something like `parent.name`?
                    # Dig into it to find the source column
                    source = self.model
                    for subname in name.split('.'):
                        attr = relattr = getattr(source, subname)
                        # Did we get to something like 'parent'?
                        # 1. If it's a synonym, get the attribute it is a synonym for
                        # 2. If it's a relationship, find the source class, join it to
                        # the query, and then continue looking for attributes over there
                        if hasattr(attr, 'original_property') and isinstance(
                            attr.original_property, SynonymProperty
                        ):
                            attr = getattr(source, attr.original_property.name)
                        if isinstance(attr, InstrumentedAttribute) and isinstance(
                            attr.property, RelationshipProperty
                        ):
                            attr = attr.property.argument
                            if attr not in joined_models:
                                # SQL JOIN the other model on the basis of
                                # the relationship that led us to this join
                                query = query.join(attr, relattr)
                                # But ensure we don't JOIN twice
                                joined_models.add(attr)
                        source = attr
                    query = query.filter(source == value)
                else:
                    query = query.filter(getattr(self.model, name) == value)
            obj = query.one_or_404()
            return obj
        return None


# --- Proxy ----------------------------------------------------------------------------

#: A proxy object that holds the currently executing :class:`ClassView` instance,
#: for use in templates as context. Exposed to templates by
#: :func:`coaster.app.init_app`. The current view handler method within the class is
#: named :attr:`~current_view.current_handler`, so to examine it, use
#: :attr:`current_view.current_handler`.
current_view = cast(
    ClassView,
    LocalProxy(
        lambda: getattr(g, '_current_view', None) if has_app_context() else None
    ),
)
