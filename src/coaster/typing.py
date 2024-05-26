"""Coaster types."""

from __future__ import annotations

from collections.abc import Coroutine
from typing import Any, Callable, Protocol, TypeVar, Union
from typing_extensions import ParamSpec, TypeAlias

WrappedFunc = TypeVar('WrappedFunc', bound=Callable)
ReturnDecorator: TypeAlias = Callable[[WrappedFunc], WrappedFunc]

_P = ParamSpec('_P')
_R_co = TypeVar('_R_co', covariant=True)


class Method(Protocol[_P, _R_co]):
    """Protocol for an instance method (sync or async)."""

    # pylint: disable=no-self-argument
    def __call__(  # noqa: D102,RUF100
        __self,  # noqa: N805
        self: Any,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> Union[Coroutine[Any, Any, _R_co], _R_co]: ...
