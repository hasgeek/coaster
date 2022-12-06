"""
Coaster types
-------------
"""
import typing as t

#: Type used for functions and methods wrapped in a decorator
WrappedFunc = t.TypeVar('WrappedFunc', bound=t.Callable)
#: Return type for decorator factories
ReturnDecorator = t.Callable[[WrappedFunc], WrappedFunc]
