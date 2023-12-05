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
P = te.ParamSpec('P')
#: Recurring use type spec
T = t.TypeVar('T')


class MethodProtocol(te.Protocol[P, T]):
    """
    Protocol that matches a method without also matching against a type constructor.

    Replace ``Callable[Concatenate[Any, P], T]`` with ``MethodProtocol[Concatenate[Any,
    P], T]``. This is needed because the typeshed defines ``type.__call__``, so any type
    will also validate as a callable. Mypy special-cases callable protocols as not
    matching ``type.__call__`` in https://github.com/python/mypy/pull/14121.
    """

    # Using ``def __call__`` seems to break Mypy, so we use this hack
    # https://github.com/python/typing/discussions/1312#discussioncomment-4416217
    __call__: t.Callable[te.Concatenate[t.Any, P], T]
