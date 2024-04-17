"""
Coaster types
-------------
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, TypeVar, overload
from typing_extensions import ParamSpec, Self

WrappedFunc = TypeVar('WrappedFunc', bound=Callable)
ReturnDecorator = Callable[[WrappedFunc], WrappedFunc]

_P = ParamSpec('_P')
_T = TypeVar('_T')
_T_contra = TypeVar('_T_contra', contravariant=True)
_R_co = TypeVar('_R_co', covariant=True)


class BoundMethod(Protocol[_T_contra, _P, _R_co]):
    """Protocol for a bound instance method. See :class:`Method` for use."""

    # pylint: disable=no-self-argument
    def __call__(
        __self, self: _T_contra, *args: _P.args, **kwargs: _P.kwargs
    ) -> _R_co: ...


class Method(Protocol[_P, _R_co]):
    """Protocol for an instance method."""

    # pylint: disable=no-self-argument
    def __call__(__self, self: Any, *args: _P.args, **kwargs: _P.kwargs) -> _R_co: ...

    @overload
    def __get__(self, obj: None, cls: type[_T]) -> Self: ...

    @overload
    def __get__(self, obj: _T, cls: type[_T]) -> BoundMethod[_T, _P, _R_co]: ...
