"""
Coaster types
-------------
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, TypeVar
from typing_extensions import ParamSpec, TypeAlias

WrappedFunc = TypeVar('WrappedFunc', bound=Callable)
ReturnDecorator: TypeAlias = Callable[[WrappedFunc], WrappedFunc]

_P = ParamSpec('_P')
_R_co = TypeVar('_R_co', covariant=True)


class Method(Protocol[_P, _R_co]):
    """Protocol for an instance method."""

    # pylint: disable=no-self-argument
    def __call__(__self, self: Any, *args: _P.args, **kwargs: _P.kwargs) -> _R_co: ...
