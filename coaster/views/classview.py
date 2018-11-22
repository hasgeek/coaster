# -*- coding: utf-8 -*-

"""
Class-based views
-----------------

Group related views into a class for easier management.
"""

from __future__ import unicode_literals
from functools import wraps, update_wrapper
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.orm.mapper import Mapper
from sqlalchemy.orm.properties import RelationshipProperty
from sqlalchemy.orm.descriptor_props import SynonymProperty
from werkzeug.routing import parse_rule
from werkzeug.local import LocalProxy
from flask import _request_ctx_stack, has_request_context, request, redirect, make_response, Blueprint
from ..auth import current_auth, add_auth_attribute

__all__ = [
    'rulejoin', 'current_view',  # Functions
    'ClassView', 'ModelView',  # View base classes
    'route', 'viewdata', 'url_change_check',  # View decorators
    'UrlChangeCheck', 'UrlForView', 'InstanceLoader',  # Mixin classes
    ]

#: A proxy object that holds the currently executing :class:`ClassView` instance,
#: for use in templates as context. Exposed to templates by :func:`coaster.app.init_app`.
#: Note that the current view handler method within the class is named
#: :attr:`~current_view.current_handler`, so to examine it, use :attr:`current_view.current_handler`.
current_view = LocalProxy(lambda: has_request_context() and getattr(_request_ctx_stack.top, 'current_view', None))


# :func:`route` wraps :class:`ViewHandler` so that it can have an independent __doc__
def route(rule, **options):
    """
    Decorator for defining routes on a :class:`ClassView` and its methods.
    Accepts the same parameters that Flask's ``app.``:meth:`~flask.Flask.route`
    accepts. See :class:`ClassView` for usage notes.
    """
    return ViewHandler(rule, rule_options=options)


def viewdata(**kwargs):
    """
    Decorator for adding additional data to a view method, to be used
    alongside :func:`route`. This data is accessible as the ``data``
    attribute on the view handler.
    """
    return ViewHandler(None, viewdata=kwargs)


