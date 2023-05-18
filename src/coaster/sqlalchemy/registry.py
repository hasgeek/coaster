"""
Model helper registry
---------------------

Provides a :class:`Registry` type and a :class:`RegistryMixin` base class
with three registries, used by other mixin classes.

Helper classes such as forms and views can be registered to the model and
later accessed from an instance::

    class MyModel(BaseMixin, db.Model):
        ...

    class MyForm(Form):
        ...

    class MyView(ModelView):
        ...

    MyModel.forms.main = MyForm
    MyModel.views.main = MyView

When accessed from an instance, the registered form or view will receive the
instance as an ``obj`` parameter::

    doc = MyModel()
    doc.forms.main() == MyForm(obj=doc)
    doc.views.main() == MyView(obj=doc)

The name ``main`` is a recommended default, but an app that has separate forms
for ``new`` and ``edit`` actions could use those names instead.
"""

from __future__ import annotations

from functools import partial
from threading import Lock
from typing import overload
import typing as t

from sqlalchemy.orm import declarative_mixin
import typing_extensions as te

from ..typing import ReturnDecorator, WrappedFunc

__all__ = ['Registry', 'InstanceRegistry', 'RegistryMixin']

_marker = object()

_T = t.TypeVar('_T', bound=t.Any)


class Registry(t.Generic[_T]):
    """
    A registry provides a plugin namespace within another class.

    Callables can be added to a registry, and when called via the registry's host
    instance, will receive the instance as a positional or keyword parameter::

        >>> class MyClass:
        ...     def __repr__(self):
        ...         return 'MyClass instance'
        ...     # Define one or more registries, with configuration
        ...     registry1 = Registry()
        ...     registry2 = Registry(kwarg='obj')
        ...     registry3 = Registry(property=True)

        >>> # Add callables to a registry, either via a decorator with config, ...
        >>> @MyClass.registry1()  # name=None, property=False, cached_property=False
        ... @MyClass.registry2('extn')
        ... def plugin(instance=None, obj=None):
        ...     return (repr(instance), repr(obj))

        >>> # ... or add them directly to the registry, using the registry's config for
        >>> # the property and cached_property flags
        >>> MyClass.registry3.plugin_as_property = plugin

        >>> instance = MyClass()
        >>> instance.registry1.plugin()
        ('MyClass instance', 'None')
        >>> instance.registry2.extn()
        ('None', 'MyClass instance')
        >>> instance.registry3.plugin_as_property
        ('MyClass instance', 'None')

    A registry can call its registered callables with the host instance as either the
    first positional argument, or as a keyword argument. Callables can be registered as
    methods or as properties (optionally cached), and may be added directly to the
    registry with setattr, or by using the registry as a decorator to customise options.

    :param kwarg: Call with the host as this keyword argument (default is positional)
    :param property: Register callables as properties
    :param cached_property: Register callables as cached properties
    """

    #: Name of this registry
    _name: t.Optional[str]
    #: A lock for the cache
    _lock: Lock
    #: Default value of the optional kwarg when registering a callable
    _default_kwarg: t.Optional[str]
    #: Default value of the property flag when registering a callable
    _default_property: bool
    #: Default value of the cached_property flag when registering a callable
    _default_cached_property: bool
    #: Dict of registered callable names and their optional kwarg parameter
    _members: t.Dict[str, t.Optional[str]]
    #: Names of callables registered as properties
    _properties: t.Set[str]
    #: Names of callables registered as cached properties
    _cached_properties: t.Set[str]

    def __init__(
        self,
        *,
        kwarg: t.Optional[str] = None,
        property: bool = False,  # noqa: A002  # pylint: disable=redefined-builtin
        cached_property: bool = False,
    ) -> None:
        """Initialize with config."""
        if property and cached_property:
            raise ValueError("Only one of property and cached_property can be True")
        if kwarg is not None and not isinstance(kwarg, str):
            raise TypeError(f"Expected type for kwarg is str|None: {kwarg}")
        if kwarg == '':
            raise ValueError("kwarg parameter cannot be blank")
        object.__setattr__(self, '_default_kwarg', kwarg if kwarg else None)
        object.__setattr__(self, '_name', None)
        object.__setattr__(self, '_lock', Lock())
        object.__setattr__(self, '_default_property', property)
        object.__setattr__(self, '_default_cached_property', cached_property)
        object.__setattr__(self, '_members', {})
        object.__setattr__(self, '_properties', set())
        object.__setattr__(self, '_cached_properties', set())

    def __set_name__(self, owner: t.Any, name: str) -> None:
        """Set a name for this registry."""
        if self._name is None:
            object.__setattr__(self, '_name', name)
        elif name != self._name:
            raise AttributeError(f"This registry is bound to the name {self._name!r}")

    def __setattr__(self, name: str, value: t.Callable) -> None:
        """Incorporate a new registry member after validation."""
        self.__call__(name)(value)

    # types.EllipsisType was only introduced in Python 3.10, so we must silence Mypy
    # for the use of ... as an undeclared sentinel value here
    def __call__(  # pylint: disable=redefined-builtin
        self,
        name: t.Optional[str] = None,
        *,
        kwarg: t.Union[str, None] = ...,  # type: ignore[assignment]
        property: t.Optional[bool] = None,  # noqa: A002  # pylint: disable=W0622
        cached_property: t.Optional[bool] = None,
    ) -> ReturnDecorator:
        """Return decorator to aid class or function registration."""
        use_kwarg = self._default_kwarg if kwarg is ... else kwarg
        use_property = self._default_property if property is None else property
        use_cached_property = (
            self._default_cached_property
            if cached_property is None
            else cached_property
        )
        if use_property and use_cached_property:
            raise TypeError(
                f"Only one of property and cached_property can be True."
                f" Provided: property={property}, cached_property={cached_property}."
                f" Registry: property={self._default_property},"
                f" cached_property={self._default_cached_property}."
                f" Conflicting registry settings must be explicitly set to False."
            )

        def decorator(f: WrappedFunc) -> WrappedFunc:
            use_name = name or f.__name__

            if use_name.startswith('_'):
                raise AttributeError(
                    "Registry member names cannot be underscore-prefixed"
                )
            if hasattr(self, use_name):
                raise AttributeError(f"{use_name} is already registered")
            if not callable(f):
                raise AttributeError("Registry members must be callable")

            self._members[use_name] = use_kwarg
            object.__setattr__(self, use_name, f)
            if use_property:
                self._properties.add(use_name)
            if use_cached_property:
                self._cached_properties.add(use_name)
            return f

        return decorator

    @overload
    def __get__(self, obj: None, cls: t.Optional[t.Type[_T]] = None) -> Registry:
        ...

    @overload
    def __get__(
        self, obj: _T, cls: t.Optional[t.Type[_T]] = None
    ) -> InstanceRegistry[_T]:
        ...

    def __get__(
        self, obj: t.Optional[_T], cls: t.Optional[t.Type[_T]] = None
    ) -> t.Union[Registry, InstanceRegistry[_T]]:
        """Access at runtime."""
        if obj is None:
            return self

        cache = obj.__dict__  # This assumes a class without __slots__
        name = self._name
        with self._lock:
            ir = cache.get(name, _marker)
            if ir is _marker:
                ir = InstanceRegistry(self, obj)
                cache[name] = ir

        # Subsequent accesses will bypass this __get__ method and use the instance
        # that was saved to obj.__dict__
        return ir

    if t.TYPE_CHECKING:
        # Tell Mypy that it's okay for code to attempt reading an attr

        def __getattr__(self, attr: str) -> t.Any:
            ...


