# -*- coding: utf-8 -*-

"""
Model helper registry
---------------------

Provides a :class:`Registry` type and a :class:`RegistryMixin` base class
with two registries, used by other mixin classes.

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

from functools import partial

from sqlalchemy.ext.declarative import declared_attr

__all__ = ['Registry', 'InstanceRegistry', 'RegistryMixin']


class Registry(object):
    """
    Container for items registered to a model.
    """
    def __get__(self, obj, cls=None):
        if obj is None:
            return self
        else:
            return InstanceRegistry(self, obj)


class InstanceRegistry(object):
    """
    Container for accessing registered items from an instance of the model.
    Used internally by :class:`Registry`. Returns a partial that will pass
    in an ``obj`` parameter when called.
    """
    def __init__(self, registry, obj):
        self.__registry = registry
        self.__obj = obj

    def __getattr__(self, attr):
        return partial(getattr(self.__registry, attr), obj=self.__obj)


class RegistryMixin(object):
    """
    Provides the :attr:`forms` and :attr:`views` registries using
    :class:`Registry`. Additional registries, if needed, should be
    added directly to the model class.
    """
    @declared_attr
    def forms(self):
        return Registry()

    @declared_attr
    def views(self):
        return Registry()
