# -*- coding: utf-8 -*-

"""
Class-based views
-----------------

Group related views into a class for easier management.
"""

from __future__ import unicode_literals
import types

__all__ = ['route', 'ClassView', 'ModelView']


# :func:`route` wraps :class:`ViewDecorator` so that it can have an independent __doc__
def route(rule, **options):
    """
    Decorator for defining routes on a :class:`ClassView` and its methods.
    Accepts the same parameters that Flask's ``app.``:meth:`~flask.Flask.route`
    accepts. See :class:`ClassView` for usage notes.
    """
    return ViewDecorator(rule, **options)


def rulejoin(class_rule, method_rule):
    """
    Join class and method rules::

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
    """
    if method_rule.startswith('/'):
        return method_rule
    else:
        return class_rule + ('' if class_rule.endswith('/') or not method_rule else '/') + method_rule


class ViewDecorator(object):
    """
    Internal object for :func:`route` decorated view methods.
    """
    def __init__(self, rule, **options):
        self.routes = [(rule, options)]

    def reroute(self, f):
        # Use type(self) instead of ViewDecorator so this works for (future) subclasses of ViewDecorator
        r = type(self)('')
        r.routes = self.routes
        return r.__call__(f)

    def __call__(self, decorated):
        # Are we decorating a ClassView? If so, annotate the ClassView and return it
        if type(decorated) is type and issubclass(decorated, ClassView):
            if '__routes__' not in decorated.__dict__:
                decorated.__routes__ = []
            decorated.__routes__.extend(self.routes)
            return decorated

        # Are we decorating another ViewDecorator? If so, copy routes and
        # wrapped method from it.
        elif isinstance(decorated, (ViewDecorator, ViewDecoratorWrapper)):
            self.routes.extend(decorated.routes)
            self.func = decorated.func

        # If neither ClassView nor ViewDecorator, assume it's a callable method
        else:
            self.func = decorated

        self.name = self.__name__ = self.func.__name__
        self.endpoint = self.name  # This will change once init_app calls __set_name__
        self.__doc__ = self.func.__doc__
        return self

    # Normally Python 3.6+, but called manually by :meth:`ClassView.init_app`
    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, obj, cls=None):
        return ViewDecoratorWrapper(self, obj, cls)

    def init_app(self, app, cls, callback=None):
        """
        Register routes for a given app and ClassView subclass
        """
        # Revisit endpoint to account for subclasses
        endpoint = cls.__name__ + '_' + self.name

        # Instantiate the ClassView and call the method with it
        def view_func(*args, **kwargs):
            return view_func.wrapped_func(view_func.view_class(), *args, **kwargs)

        view_func.__name__ = self.__name__
        view_func.__doc__ = self.__doc__
        # Stick `method` and `cls` into view_func to avoid creating a closure.
        view_func.wrapped_func = self.func
        view_func.view_class = cls

        for class_rule, class_options in cls.__routes__:
            for method_rule, method_options in self.routes:
                use_options = dict(method_options)
                use_options.update(class_options)
                endpoint = use_options.pop('endpoint', endpoint)
                use_rule = rulejoin(class_rule, method_rule)
                app.add_url_rule(use_rule, endpoint, view_func, **use_options)
                if callback:
                    callback(use_rule, endpoint, view_func, **use_options)


class ViewDecoratorWrapper(object):
    """Wrapper for a view at runtime"""
    def __init__(self, viewd, obj, cls=None):
        self.__viewd = viewd
        self.__obj = obj
        self.__cls = cls

    def __call__(self, *args, **kwargs):
        return self.__viewd.func(self.__obj, *args, **kwargs)

    def __getattr__(self, attr):
        return getattr(self.__viewd, attr)


class ClassView(object):
    """
    Base class for defining a collection of views that are related to each
    other. Subclasses may define methods decorated with :func:`route`. When
    :meth:`init_app` is called, these will be added as routes to the app.

    Typical use::

        @route('/')
        class IndexView(ClassView):
            @route('')
            def index():
                return render_template('index.html.jinja2')

            @route('about')
            def about():
                return render_template('about.html.jinja2')

        IndexView.init_app(app)

    The :func:`route` decorator on the class specifies the base rule which is
    prefixed to the rule specified on each view method. This example produces
    two view handlers, for ``/`` and ``/about``.

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

    See :class:`ModelView` (TODO) for a better way to build views around a model.
    """
    # If the class did not get a @route decorator, provide a fallback route
    __routes__ = [('', {})]

    @classmethod
    def __get_raw_attr(cls, name):
        for base in cls.__mro__:
            if name in base.__dict__:
                return base.__dict__[name]
        raise AttributeError(name)

    @classmethod
    def add_route_for(cls, _name, rule, **options):
        """
        Add a route for an existing method or view in the class view. Useful
        for modifying routes that a subclass inherits from a base class::

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
        for base in cls.__mro__:
            for name, attr in base.__dict__.items():
                if name in processed:
                    continue
                processed.add(name)
                if isinstance(attr, ViewDecorator):
                    attr.__set_name__(base, name)  # Required for Python < 3.6
                    attr.init_app(app, cls, callback=callback)


class ModelView(ClassView):
    """
    Base class for constructing views around a model. Provides assistance for:

    1. Loading instances based on URL parameters
    2. Registering view handlers for Model.url_for() calls

    TODO
    """
    pass  # TODO