def rulejoin(class_rule, method_rule):
    """
    Join class and method rules. Used internally by :class:`ClassView` to
    combine rules from the :func:`route` decorators on the class and on the
    individual view handler methods::

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
    else:
        return class_rule + ('' if class_rule.endswith('/') or not method_rule else '/') + method_rule


class ViewHandler(object):
    """
    Internal object created by the :func:`route` and :func:`viewdata` functions.
    """
    def __init__(self, rule, rule_options={}, viewdata={}):
        if rule is not None:
            self.routes = [(rule, rule_options)]
        else:
            self.routes = []
        self.data = viewdata
        self.endpoints = set()

    def reroute(self, f):
        # Use type(self) instead of ViewHandler so this works for (future) subclasses of ViewHandler
        r = type(self)(None)
        r.routes = self.routes
        r.data = self.data
        return r.__call__(f)

    def copy_for_subclass(self):
        # Like reroute, but just a copy
        r = type(self)(None)
        r.routes = self.routes
        r.data = self.data
        r.func = self.func  # Copy func but not wrapped_func, as it will be re-wrapped by init_app
        r.name = self.name
        r.endpoint = self.endpoint
        r.__doc__ = self.__doc__
        r.endpoints = set()
        return r

    def __call__(self, decorated):
        # Are we decorating a ClassView? If so, annotate the ClassView and return it
        if type(decorated) is type and issubclass(decorated, ClassView):
            if '__routes__' not in decorated.__dict__:
                decorated.__routes__ = []
            decorated.__routes__.extend(self.routes)
            return decorated

        # Are we decorating another ViewHandler? If so, copy routes and
        # wrapped method from it.
        elif isinstance(decorated, (ViewHandler, ViewHandlerWrapper)):
            self.routes.extend(decorated.routes)
            newdata = dict(decorated.data)
            newdata.update(self.data)
            self.data = newdata
            self.func = decorated.func

        # If neither ClassView nor ViewHandler, assume it's a callable method
        else:
            self.func = decorated

        self.name = self.func.__name__
        self.endpoint = self.name  # This will change once init_app calls __set_name__
        self.__doc__ = self.func.__doc__
        return self

    # Normally Python 3.6+, but called manually by :meth:`ClassView.init_app`
    def __set_name__(self, owner, name):
        self.name = name
        self.endpoint = owner.__name__ + '_' + self.name

    def __get__(self, obj, cls=None):
        return ViewHandlerWrapper(self, obj, cls)

    def init_app(self, app, cls, callback=None):
        """
        Register routes for a given app and :class:`ClassView` class. At the
        time of this call, we will always be in the view class even if we were
        originally defined in a base class. :meth:`ClassView.init_app`
        ensures this. :meth:`init_app` therefore takes the liberty of adding
        additional attributes to ``self``:

        * :attr:`wrapped_func`: The function wrapped with all decorators added by the class
        * :attr:`view_func`: The view function registered as a Flask view handler
        * :attr:`endpoints`: The URL endpoints registered to this view handler
        """
        def view_func(*args, **kwargs):
            # Instantiate the view class. We depend on its __init__ requiring no parameters
            viewinst = view_func.view_class()
            # Declare ourselves (the ViewHandler) as the current view
            viewinst.current_handler = ViewHandlerWrapper(view_func.view, viewinst, view_func.view_class)
            # Place it on the request stack for :obj:`current_view` to discover
            _request_ctx_stack.top.current_view = viewinst
            # Call the instance's before_request method
            viewinst.before_request(kwargs)
            # Finally, call the view handler method
            return viewinst.after_request(make_response(view_func.wrapped_func(viewinst, *args, **kwargs)))

        # Decorate the wrapped view function with the class's desired decorators.
        # Mixin classes may provide their own decorators, and all of them will be applied.
        # The oldest defined decorators (from mixins) will be applied first, and the
        # class's own decorators last. Within the list of decorators, we reverse the list
        # again, so that a list specified like this:
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
        view_func.wrapped_func = wrapped_func
        view_func.view_class = cls
        view_func.view = self

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
                    callback(use_rule, endpoint, view_func, **use_options)


class ViewHandlerWrapper(object):
    """Wrapper for a view at runtime"""
    def __init__(self, viewh, obj, cls=None):
        self._viewh = viewh
        self._obj = obj
        self._cls = cls

    def __call__(self, *args, **kwargs):
        """Treat this like a call to the method (and not to the view)"""
        # As per the __decorators__ spec, we call .func, not .wrapped_func
        return self._viewh.func(self._obj, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._viewh, name)

    def __eq__(self, other):
        return (isinstance(other, ViewHandlerWrapper) and
            self._viewh == other._viewh and
            self._obj == other._obj and
            self._cls == other._cls)

    def __ne__(self, other):  # pragma: no cover
        return not self.__eq__(other)


class ClassView(object):
    """
    Base class for defining a collection of views that are related to each
    other. Subclasses may define methods decorated with :func:`route`. When
    :meth:`init_app` is called, these will be added as routes to the app.

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

    The :func:`route` decorator on the class specifies the base rule, which is
    prefixed to the rule specified on each view method. This example produces
    two view handlers, for ``/`` and ``/about``. Multiple :func:`route`
    decorators may be used in both places.

    The :func:`viewdata` decorator can be used to specify additional data, and
    may appear either before or after the :func:`route` decorator, but only
    adjacent to it. Data specified here is available as the :attr:`data`
    attribute on the view handler, or at runtime in templates as
    ``current_view.current_handler.data``.

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
    __routes__ = [('', {})]
    #: Track all the views registered in this class
    __views__ = ()
    #: Subclasses may define decorators here. These will be applied to every
    #: view handler in the class, but only when called as a view and not
    #: as a Python method call.
    __decorators__ = []

    #: When a view is called, this will point to the current view handler,
    #: an instance of `ViewHandler`.
    current_handler = None

    def before_request(self, kwargs):
        """
        This method is called after the app's ``before_request`` handlers, and
        before the class's view method. It receives the name of the view
        method, and all keyword arguments that will be sent to the view method.
        Subclasses and mixin classes may define their own
        :meth:`before_request` to pre-process requests.

        :param dict kwargs: Parameters that will be sent to the view handler.
            These are typically parameters from the URL rule
        """
        pass

    def after_request(self, response):
        """
        This method is called with the response from the view handler method.
        It must return a valid response object. Subclasses and mixin classes
        may override this to perform any necessary post-processing::

            class MyView(ClassView):
                ...
                def after_request(self, response):
                    response = super(MyView, self).after_request(response)
                    ...  # Process here
                    return response

        :param response: Response from the view handler method
        :return: Response object
        """
        return response

    @classmethod
    def __get_raw_attr(cls, name):
        for base in cls.__mro__:
            if name in base.__dict__:
                return base.__dict__[name]
        raise AttributeError(name)

    @classmethod
    def add_route_for(cls, _name, rule, **options):
        """
        Add a route for an existing method or view. Useful for modifying routes
        that a subclass inherits from a base class::

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
        setattr(cls, _name, route(rule, **options)(cls.__get_raw_attr(_name)))

    @classmethod
    def init_app(cls, app, callback=None):
        """
        Register views on an app. If :attr:`callback` is specified, it will
        be called after ``app.``:meth:`~flask.Flask.add_url_rule`, with the same
        parameters.
        """
        processed = set()
        cls.__views__ = set()
        for base in cls.__mro__:
            for name, attr in base.__dict__.items():
                if name in processed:
                    continue
                processed.add(name)
                if isinstance(attr, ViewHandler):
                    if base != cls:  # Copy ViewHandler instances into subclasses
                        # TODO: Don't do this during init_app. Use a metaclass
                        # and do this when the class is defined.
                        attr = attr.copy_for_subclass()
                        setattr(cls, name, attr)
                    attr.__set_name__(cls, name)  # Required for Python < 3.6
                    cls.__views__.add(name)
                    attr.init_app(app, cls, callback=callback)


class ModelView(ClassView):
    """
    Base class for constructing views around a model. Functionality is provided
    via mixin classes that must precede :class:`ModelView` in base class order.
    Two mixins are provided: :class:`UrlForView` and :class:`InstanceLoader`.
    Sample use::

        @route('/doc/<document>')
        class DocumentView(UrlForView, InstanceLoader, ModelView):
            model = Document
            route_model_map = {
                'document': 'name'
                }

            @route('')
            @render_with(json=True)
            def view(self, **kwargs):
                return self.obj.current_access()

        DocumentView.init_app(app)

    Views will receive keyword arguments as in :class:`ClassView`, but
    typically will have no use for them if :meth:`loader` works as expected.
    """

    #: The model that this view class represents, to be specified by subclasses.
    model = None
    #: A base query to use if the model needs special handling.
    query = None

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
    route_model_map = {}

    def loader(self, kwargs):  # pragma: no cover
        """
        Subclasses or mixin classes may override this method to provide a model
        instance loader. The return value of this method will be placed at
        ``self.obj``.

        :return: Object instance loaded from database
        """
        pass

    def before_request(self, kwargs):
        """
        :class:`ModelView` overrides :meth:`~ClassView.before_request` to call
        :meth:`loader`. Subclasses overriding this method must use
        :func:`super` to ensure :meth:`loader` is called.
        """
        super(ModelView, self).before_request(kwargs)
        self.obj = self.loader(kwargs)


class UrlForView(object):
    """
    Mixin class for :class:`ModelView` that registers view handler methods with
    :class:`~coaster.sqlalchemy.mixins.UrlForMixin`'s
    :meth:`~coaster.sqlalchemy.mixins.UrlForMixin.is_url_for`.
    """
    @classmethod
    def init_app(cls, app, callback=None):
        def register_view_on_model(rule, endpoint, view_func, **options):
            # Only pass in the attrs that are included in the rule.
            # 1. Extract list of variables from the rule
            rulevars = (v for c, a, v in parse_rule(rule))
            # Make a subset of cls.route_model_map with the required variables
            params = {v: cls.route_model_map[v] for v in rulevars if v in cls.route_model_map}
            # Hook up is_url_for with the view function's name, endpoint name and parameters.
            # Register the view for a specific app, unless we're in a Blueprint,
            # in which case it's not an app.
            # FIXME: The behaviour of a Blueprint + multi-app combo is unknown and needs tests.
            if isinstance(app, Blueprint):
                prefix = app.name + '.'
                reg_app = None
            else:
                prefix = ''
                reg_app = app
            cls.model.is_url_for(view_func.__name__, prefix + endpoint, _app=reg_app, **params)(view_func)
            if callback:  # pragma: no cover
                callback(rule, endpoint, view_func, **options)

        super(UrlForView, cls).init_app(app, callback=register_view_on_model)


def url_change_check(f):
    """
    View method decorator that checks the URL of the loaded object in
    ``self.obj`` against the URL in the request (using
    ``self.obj.url_for(__name__)``). If the URLs do not match,
    and the request is a ``GET``, it issues a redirect to the correct URL.
    Usage::

        @route('/doc/<document>')
        class MyModelView(UrlForView, InstanceLoader, ModelView):
            model = MyModel
            route_model_map = {'document': 'url_id_name'}

            @route('')
            @url_change_check
            @render_with(json=True)
            def view(self, **kwargs):
                return self.obj.current_access()

    If the decorator is required for all view handlers in the class, use
    :class:`UrlChangeCheck`.
    """
    @wraps(f)
    def wrapper(self, *args, **kwargs):
        if request.method == 'GET' and self.obj is not None:
            correct_url = self.obj.url_for(f.__name__, _external=True)
            if correct_url != request.base_url:
                if request.query_string:
                    correct_url = correct_url + '?' + request.query_string.decode()
                return redirect(correct_url)  # TODO: Decide if this should be 302 (default) or 301
        return f(self, *args, **kwargs)
    return wrapper


class UrlChangeCheck(UrlForView):
    """
    Mixin class for :class:`ModelView` and
    :class:`~coaster.sqlalchemy.mixins.UrlForMixin` that applies the
    :func:`url_change_check` decorator to all view handler methods. Subclasses
    :class:`UrlForView`, which it depends on to register the view with the
    model so that URLs can be generated. Usage::

        @route('/doc/<document>')
        class MyModelView(UrlChangeCheck, InstanceLoader, ModelView):
            model = MyModel
            route_model_map = {'document': 'url_id_name'}

            @route('')
            @render_with(json=True)
            def view(self, **kwargs):
                return self.obj.current_access()
    """
    __decorators__ = [url_change_check]


class InstanceLoader(object):
    """
    Mixin class for :class:`ModelView` that provides a :meth:`loader` that
    attempts to load an instance of the model based on attributes in the
    :attr:`~ModelView.route_model_map` dictionary.

    :class:`InstanceLoader` will traverse relationships (many-to-one or
    one-to-one) and perform a SQL ``JOIN`` with the target class.
    """
    def loader(self, kwargs):
        if any((name in self.route_model_map for name in kwargs)):
            # We have a URL route attribute that matches one of the model's attributes.
            # Attempt to load the model instance
            filters = {self.route_model_map[key]: value
                for key, value in kwargs.items()
                if key in self.route_model_map}

            query = self.query or self.model.query
            joined_models = set()
            for name, value in filters.items():
                if '.' in name:
                    # Did we get something like `parent.name`?
                    # Dig into it to find the source column
                    source = self.model
                    for subname in name.split('.'):
                        attr = getattr(source, subname)
                        # Did we get to something like 'parent'?
                        # 1. If it's a synonym, get the attribute it is a synonym for
                        # 2. If it's a relationship, find the source class, join it to
                        # the query, and then continue looking for attributes over there
                        if hasattr(attr, 'original_property') and isinstance(attr.original_property, SynonymProperty):
                            attr = getattr(source, attr.original_property.name)
                        if isinstance(attr, InstrumentedAttribute):
                            if isinstance(attr.property, RelationshipProperty):
                                if isinstance(attr.property.argument, Mapper):
                                    attr = attr.property.argument.class_  # Unlikely to be used. pragma: no cover
                                else:
                                    attr = attr.property.argument
                                if attr not in joined_models:
                                    # SQL JOIN the other model
                                    query = query.join(attr)
                                    # But ensure we don't JOIN twice
                                    joined_models.add(attr)
                        source = attr
                    query = query.filter(source == value)
                else:
                    query = query.filter(getattr(self.model, name) == value)
            obj = query.one_or_404()
            # Determine permissions available on the object for the current actor,
            # but only if the view method has a requires_permission decorator
            if (hasattr(self.current_handler.wrapped_func, 'requires_permission') and
                    hasattr(obj, 'current_permissions')):
                perms = obj.current_permissions
                if hasattr(current_auth, 'permissions'):
                    perms = perms | current_auth.permissions
                add_auth_attribute('permissions', perms)
            return obj
