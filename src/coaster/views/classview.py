"""
Class-based views.

Group related views into a class for easier management. See :class:`ClassView` and
:class:`ModelView` for two different ways to use them.
"""

# pyright: reportMissingImports=false

from __future__ import annotations

import warnings
from collections.abc import Awaitable, Collection, Coroutine
from functools import partial, update_wrapper, wraps
from inspect import iscoroutinefunction
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Generic,
    Optional,
    Protocol,
    Union,
    cast,
    get_args,
    get_origin,
    overload,
)
from typing_extensions import (
    Concatenate,
    ParamSpec,
    Self,
    TypeAlias,
    TypeVar,
    get_original_bases,
)

from flask.typing import ResponseReturnValue
from furl import furl
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.orm.descriptor_props import SynonymProperty
from sqlalchemy.orm.properties import RelationshipProperty
from werkzeug.local import LocalProxy
from werkzeug.routing import Map as WzMap, Rule as WzRule

from ..auth import add_auth_attribute, current_auth
from ..compat import (
    BaseApp,
    BaseBlueprint,
    BaseResponse,
    BlueprintSetupState,
    abort,
    app_ctx,
    async_make_response,
    make_response,
    redirect,
    request,
)
from ..sqlalchemy import PermissionMixin, Query, UrlForMixin
from ..typing import Method
from ..utils import InspectableSet

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
    'url_change_check',
    'requires_roles',
    # Mixin classes
    'UrlChangeCheck',
    'UrlForView',
    'InstanceLoader',
]

# --- Types and protocols --------------------------------------------------------------

#: Type for URL rules in classviews
RouteRuleOptions: TypeAlias = dict[str, Any]
ClassViewSubtype = TypeVar('ClassViewSubtype', bound='ClassView')
ClassViewType: TypeAlias = type[ClassViewSubtype]
ModelType = TypeVar('ModelType', default=Any)

_P = ParamSpec('_P')
_P2 = ParamSpec('_P2')
_R_co = TypeVar('_R_co', covariant=True)
_R2_co = TypeVar('_R2_co', covariant=True)


# These protocols are used for decorator helpers that return an overloaded decorator
# https://typing.readthedocs.io/en/latest/source/protocols.html#callback-protocols
# https://stackoverflow.com/a/56635360/78903
class RouteDecoratorProtocol(Protocol):
    """Protocol for the decorator returned by ``@route(...)``."""

    @overload
    def __call__(self, __decorated: ClassViewType) -> ClassViewType: ...

    @overload
    def __call__(self, __decorated: ViewMethod[_P, _R_co]) -> ViewMethod[_P, _R_co]: ...

    @overload
    def __call__(self, __decorated: Method[_P, _R_co]) -> ViewMethod[_P, _R_co]: ...

    def __call__(
        self,
        __decorated: Union[ClassViewType, Method[_P, _R_co], ViewMethod[_P, _R_co]],
    ) -> Union[ClassViewType, ViewMethod[_P, _R_co]]: ...


class ViewDataDecoratorProtocol(Protocol):
    """Protocol for the decorator returned by ``@viewdata(...)``."""

    @overload
    def __call__(self, __decorated: ViewMethod[_P, _R_co]) -> ViewMethod[_P, _R_co]: ...

    @overload
    def __call__(self, __decorated: Method[_P, _R_co]) -> ViewMethod[_P, _R_co]: ...

    def __call__(
        self, __decorated: Union[Method[_P, _R_co], ViewMethod[_P, _R_co]]
    ) -> ViewMethod[_P, _R_co]: ...


class InitAppCallback(Protocol):
    """Protocol for a callable that gets a callback from ClassView.init_app."""

    def __call__(
        self,
        app: Union[BaseApp, BaseBlueprint],
        rule: str,
        endpoint: str,
        view_func: Callable,
        **options,
    ) -> Any: ...


# --- Class views and utilities --------------------------------------------------------


def _get_arguments_from_rule(
    rule: str, endpoint: str, options: dict[str, Any], url_map: WzMap
) -> list[str]:
    """Get arguments from a URL rule."""
    obj = WzRule(rule, endpoint=endpoint, **options)
    obj.bind(url_map)
    return list(obj.arguments)


def route(
    rule: str,
    init_app: Optional[
        Union[BaseApp, BaseBlueprint, tuple[Union[BaseApp, BaseBlueprint], ...]]
    ] = None,
    **options: Any,
) -> RouteDecoratorProtocol:
    """
    Decorate :class:`ClassView` and its methods to define a URL routing rule.

    Accepts the same parameters as Flask's ``app.``:meth:`~flask.Flask.route` See
    :class:`ClassView` for usage notes. This decorator must always be the outermost
    decorator (barring :func:`viewdata`).

    The rule specified on a method will be joined to the rule on a class using
    :func:`rulejoin`, which inserts a ``/`` separator. If the method's rule begins with
    ``/``, it is assumed to be an absolute path and the class's rule is ignored. The
    rule options specified in both places are merged, with the method's options
    overriding.

    :param rule: The URL rule passed to Flask's :meth:`~flask.Flask.add_url_rule` after
        joining class and method rules
    :param init_app: If provided when decorating a :class:`ClassView` or
        :meth:`ModelView`, also call :meth:`~ClassView.init_app`. This can be a Flask
        app, Blueprint, or a tuple of them. This parameter may not be provided when
        decorating a method
    :param options: URL rule options, passed as is to Flask's
        :meth:`~flask.Flask.add_url_rule` after merging class and method options
    """

    @overload
    def decorator(decorated: ClassViewType) -> ClassViewType: ...

    @overload
    def decorator(decorated: ViewMethod[_P, _R_co]) -> ViewMethod[_P, _R_co]: ...

    @overload
    def decorator(decorated: Method[_P, _R_co]) -> ViewMethod[_P, _R_co]: ...

    def decorator(
        decorated: Union[
            ClassViewType,
            Method[_P, _R_co],
            ViewMethod[_P, _R_co],
        ],
    ) -> Union[ClassViewType, ViewMethod[_P, _R_co]]:
        # Are we decorating a ClassView? If so, annotate the ClassView and return it
        if isinstance(decorated, type):
            if issubclass(decorated, ClassView):
                if '__routes__' not in decorated.__dict__:
                    decorated.__routes__ = []
                decorated.__routes__.append((rule, options))
                if init_app is not None:
                    apps = init_app if isinstance(init_app, tuple) else (init_app,)
                    for each in apps:
                        decorated.init_app(each)
                return decorated
            raise TypeError("@route can only decorate ClassView subclasses")

        if init_app is not None:
            raise TypeError(
                "@route accepts init_app only when decorating a ClassView or ModelView"
            )

        if isinstance(decorated, AsyncViewMethod) or iscoroutinefunction(decorated):
            return AsyncViewMethod(decorated, rule=rule, rule_options=options)
        return ViewMethod(decorated, rule=rule, rule_options=options)

    return decorator


