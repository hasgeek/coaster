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
import typing as t

from sqlalchemy.orm import declarative_mixin

__all__ = ['Registry', 'InstanceRegistry', 'RegistryMixin']

_marker = object()


class Registry:
    """Container for items registered to a model."""

    _param: t.Optional[str]
    _name: t.Optional[str]
    _lock: Lock
    _default_property: bool
    _default_cached_property: bool
    _members: t.Set[str]
    _properties: t.Set[str]
    _cached_properties: t.Set[str]

    def __init__(
        self,
        param: t.Optional[str] = None,
        property: bool = False,  # noqa: A002  # pylint: disable=redefined-builtin
        cached_property: bool = False,
    ):
        """Initialize with config."""
        if property and cached_property:
            raise TypeError("Only one of property and cached_property can be True")
        object.__setattr__(self, '_param', str(param) if param else None)
        object.__setattr__(self, '_name', None)
        object.__setattr__(self, '_lock', Lock())
        object.__setattr__(self, '_default_property', property)
        object.__setattr__(self, '_default_cached_property', cached_property)
        object.__setattr__(self, '_members', set())
        object.__setattr__(self, '_properties', set())
        object.__setattr__(self, '_cached_properties', set())

    def __set_name__(self, owner, name):
        """Set a name for this registry."""
        if self._name is None:
            object.__setattr__(self, '_name', name)
        elif name != self._name:
            raise TypeError(
                f"A registry cannot be used under multiple names {self._name} and"
                f" {name}"
            )

    def __setattr__(self, name, value):
        """Incorporate a new registry member."""
        if name.startswith('_'):
            raise ValueError("Registry member names cannot be underscore-prefixed")
        if hasattr(self, name):
            raise ValueError(f"{name} is already registered")
        if not callable(value):
            raise ValueError("Registry members must be callable")
        self._members.add(name)
        object.__setattr__(self, name, value)

    def __call__(  # pylint: disable=redefined-builtin
        self, name=None, property=None, cached_property=None  # noqa: A002
    ):
        """Return decorator to aid class or function registration."""
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

        def decorator(f):
            use_name = name or f.__name__
            setattr(self, use_name, f)
            if use_property:
                self._properties.add(use_name)
            if use_cached_property:
                self._cached_properties.add(use_name)
            return f

        return decorator

    # def __iter__ (here or in instance?)

    def __get__(self, obj, cls=None):
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

    def clear_cache_for(self, obj) -> bool:
        """
        Clear cached instance registry from an object.

        Returns `True` if cache was cleared, `False` if it wasn't needed.
        """
        with self._lock:
            return bool(obj.__dict__.pop(self._name, False))


class InstanceRegistry:
    """
    Container for accessing registered items from an instance of the model.

    Used internally by :class:`Registry`. Returns a partial that will pass
    in an ``obj`` parameter when called.
    """

    def __init__(self, registry, obj):
        """Prepare to serve a registry member."""
        # This would previously be cause for a memory leak due to being a cyclical
        # reference, and would have needed a weakref. However, this is no longer a
        # concern since PEP 442 and Python 3.4.
        self.__registry = registry
        self.__obj = obj

    def __getattr__(self, attr):
        """Access a registry member."""
        registry = self.__registry
        obj = self.__obj
        param = registry._param
        func = getattr(registry, attr)

        # If attr is a property, return the result
        if attr in registry._properties:
            if param is not None:
                return func(**{param: obj})
            return func(obj)

        # If attr is a cached property, cache and return the result
        if attr in registry._cached_properties:
            if param is not None:
                val = func(**{param: obj})
            else:
                val = func(obj)
            setattr(self, attr, val)
            return val

        # Not a property or cached_property. Construct a partial, cache and return it
        if param is not None:
            pfunc = partial(func, **{param: obj})
        else:
            pfunc = partial(func, obj)
        setattr(self, attr, pfunc)
        return pfunc

    def clear_cache(self):
        """Clear cache from this registry."""
        with self.__registry.lock:
            return bool(self.__obj.__dict__.pop(self.__registry.name, False))


@declarative_mixin
class RegistryMixin:
    """
    Adds common registries to a model.

    Included:

    * ``forms`` registry, for WTForms forms
    * ``views`` registry for view classes and helper functions
    * ``features`` registry for feature availability test functions.

    The forms registry passes the instance to the registered form as an ``obj`` keyword
    parameter. The other registries pass it as the first positional parameter.
    """

    forms: t.ClassVar[Registry]
    views: t.ClassVar[Registry]
    features: t.ClassVar[Registry]

    def __init_subclass__(cls, **kwargs) -> None:
        cls.forms = Registry('obj')
        cls.forms.__set_name__(cls, 'forms')
        cls.views = Registry()
        cls.views.__set_name__(cls, 'views')
        cls.features = Registry()
        cls.features.__set_name__(cls, 'features')
        return super().__init_subclass__(**kwargs)