class InstanceRegistry(t.Generic[_T]):
    """
    Container for accessing registered items from an instance of the model.

    Used internally by :class:`Registry`. Returns a partial that will pass
    in an ``obj`` parameter when called.
    """

    def __init__(self, registry: Registry[_T], obj: _T):
        """Prepare to serve a registry member."""
        # This would previously be cause for a memory leak due to being a cyclical
        # reference, and would have needed a weakref. However, this is no longer a
        # concern since PEP 442 and Python 3.4.
        self.__registry = registry
        self.__obj = obj

    def __getattr__(self, attr: str) -> t.Any:
        """Access a registry member."""
        registry = self.__registry
        obj = self.__obj
        kwarg = registry._members[attr]
        func = getattr(registry, attr)

        # If attr is a property, return the result
        if attr in registry._properties:
            if kwarg is not None:
                return func(**{kwarg: obj})
            return func(obj)

        # If attr is a cached property, cache and return the result
        if attr in registry._cached_properties:
            if kwarg is not None:
                val = func(**{kwarg: obj})
            else:
                val = func(obj)
            setattr(self, attr, val)
            return val

        # Not a property or cached_property. Construct a partial, cache and return it
        if kwarg is not None:
            pfunc = partial(func, **{kwarg: obj})
        else:
            pfunc = partial(func, obj)
        setattr(self, attr, pfunc)
        return pfunc


@declarative_mixin
class RegistryMixin:
    """
    Adds common registries to a model.

    Included:

    * ``forms`` registry, for WTForms forms
    * ``views`` registry for view classes and helper functions
    * ``features`` registry for feature availability test functions.

    The forms registry passes the instance to the registered form as an ``obj`` keyword
    argument. The other registries pass it as the first positional argument.
    """

    forms: t.ClassVar[Registry[te.Self]]
    views: t.ClassVar[Registry[te.Self]]
    features: t.ClassVar[Registry[te.Self]]

    def __init_subclass__(cls, **kwargs) -> None:
        cls.forms = Registry(kwarg='obj')
        cls.forms.__set_name__(cls, 'forms')
        cls.views = Registry()
        cls.views.__set_name__(cls, 'views')
        cls.features = Registry()
        cls.features.__set_name__(cls, 'features')
        return super().__init_subclass__(**kwargs)
