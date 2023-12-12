"""
Coaster types
-------------
"""

from __future__ import annotations

import typing as t
import typing_extensions as te

#: Type used for functions and methods wrapped in a decorator
WrappedFunc = t.TypeVar('WrappedFunc', bound=t.Callable)
#: Return type for decorator factories
ReturnDecorator = t.Callable[[WrappedFunc], WrappedFunc]

#: Recurring use ParamSpec
_P = te.ParamSpec('_P')
#: Recurring use type spec
_T = t.TypeVar('_T')


class MethodProtocol(te.Protocol[_P, _T]):
    """
    Protocol that matches a method without also matching against a type constructor.

    Replace ``Callable[Concatenate[Any, P], R]`` with ``MethodProtocol[Concatenate[Any,
    P], R]``. This is needed because the typeshed defines ``type.__call__``, so any type
    will also validate as a callable. Mypy special-cases callable protocols as not
    matching ``type.__call__`` in https://github.com/python/mypy/pull/14121.
    """

    # Using ``def __call__`` seems to break Mypy, so we use this hack
    # https://github.com/python/typing/discussions/1312#discussioncomment-4416217
    __call__: t.Callable[te.Concatenate[t.Any, _P], _T]