def viewdata(**kwargs: Any) -> ViewDataDecoratorProtocol:
    """
    Decorate a view to add additional data alongside :func:`route`.

    This data is accessible as the ``data`` attribute on the view method. This decorator
    must always be the outermost decorator (barring :func:`route`).
    """

    @overload
    def decorator(decorated: ViewMethod[_P, _R_co]) -> ViewMethod[_P, _R_co]: ...

    @overload
    def decorator(decorated: Method[_P, _R_co]) -> ViewMethod[_P, _R_co]: ...

    def decorator(
        decorated: Union[ViewMethod[_P, _R_co], Method[_P, _R_co]],
    ) -> ViewMethod[_P, _R_co]:
        if isinstance(decorated, AsyncViewMethod) or iscoroutinefunction(decorated):
            return AsyncViewMethod(decorated, data=kwargs)
        return ViewMethod(decorated, data=kwargs)

    return decorator


def rulejoin(class_rule: str, method_rule: str) -> str:
    """
    Join URL paths from routing rules on a class and its methods.

    Used internally by :class:`ClassView` to combine rules from the :func:`route`
    decorators on the class and on the individual view methods::

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


class ViewMethod(Generic[_P, _R_co]):
    """Internal object created by the :func:`route` and :func:`viewdata` decorators."""

    # No __slots__ in ViewMethod because it mimics a wrapped function and must reproduce
    # its attrs __name__, __module__ and __doc__ in the instance, which conflict with
    # class attributes

    #: The name of this view method, derived from the wrapped function
    __name__: str
    #: Template-accessible name, same as :attr:`__name__`
    name: str
    #: The unmodified wrapped method, made available for future decorators
    __func__: Callable[Concatenate[Any, _P], Any]
    #: The wrapped method with the class's :attr:`~ClassView.__decorators__` applied
    decorated_func: Callable
    #: The actual view function registered to Flask, responsible for creating an
    #: instance of the class view and calling :meth:`~ClassView.dispatch_request`
    view_func: Callable
    #: The default endpoint name if not specified in the route
    default_endpoint: str
    #: All endpoint names registered to this view method (populated in :meth:`init_app`)
    endpoints: set[str]

    def __init__(
        self,
        decorated: Union[Method[_P, _R_co], ViewMethod[_P, _R_co]],
        rule: Optional[str] = None,
        rule_options: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> None:
        if rule is not None:
            self.routes = [(rule, rule_options or {})]
        else:
            self.routes = []
        self.data = data or {}
        self.endpoints = set()

        # Are we decorating another ViewMethod? If so, copy routes and func from it.
        if isinstance(decorated, ViewMethod):
            self.routes.extend(decorated.routes)
            # Copy decorated.data, ensuring self.data overrides
            self.data = decorated.data | self.data
            self.__func__ = self.__wrapped__ = func = decorated.__func__
        else:
            self.__func__ = self.__wrapped__ = func = decorated

        self.__doc__ = func.__doc__
        self.__module__ = func.__module__

        # These may change in __set_name__
        self.__name__ = self.name = func.__name__
        self.__qualname__ = func.__qualname__
        self.default_endpoint = self.__qualname__.replace('.', '_')

    def __repr__(self) -> str:
        return f'<ViewMethod {self.__qualname__}>'

    def replace(
        self,
        __f: Union[ViewMethod[_P2, _R2_co], Method[_P2, _R2_co]],
    ) -> ViewMethod[_P2, _R2_co]:
        """
        Replace a view method in a subclass while keeping its URL routes.

        To be used when a subclass needs a custom implementation::

            class CrudView:
                @route('delete', methods=['GET', 'POST'])
                def delete(self): ...


            @route('/<doc>')
            class MyModelView(CrudView, ModelView[MyModel]):
                @route('remove', methods=['GET', 'POST'])  # Add another route
                @CrudView.delete.replace  # Keep the existing 'delete' route
                def delete(self):
                    super().delete()  # Call into base class's implementation if needed
        """
        # Get the class, telling static type checkers to ignore generic type binding...
        cls = cast(type[ViewMethod], self.__class__)
        # ...then bind to the replacement generic types and use it
        r: ViewMethod[_P2, _R2_co] = cls(__f, data=self.data)
        r.routes = self.routes
        return r

    def copy(self) -> Self:
        """Make a copy of this ViewMethod, for use in a subclass."""
        return self.__class__(self)

    def with_route(self, rule: str, **options: Any) -> Self:
        """
        Make a copy of this ViewMethod with an additional route.

        To be used when a subclass needs an additional route, but doesn't need a new
        implementation. This can also be used to provide a base implementation with no
        routes::

            class CrudView:
                @route('delete', methods=['GET', 'POST'])
                def delete(self): ...

                @viewdata()  # This creates a ViewMethod with no routes
                def latent(self): ...


            @route('/<doc>')
            class MyModelView(CrudView, ModelView[MyModel]):
                delete = CrudView.delete.with_route('remove', methods=['GET', 'POST'])
                latent = CrudView.latent.with_route('latent')
        """
        return self.__class__(self, rule=rule, rule_options=options)

    def with_data(self, **data: Any) -> Self:
        """
        Make a copy of this ViewMethod with additional data.

        See :meth:`with_route` for usage notes. This method adds or replaces data
        instead of adding a URL route.
        """
        return self.__class__(self, data=data)

    @overload
    def __get__(self, obj: None, cls: Optional[type[Any]] = None) -> Self: ...

    @overload
    def __get__(
        self, obj: Any, cls: Optional[type[Any]] = None
    ) -> ViewMethodBind[_P, _R_co]: ...

    def __get__(
        self, obj: Optional[Any], cls: Optional[type[Any]] = None
    ) -> Union[Self, ViewMethodBind[_P, _R_co]]:
        if obj is None:
            return self
        bind = ViewMethodBind(self, obj)
        if '__slots__' not in cls.__dict__:
            # Cache it in the instance obj for repeat access. Since we are a non-data
            # descriptor (no __set__ or __delete__ methods), the instance dict will have
            # first priority for future lookups
            setattr(obj, self.__name__, bind)
        return bind

    def __call__(  # pylint: disable=no-self-argument
        __self,  # noqa: N805
        self: ClassViewSubtype,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> _R_co:
        # Mimic an unbound method call
        return __self.__func__(self, *args, **kwargs)

    def is_available(self) -> bool:
        """
        Indicate whether this view is available in the current context.

        This always returns `False` on the unbound :class:`ViewMethod`. The bound
        implementation is in :meth:`ViewMethodBind.is_available`.
        """
        return False

    def __set_name__(self, owner: type[ClassViewSubtype], name: str) -> None:
        # `name` is almost always the existing value acquired from decorated.__name__,
        # the exception being when the view function is defined outside the class:
        #
        # def external_view(self):
        #     ...
        # class MyView(ClassView):
        #     internal_view = ViewMethod(external_view)
        self.__name__ = self.name = name
        self.__qualname__ = qualname = f'{owner.__qualname__}.{name}'
        # We can't use `.` as a separator because Flask uses that to identify blueprint
        # endpoints. Instead we use `_`, as in `ViewClass_method_name`
        self.default_endpoint = qualname.replace('.', '_')

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
        decorated_func = self.__func__
        for base in reversed(owner.__mro__):
            if '__decorators__' in base.__dict__:
                for decorator in reversed(base.__dict__['__decorators__']):
                    decorated_func = decorator(decorated_func)
                    decorated_func.__name__ = name  # See below for why

        self.decorated_func = decorated_func

        if iscoroutinefunction(self.__func__) and not iscoroutinefunction(
            decorated_func
        ):
            raise TypeError(
                f"{self.__qualname__} is async, but one of the decorators is not"
            )

        if iscoroutinefunction(decorated_func):

            async def view_func(**view_args: Any) -> BaseResponse:
                """
                Dispatch Flask/Quart view.

                This function creates an instance of the view class, then calls
                :meth:`~ViewClass.async_dispatch_request` on it passing in
                :attr:`decorated_func`.
                """
                # Instantiate the view class. We depend on its __init__ requiring no
                # args
                viewinst = owner()
                # Declare ourselves (the AsyncViewMethod) as the current view. The bind
                # makes equivalence tests possible, such as ``self.current_method ==
                # self.index``
                viewinst.current_method = AsyncViewMethodBind(self, viewinst)
                # Place view arguments in the instance, in case they are needed outside
                # the dispatch process
                viewinst.view_args = view_args
                # Place the view instance on the app context for :obj:`current_view` to
                # discover
                if app_ctx:
                    app_ctx.current_view = viewinst  # type: ignore[union-attr]
                # Call the view class's dispatch method. View classes can customise this
                # for desired behaviour.
                return await viewinst.async_dispatch_request(decorated_func, view_args)

        else:

            def view_func(**view_args: Any) -> BaseResponse:  # type: ignore[misc]
                """
                Dispatch Flask/Quart view.

                This function creates an instance of the view class, then calls
                :meth:`~ViewClass.dispatch_request` on it passing in
                :attr:`decorated_func`.
                """
                # Instantiate the view class. We depend on its __init__ requiring no
                # args
                viewinst = owner()
                # Declare ourselves (the ViewMethod) as the current view. The bind makes
                # equivalence tests possible, such as ``self.current_method ==
                # self.index``
                viewinst.current_method = ViewMethodBind(self, viewinst)
                # Place view arguments in the instance, in case they are needed outside
                # the dispatch process
                viewinst.view_args = view_args
                # Place the view instance on the app context for :obj:`current_view` to
                # discover
                if app_ctx:
                    app_ctx.current_view = viewinst  # type: ignore[union-attr]
                # Call the view class's dispatch method. View classes can customise this
                # for desired behaviour.
                return viewinst.dispatch_request(decorated_func, view_args)

        # Make view_func resemble the decorated function...
        view_func = update_wrapper(view_func, decorated_func)
        # ...but give view_func the name of the method in the class.
        # This name will differ from self.__func__.__name__ only if the view method
        # was defined outside the class and then added to the class with a different
        # name:
        #
        #     @route('')
        #     def external_method(self):
        #         ...
        #     class MyView(ClassView): ...
        #         view_method = external_method
        #     assert MyView.view_method.__name__ == 'view_method'
        #     assert MyView.view_method.__func__.__name__ == 'external_method'
        view_func.__name__ = name
        self.view_func = view_func

    def init_app(
        self,
        app: Union[BaseApp, BaseBlueprint],
        cls: type[ClassView],
        callback: Optional[InitAppCallback] = None,
    ) -> None:
        """Register routes for a given app and :class:`ClassView` class."""
        for class_rule, class_options in cls.__routes__:
            if 'endpoint' in class_options:
                raise ValueError(
                    f"{cls} route cannot specify 'endpoint'; it must be per-view"
                )
            for method_rule, method_options in self.routes:
                use_options = dict(class_options)
                use_options.update(method_options)
                endpoint = use_options.pop('endpoint', self.default_endpoint)
                self.endpoints.add(endpoint)
                use_rule = rulejoin(class_rule, method_rule)
                app.add_url_rule(use_rule, endpoint, self.view_func, **use_options)
                if callback:
                    callback(app, use_rule, endpoint, self.view_func, **use_options)


class AsyncViewMethod(ViewMethod[_P, _R_co]):
    """Async variant of :class:`ViewMethod."""

    @overload
    def __get__(self, obj: None, cls: Optional[type[Any]] = None) -> Self: ...

    @overload
    def __get__(
        self, obj: Any, cls: Optional[type[Any]] = None
    ) -> AsyncViewMethodBind[_P, _R_co]: ...

    def __get__(
        self, obj: Optional[Any], cls: Optional[type[Any]] = None
    ) -> Union[Self, AsyncViewMethodBind[_P, _R_co]]:
        if obj is None:
            return self
        bind = AsyncViewMethodBind(self, obj)
        if '__slots__' not in cls.__dict__:
            # Cache it in the instance obj for repeat access. Since we are a non-data
            # descriptor (no __set__ or __delete__ methods), the instance dict will have
            # first priority for future lookups
            setattr(obj, self.__name__, bind)
        return bind

    # pylint: disable=no-self-argument, invalid-overridden-method
    async def __call__(  # type: ignore[override]
        __self,  # noqa: N805
        self: ClassViewSubtype,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> _R_co:
        # Mimic an unbound method call
        return await __self.__func__(self, *args, **kwargs)


class ViewMethodBind(Generic[_P, _R_co]):
    """Wrapper for :class:`ViewMethod` binding it to an instance of the view class."""

    __slots__ = ('__weakref__', '_view_method', '__self__')

    # Provide type hints for proxied attributes
    __name__: str
    name: str
    __qualname__: str
    __module__: str
    __doc__: Optional[str]
    __func__: Callable[Concatenate[Any, _P], Any]
    decorated_func: Callable
    view_func: Callable
    default_endpoint: str
    endpoints: set[str]

    def __init__(
        self,
        view_method: ViewMethod[_P, _R_co],
        view_class_instance: ClassViewSubtype,
        /,
    ) -> None:
        self._view_method = view_method
        # Named `__self__` to ducktype the API for instance methods:
        # https://docs.python.org/3/reference/datamodel.html#instance-methods
        self.__self__ = view_class_instance

    def __repr__(self) -> str:
        return f'<ViewMethodBind {self.__qualname__}>'

    def __call__(self, *args: _P.args, **kwargs: _P.kwargs) -> _R_co:
        # Treat this like a call to the original method and not to the view.
        # As per the __decorators__ spec, we call .__func__, not .decorated_func
        return self._view_method.__func__(self.__self__, *args, **kwargs)

    if not TYPE_CHECKING:
        # Hide the proxy implementation from type checkers, so we only appear to have
        # the members explicitly defined in the class
        def __getattr__(self, name: str) -> Any:
            return getattr(self._view_method, name)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ViewMethodBind):
            return (
                self._view_method == other._view_method
                and self.__self__ == other.__self__
            )
        return NotImplemented

    def is_available(self) -> bool:
        """Indicate whether this view is available in the current context."""
        func = self._view_method.decorated_func
        # If the method has an `is_available` callable in its dict, call it with the
        # view class instance as context (the method's `self` parameter). If not, simply
        # return True. Is it an error for `is_available` to not be a callable, or to
        # expect other arguments.
        return getattr(func, 'is_available', lambda _: True)(self.__self__)


class AsyncViewMethodBind(ViewMethodBind[_P, _R_co]):
    """Wrapper for :class:`ViewMethod` binding it to an instance of the view class."""

    __slots__ = ()

    # pylint: disable=invalid-overridden-method
    async def __call__(  # type: ignore[override]
        self, *args: _P.args, **kwargs: _P.kwargs
    ) -> _R_co:
        # Treat this like a call to the original method and not to the view.
        # As per the __decorators__ spec, we call .__func__, not .decorated_func
        return await self._view_method.__func__(self.__self__, *args, **kwargs)


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
    to the rule specified on each view method. This example produces two view methods,
    for ``/`` and ``/about``. Multiple :func:`route` decorators may be used in both
    places. Any rule options specified on the class become the default for all methods
    in the class.

    The :func:`viewdata` decorator can be used to specify additional data, and may
    appear either before or after the :func:`route` decorator, but only adjacent to it.
    Data specified here is available as the :attr:`data` attribute on the view method,
    or at runtime in templates as ``current_view.current_method.data``.

    :func:`route` on the class also accepts an ``init_app`` parameter, a Flask app,
    Blueprint, or a tuple containing a sequence of apps or blueprints. If specified,
    this will call :meth:`~ClassView.init_app` with the app(s).

    A rudimentary CRUD view collection can be assembled like this::

        @route('/doc/<name>', init_app=app)
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

    See :class:`ModelView` for a better way to build views around a model.
    """

    __slots__ = ('__weakref__', 'current_method', 'view_args')

    # If the class did not get a @route decorator, provide a fallback route
    __routes__: ClassVar[list[tuple[str, RouteRuleOptions]]] = [('', {})]

    #: Track all the views registered in this class
    __views__: ClassVar[Collection[str]] = frozenset()

    #: Subclasses may define decorators here. These will be applied to every
    #: view method in the class, but only when called as a view and not
    #: as a Python method.
    __decorators__: ClassVar[list[Callable[[Callable], Callable]]] = []

    #: Indicates whether meth:`is_available` should simply return `True`
    #: without conducting a test. Subclasses should not set this flag. It will
    #: be set by :meth:`init_app` if any view method is missing an
    #: ``is_available`` callable, as it implies that view is always available.
    is_always_available: ClassVar[bool] = False

    #: When a view is called, this will point to the current view method,
    #: an instance of :class:`ViewMethodBind`.
    current_method: ViewMethodBind

    #: When a view is called, this will be replaced with a dictionary of
    #: arguments to the view.
    view_args: dict[str, Any]

    def __init__(self) -> None:
        self.current_method = None  # type: ignore[assignment]
        self.view_args = {}

    @property
    def current_handler(self) -> ViewMethodBind:
        """Deprecated name for :attr:`current_method`."""
        warnings.warn(
            "current_handler has been renamed to current_method",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.current_method

    def __eq__(self, other: object) -> bool:
        return type(other) is type(self)

    def dispatch_request(
        self, view: Callable[..., ResponseReturnValue], view_args: dict[str, Any]
    ) -> BaseResponse:
        """
        View dispatcher that invokes before and after-view hooks.

        Calls :meth:`before_request`, the view, and then :meth:`after_request`. If
        :meth:`before_request` returns a non-None response, the view is skipped and flow
        proceeds to :meth:`after_request`.

        Generic subclasses may override this to provide a custom flow.
        :class:`ModelView` overrides to insert a model loading phase.

        :param view: View method wrapped in specified decorators. The dispatcher must
            call this
        :param view_args: View arguments, to be passed on to the view method
        """
        # Call the :meth:`before_request` method
        resp = self.before_request()  # pylint: disable=assignment-from-none
        if resp is not None:
            return self.after_request(make_response(resp))
        # Call the view method, then pass the response to :meth:`after_response`
        return self.after_request(make_response(view(self, **view_args)))

    def before_request(self) -> Optional[ResponseReturnValue]:
        """
        Process request before the view method.

        This method is called after the app's ``before_request`` handlers, and before
        the class's view method. Subclasses and mixin classes may define their own
        :meth:`before_request` to pre-process requests. This method receives context via
        `self`, in particular via :attr:`current_method` and :attr:`view_args`.
        """
        return None

    def after_request(self, response: BaseResponse) -> BaseResponse:
        """
        Process response returned by view.

        This method is called with the response from the view method. It must return a
        valid response object. Subclasses and mixin classes may override this to perform
        any necessary post-processing::

            class MyView(ClassView):
                ...

                def after_request(self, response):
                    response = super().after_request(response)
                    ...  # Process here
                    return response

        :param response: Response from the view method
        :return: Response object
        """
        return response

    async def async_dispatch_request(
        self,
        view: Callable[..., Awaitable[ResponseReturnValue]],
        view_args: dict[str, Any],
    ) -> BaseResponse:
        """
        Async view dispatcher that invokes before and after-view hooks.

        Calls :meth:`async_before_request`, the view, and then
        :meth:`async_after_request`. If :meth:`async_before_request` returns a non-None
        response, the view is skipped and flow proceeds to :meth:`async_after_request`.

        Generic subclasses may override this to provide a custom flow.
        :class:`ModelView` overrides to insert a model loading phase.

        :param view: View method wrapped in specified decorators. The dispatcher must
            call this
        :param view_args: View arguments, to be passed on to the view method
        """
        # Call the :meth:`async_before_request` method
        resp = await self.async_before_request()
        if resp is not None:
            return await self.async_after_request(await async_make_response(resp))
        # Call the view method, then pass the response to :meth:`async_after_response`
        return await self.async_after_request(
            await async_make_response(await view(self, **view_args))
        )

    async def async_before_request(self) -> Optional[ResponseReturnValue]:
        """
        Process request before the async view method.

        This method is called after the app's ``before_request`` handlers, and before
        the class's view method. Subclasses and mixin classes may define their own
        :meth:`async_before_request` to pre-process requests. This method receives
        context via `self`, in particular via :attr:`current_method` and
        :attr:`view_args`. The default implementation calls :meth:`before_request`.
        """
        return self.before_request()

    async def async_after_request(self, response: BaseResponse) -> BaseResponse:
        """
        Process response returned by async view.

        This method is called with the response from the view method. It must return a
        valid response object. Subclasses and mixin classes may override this to perform
        any necessary post-processing::

            class MyView(ClassView):
                ...

                async def async_after_request(self, response):
                    response = await super().async_after_request(response)
                    ...  # Process here
                    return response

        The default implementation calls :meth:`after_request`.

        :param response: Response from the view method
        :return: Response object
        """
        return self.after_request(response)

    def is_available(self) -> bool:
        """
        Return `True` if *any* view method in the class is currently available.

        Tests by calling :meth:`ViewMethodBind.is_available` of each view method.
        """
        return self.is_always_available or any(
            getattr(self, _v).is_available() for _v in self.__views__
        )

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
                    if base is not cls:
                        # Copy ViewMethod instances into subclasses. We know an attr
                        # with the same name doesn't exist in the subclass because it
                        # was processed first in the MRO and added to the processed set.
                        attr = attr.copy()
                        setattr(cls, name, attr)
                        attr.__set_name__(cls, name)
                    view_names.add(name)
        cls.__views__ = frozenset(view_names)
        # Set is_always_available attr in the subclass. init_app may change this to
        # True after confirming that any of the view methods __after wrapping__ with
        # local decorators remains always available.
        cls.is_always_available = False
        super().__init_subclass__()

    @classmethod
    def init_app(
        cls,
        app: Union[BaseApp, BaseBlueprint],
        callback: Optional[InitAppCallback] = None,
    ) -> None:
        """
        Register views on an app.

        If :attr:`callback` is specified, it will be called after Flask's
        :meth:`~flask.Flask.add_url_rule`, with app and the same parameters.
        """
        for name in cls.__views__:
            attr = getattr(cls, name)
            attr.init_app(app, cls, callback=callback)
            if not hasattr(attr.decorated_func, 'is_available'):
                cls.is_always_available = True


class ModelView(ClassView, Generic[ModelType]):
    """
    Base class for constructing views around a model.

    Functionality is provided via mixin classes that must precede :class:`ModelView` in
    base class order. Three mixins are provided: :class:`UrlForView`,
    :class:`UrlChangeCheck` and :class:`InstanceLoader`. Sample use::

        @Document.views('main')
        @route('/doc/<document>', init_app=app)
        class DocumentView(UrlForView, InstanceLoader, ModelView):
            model = Document
            route_model_map: ClassVar = {
                'document': 'name',
            }

            @route('')
            @render_with(json=True)
            def view(self):
                return self.obj.current_access()

    Views will not receive view arguments, unlike in :class:`ClassView`. If necessary,
    they are available as `self.view_args`.
    """

    # Place obj in slots for potentially faster access at runtime
    __slots__ = ('obj',)

    if TYPE_CHECKING:
        # Pretend `model` is an instance-var for type-checking, as a classvar cannot be
        # bound to a generic arg
        model: type[ModelType]
    else:
        #: The model that is being handled by this ModelView (auto-set from Generic arg)
        model: ClassVar[type[ModelType]]

    #: A loaded object of the model's type
    obj: ModelType

    route_model_map: ClassVar[dict[str, str]] = {}
    """
    A mapping of URL rule variables to attributes on the model. For example, if the URL
    rule is ``/<parent>/<document>``, the attribute map can be::

        model = MyModel  # This is auto-inserted when using ModelView[MyModel]
        obj: MyModel  # This is auto-inserted when using ModelView[MyModel]
        route_model_map: ClassVar = {
            'document': 'name',       # Map 'document' in URL to obj.name
            'parent': 'parent.name',  # Map 'parent' to obj.parent.name
            }

    The :class:`UrlForView` mixin will register
    :class:`~coaster.sqlalchemy.mixins.UrlForMixin` actions using these attribute
    references to construct URLs from the object, while :class:`InstanceLoader`
    (deprecated) will do the reverse to construct a SQLAlchemy query to load the object.
    Since the values in this mapping are a domain-specific language (DSL), this is
    incompatible with type hinting. For type hinting support, use the
    :class:`~ModelView.GetAttr` class approach.
    """

    class GetAttr:
        """
        An alternative to :attr:`~ModelView.route_model_map` with type hinting support.

        All methods in this class must be static or class methods. The methods must have
        the same name as the view variable, and must accept an instance of the object as
        the first and only positional parameter. Example::

            @route('/<parent>/<document>')
            class MyModelView(ModelView[MyModel]):
                class GetAttr:
                    @staticmethod
                    def parent(obj: MyModel) -> str:
                        return obj.parent.name

                    @staticmethod
                    def document(obj: MyModel) -> str:
                        return obj.name

        The :attr:`~ModelView.route_model_map` dict and :class:`~ModelView.GetAttr`
        class can be used together in the same view, with the class taking priority.
        ``GetAttr`` in a subclass will override the base class unless explicitly
        subclassed::

            class Mixin:
                class GetAttr: ...


            class MyModelView(Mixin, ModelView[MyModel]):
                class GetAttr(Mixin.GetAttr): ...

        :class:`~ModelView.GetAttr` is verbose but its utility shows in static type
        checking and code refactoring.
        """

    def __init__(self, obj: Optional[ModelType] = None) -> None:
        """
        Instantiate ModelView with an optional object.

        This is typically used when bypassing :meth:`load`, such as when used with a
        registry::

            @MyModel.views('main')
            class MyModelView(ModelView[MyModel]): ...


            view = obj.views.main()
            # Same as `view = MyModelView(obj)`

        This will skip any side-effects in custom :meth:`load` implementations. Place
        those in :meth:`post_load` instead.
        """
        super().__init__()
        if obj is not None:
            self.obj = obj
            self.post_load()

    def __init_subclass__(cls) -> None:
        """Extract model type from generic args and set on cls if unset."""
        if getattr(cls, 'model', None) is None:  # Allow a base/mixin class to set it
            for base in get_original_bases(cls):
                origin_base = get_origin(base)
                if origin_base is ModelView:
                    (model_type,) = get_args(base)
                    if model_type is not Any:
                        cls.model = model_type
                    break
        super().__init_subclass__()

    def __eq__(self, other: object) -> bool:
        return isinstance(other, self.__class__) and other.obj == self.obj

    def dispatch_request(
        self, view: Callable[..., ResponseReturnValue], view_args: dict[str, Any]
    ) -> BaseResponse:
        """
        Dispatch a view.

        Calls :meth:`before_request`, :meth:`load`, the view, and then
        :meth:`after_request`.

        If :meth:`before_request` or :meth:`load` return a non-None response, it will
        skip ahead to :meth:`after_request`, allowing either of these to override the
        view.

        :param view: View method wrapped in specified decorators
        :param dict view_args: View arguments, to be passed on to :meth:`load` but not
            to the view
        """
        # Call the :meth:`before_request` method
        resp = self.before_request()  # pylint: disable=assignment-from-none
        if resp is not None:
            return self.after_request(make_response(resp))
        # Load the database model
        resp = self.load(**view_args)
        if resp is not None:
            return self.after_request(make_response(resp))
        # Trigger post-load processing of the object
        self.post_load()
        # Call the view method, then pass the response to :meth:`after_response`
        return self.after_request(make_response(view(self)))

    async def async_dispatch_request(
        self,
        view: Callable[..., Awaitable[ResponseReturnValue]],
        view_args: dict[str, Any],
    ) -> BaseResponse:
        """
        Dispatch an async view.

        Calls :meth:`before_request`, :meth:`load`, the view, and then
        :meth:`after_request`.

        If :meth:`before_request` or :meth:`load` return a non-None response, it will
        skip ahead to :meth:`after_request`, allowing either of these to override the
        view.

        :param view: View method wrapped in specified decorators
        :param dict view_args: View arguments, to be passed on to :meth:`load` but not
            to the view
        """
        # Call the :meth:`before_request` method (optionally async)
        resp = await self.async_before_request()
        if resp is not None:
            # If it had a response, skip the view and call after_request, then return
            return await self.async_after_request(await async_make_response(resp))
        # Load the database model
        resp = await self.async_load(**view_args)
        if resp is not None:
            return await self.async_after_request(await async_make_response(resp))
        # Trigger post-load processing of the object
        self.post_load()
        # Call the view method, then pass the response to :meth:`async_after_response`
        return await self.async_after_request(
            await async_make_response(await view(self))
        )

    if TYPE_CHECKING:
        # Type-checking version without arg-spec to let subclasses specify explicit args
        loader: Callable[..., ModelType]

    else:
        # Actual default implementation has variadic arguments
        def loader(self, **__view_args) -> ModelType:  # pragma: no cover
            """
            Load database object and return it.

            Subclasses or mixin classes must override this method to provide a model
            instance loader. The return value of this method will be placed at
            ``self.obj``.

            An implementation that returns an interim object for further processing in
            :meth:`after_loader` should instead override :meth:`load` so that
            :attr:`obj` can be declared to be a well defined type.

            :return: Object instance loaded from database
            """
            raise NotImplementedError("View class is missing a loader method")

    if TYPE_CHECKING:
        # Type-checking version without arg-spec to let subclasses specify explicit args
        load: Callable[..., Optional[ResponseReturnValue]]

    else:
        # Actual default implementation has variadic arguments
        def load(self, **__view_args) -> Optional[ResponseReturnValue]:
            """
            Load the database object given view parameters.

            The default implementation calls :meth:`loader` and sets the return value as
            :attr:`obj`. It then calls :meth:`after_loader` to process this object. This
            behaviour is considered legacy as an implementation that processes interim
            objects like redirects cannot ascribe a clear data type to :attr:`obj`.

            New implementations must override :meth:`load` and be responsible for
            setting :attr:`obj`.
            """
            self.obj = self.loader(**__view_args)
            return self.after_loader()

    if TYPE_CHECKING:
        # Type-checking version without arg-spec to let subclasses specify explicit args
        async_load: Callable[..., Coroutine[Any, Any, Optional[ResponseReturnValue]]]

    else:
        # Actual default implementation has variadic arguments
        async def async_load(self, **__view_args) -> Optional[ResponseReturnValue]:
            """
            Load the database object given view parameters.

            The default implementation calls :meth:`load`. Subclasses should override
            this to make an actual async implementation.
            """
            return self.load(**__view_args)

    def after_loader(  # pylint: disable=useless-return
        self,
    ) -> Optional[ResponseReturnValue]:
        """Process loaded value after :meth:`loader` is called (deprecated)."""
        return None

    def post_load(self) -> None:
        """
        Optionally post-process after :meth:`load` or direct init with an object.

        Subclasses may override this to post-process as necessary. The default
        implementation adds support for retrieving available permissions from
        :class:`~coaster.sqlalchemy.mixins.PermissionMixin` and storing them in
        :class:`~coaster.auth.current_auth`, but only if the view method has the
        :func:`~coaster.views.decorators.requires_permission` decorator. Overriding
        implementations should call `super().post_load()` if this decorator is in use.
        """
        # Determine permissions available on the object for the current actor,
        # but only if the view method has a requires_permission decorator
        if self.current_method and hasattr(
            self.current_method.decorated_func, 'requires_permission'
        ):
            if isinstance(self.obj, tuple):
                perms: Any = None
                for subobj in self.obj:
                    if isinstance(subobj, PermissionMixin):
                        perms = subobj.permissions(current_auth.actor, perms)
                perms = InspectableSet(perms)
            elif isinstance(self.obj, PermissionMixin):
                # current_permissions always returns an InspectableSet
                perms = self.obj.current_permissions
            else:
                perms = InspectableSet()
            add_auth_attribute('permissions', perms)


ModelViewType = TypeVar('ModelViewType', bound=ModelView)


def requires_roles(
    roles: set[str],
) -> Callable[[Callable[_P, _R_co]], Callable[_P, _R_co]]:
    """Decorate to require specific roles in a :class:`ModelView` view."""

    def decorator(f: Callable[_P, _R_co]) -> Callable[_P, _R_co]:
        def is_available_here(context: ModelViewType) -> bool:
            return context.obj.roles_for(
                current_auth.actor, current_auth.anchors
            ).has_any(roles)

        def is_available(context: ModelViewType) -> bool:
            result = is_available_here(context)
            if result and hasattr(f, 'is_available'):
                # We passed, but we're wrapping another test, so ask there as well
                return f.is_available(context)
            return result

        def validate(context: ModelViewType) -> None:
            add_auth_attribute('login_required', True)
            if not is_available_here(context):
                abort(403)

        if iscoroutinefunction(f):

            @wraps(f)
            async def async_wrapper(*args: _P.args, **kwargs: _P.kwargs) -> Any:
                validate(args[0])  # type: ignore[type-var]
                return await f(*args, **kwargs)

            # Fix return type hint
            wrapper = cast(Callable[_P, _R_co], async_wrapper)
        else:

            @wraps(f)
            def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R_co:
                validate(args[0])  # type: ignore[type-var]
                return f(*args, **kwargs)

        wrapper.requires_roles = roles  # type: ignore[attr-defined]
        wrapper.is_available = is_available  # type: ignore[attr-defined]
        return wrapper

    return decorator


class UrlForView:
    """
    Mixin class that registers view methods as view actions on the model.

    This mixin must be used with :class:`ModelView`, and the model must be based on
    :class:`~coaster.sqlalchemy.mixins.UrlForMixin`.
    """

    __slots__ = ()

    @classmethod
    def init_app(
        cls,
        app: Union[BaseApp, BaseBlueprint],
        callback: Optional[InitAppCallback] = None,
    ) -> None:
        """Register view on an app."""

        def register_view_on_model(
            cls: type[ModelView],
            callback: Optional[InitAppCallback],
            app: Union[BaseApp, BaseBlueprint],
            rule: str,
            endpoint: str,
            view_func: Callable,
            **options: Any,
        ) -> None:
            def register_paths_from_app(
                reg_app: BaseApp,
                reg_rule: str,
                reg_endpoint: str,
                reg_options: dict[str, Any],
            ) -> None:
                model = cls.model
                assert issubclass(model, UrlForMixin)  # nosec B101  # noqa: S101
                # Only pass in the attrs that are included in the rule.
                # 1. Extract list of variables from the rule
                rulevars = _get_arguments_from_rule(
                    reg_rule, reg_endpoint, reg_options, reg_app.url_map
                )
                # Make a subset of cls.GetAttr and cls.route_model_map with the required
                # variables
                try:
                    params = {
                        v: (
                            getattr(cls.GetAttr, v)
                            if hasattr(cls.GetAttr, v)
                            else cls.route_model_map[v]
                        )
                        for v in rulevars
                    }
                except KeyError as exc:
                    raise TypeError(
                        f"View variable {exc.args[0]} missing in both"
                        f" {cls.__qualname__}.GetAttr and"
                        f" {cls.__qualname__}.route_model_map"
                    ) from None

                # Register endpoint with the view function's name, endpoint name and
                # parameters
                model.register_endpoint(
                    action=view_func.__name__,
                    endpoint=reg_endpoint,
                    app=reg_app,
                    roles=getattr(view_func, 'requires_roles', None),
                    paramattrs=params,
                )
                model.register_view_for(
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

            if isinstance(app, BaseApp):
                register_paths_from_app(app, rule, endpoint, options)
            elif isinstance(app, BaseBlueprint):
                app.record(blueprint_postprocess)
            else:
                raise TypeError(f"App must be Flask or Blueprint: {app!r}")
            if callback:  # pragma: no cover
                callback(app, rule, endpoint, view_func, **options)

        assert issubclass(cls, ModelView)  # nosec B101  # noqa: S101
        super().init_app(  # type: ignore[misc]
            app, callback=partial(register_view_on_model, cls, callback)
        )


def url_change_check(
    f: Callable[_P, _R_co],
) -> Callable[_P, Union[_R_co, BaseResponse]]:
    """
    Decorate view method in a :class:`ModelView` to check for a change in URL.

    This decorator checks the URL of the loaded object in ``self.obj`` against the URL
    in the request (using ``self.obj.url_for(__name__)``). If the URLs do not match and
    the request is a ``GET``, it issues a HTTP 302 redirect to the correct URL. Usage::

        @route('/doc/<document>')
        class MyModelView(UrlForView, InstanceLoader, ModelView):
            model = MyModel
            route_model_map: ClassVar = {'document': 'url_id_name'}

            @route('')
            @url_change_check
            @render_with(json=True)
            def view(self):
                return self.obj.current_access()

    If the decorator is required for all view methods in the class, use
    :class:`UrlChangeCheck`.

    This decorator will only consider the URLs to be different if:

    * Schemes differ (``http`` vs ``https`` etc)
    * Hostnames differ (apart from a case difference, as user agents use lowercase)
    * Paths differ

    The current URL's query will be copied to the redirect URL. The URL fragment
    (``#target_id``) is not available to the server and will be lost.
    """

    def validate(context: ModelView) -> Optional[BaseResponse]:
        if request.method == 'GET' and getattr(context, 'obj', None) is not None:
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
                return redirect(
                    str(correct_url.set(query=request.query_string.decode()))
                )
        return None

    if iscoroutinefunction(f):

        @wraps(f)
        async def async_wrapper(*args: _P.args, **kwargs: _P.kwargs) -> Any:
            retval = validate(args[0])  # type: ignore[arg-type]
            if retval is not None:
                return retval
            return await f(*args, **kwargs)

        # Fix return type hint
        wrapper = cast(Callable[_P, Union[_R_co, BaseResponse]], async_wrapper)

    else:

        @wraps(f)
        def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> Union[_R_co, BaseResponse]:
            retval = validate(args[0])  # type: ignore[arg-type]
            if retval is not None:
                return retval
            return f(*args, **kwargs)

    return wrapper


class UrlChangeCheck:
    """
    Check for changed URLs in a :class:`ModelView`.

    Mixin class for :class:`ModelView` and :class:`UrlForMixin` that applies the
    :func:`url_change_check` decorator to all view methods. The view class should also
    subclass :class:`UrlForView`, which provides necessary functionality to register
    view actions to the model. Usage::

        @route('/doc/<document>')
        class MyModelView(UrlChangeCheck, UrlForView, InstanceLoader, ModelView):
            model = MyModel
            route_model_map: ClassVar = {'document': 'url_id_name'}

            @route('')
            @render_with(json=True)
            def view(self):
                return self.obj.current_access()
    """

    __slots__ = ()
    __decorators__: ClassVar[list[Callable[[Callable], Callable]]] = [url_change_check]


class InstanceLoader:
    """
    Mixin class for :class:`ModelView` that loads an instance.

    This class provides a :meth:`loader` that attempts to load an instance of the model
    based on attributes in the :attr:`~ModelView.route_model_map` dictionary. It will
    traverse relationships (many-to-one or one-to-one) and perform a SQL ``JOIN`` with
    the target class.

    .. deprecated:: 0.7.0
        This loader cannot process complex joins and the query it produces is not
        cached. Consider implementing a :meth:`~ModelView.loader` method directly, for
        static type checking, easier refactoring, and better performance from query
        caching.
    """

    __slots__ = ()
    route_model_map: ClassVar[dict[str, str]]
    model: ClassVar[type[Any]]
    query: ClassVar[Optional[Query]] = None

    def loader(self, **view_args: Any) -> Any:
        """Load instance based on view arguments."""
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
            return query.one_or_404()
        return None


# --- Proxy ----------------------------------------------------------------------------


def _get_current_view() -> Optional[ClassView]:
    if app_ctx:
        return getattr(app_ctx, 'current_view', None)
    return None


#: A proxy object that holds the currently executing :class:`ClassView` instance, for
#: use in templates as context. Exposed to templates by :func:`coaster.app.init_app`.
#: The current view method within the class is available as
#: :attr:`current_view.current_method`.
current_view: ClassView = cast(ClassView, LocalProxy(_get_current_view))
