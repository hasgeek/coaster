"""
Coaster types
-------------
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, Callable, Optional, Protocol, TypeVar, Union, overload
from typing_extensions import ParamSpec, Self, TypeAlias

WrappedFunc = TypeVar('WrappedFunc', bound=Callable)
ReturnDecorator: TypeAlias = Callable[[WrappedFunc], WrappedFunc]

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

    __name__: str

    # pylint: disable=no-self-argument
    def __call__(__self, self: Any, *args: _P.args, **kwargs: _P.kwargs) -> _R_co: ...

    @overload
    def __get__(self, obj: None, cls: type[_T_contra]) -> Self: ...

    @overload
    def __get__(
        self, obj: _T_contra, cls: type[_T_contra]
    ) -> BoundMethod[_T_contra, _P, _R_co]: ...

    def __get__(
        self, obj: Optional[_T_contra], cls: type[_T_contra]
    ) -> Union[Self, BoundMethod[_T_contra, _P, _R_co]]: ...


class BoundAsyncMethod(Protocol[_T_contra, _P, _R_co]):
    """Protocol for a bound instance method. See :class:`Method` for use."""

    # pylint: disable=no-self-argument
    def __call__(
        __self, self: _T_contra, *args: _P.args, **kwargs: _P.kwargs
    ) -> Awaitable[_R_co]: ...


class AsyncMethod(Protocol[_P, _R_co]):
    """Protocol for an instance method."""

    # pylint: disable=no-self-argument
    def __call__(
        __self, self: Any, *args: _P.args, **kwargs: _P.kwargs
    ) -> Awaitable[_R_co]: ...

    @overload
    def __get__(self, obj: None, cls: type[_T_contra]) -> Self: ...

    @overload
    def __get__(
        self, obj: _T_contra, cls: type[_T_contra]
    ) -> BoundAsyncMethod[_T_contra, _P, _R_co]: ...

    def __get__(
        self, obj: Optional[_T_contra], cls: type[_T_contra]
    ) -> Union[Self, BoundAsyncMethod[_T_contra, _P, _R_co]]: ...


class MethodDecorator(Protocol):
    """Protocol for a transparent method decorator (no change in signature)."""

    @overload
    def __call__(self, __f: AsyncMethod[_P, _T]) -> AsyncMethod[_P, _T]: ...

    @overload
    def __call__(self, __f: Method[_P, _T]) -> Method[_P, _T]: ...

    def __call__(
        self, __f: Union[Method[_P, _T], AsyncMethod[_P, _T]]
    ) -> Union[Method[_P, _T], AsyncMethod[_P, _T]]: ...
