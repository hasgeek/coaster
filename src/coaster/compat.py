"""Async compatibility between Flask and Quart."""

# pyright: reportMissingImports=false
# pylint: disable=ungrouped-imports

from __future__ import annotations

from collections.abc import Awaitable, Callable
from inspect import isawaitable, iscoroutinefunction
from typing import TYPE_CHECKING, Any, AnyStr, Optional, TypeVar, Union, overload
from typing_extensions import Literal, ParamSpec

from asgiref.sync import async_to_sync
from flask import (
    current_app as flask_current_app,
    g as flask_g,
    has_request_context as flask_has_request_context,
    make_response as flask_make_response,
    render_template as flask_render_template,
    render_template_string as flask_render_template_string,
    request as flask_request,
)
from flask.globals import request_ctx as flask_request_ctx
from werkzeug.datastructures import CombinedMultiDict, MultiDict
from werkzeug.wrappers import Response as WerkzeugResponse

# MARK: Gated imports ------------------------------------------------------------------

try:  # Flask >= 3.0
    from flask.sansio.app import App as BaseApp
    from flask.sansio.blueprints import Blueprint as BaseBlueprint
except ModuleNotFoundError:  # Flask < 3.0
    from flask import Blueprint as BaseBlueprint, Flask as BaseApp

try:  # Werkzeug >= 3.0
    from werkzeug.sansio.request import Request as BaseRequest
    from werkzeug.sansio.response import Response as BaseResponse
except ModuleNotFoundError:  # Werkzeug < 3.0
    # pylint: disable=reimported
    from werkzeug.wrappers import (  # type: ignore[assignment]
        Request as BaseRequest,
        Response as BaseResponse,
    )

try:
    from quart import (
        current_app as quart_current_app,
        g as quart_g,
        has_request_context as quart_has_request_context,
        make_response as quart_make_response,
        render_template as quart_render_template,
        render_template_string as quart_render_template_string,
        request as quart_request,
    )
    from quart.globals import request_ctx as quart_request_ctx
except ModuleNotFoundError:
    quart_current_app = None  # type: ignore[assignment]
    quart_g = None  # type: ignore[assignment]
    quart_request = None  # type: ignore[assignment]
    quart_has_request_context = None  # type: ignore[assignment]
    quart_render_template = None  # type: ignore[assignment]
    quart_render_template_string = None  # type: ignore[assignment]
    quart_request_ctx = None  # type: ignore[assignment]


if TYPE_CHECKING:
    from flask import Flask, Request as FlaskRequest
    from flask.ctx import RequestContext as FlaskRequestContext
    from quart import Quart, Request as QuartRequest, Response as QuartResponse
    from quart.ctx import RequestContext as QuartRequestContext

__all__ = [
    'BaseApp',
    'BaseBlueprint',
    'BaseRequest',
    'BaseResponse',
    'async_render_template_string',
    'async_render_template',
    'async_request',
    'current_app_object',
    'current_app',
    'flask_g',
    'has_request_context',
    'quart_g',
    'request_ctx',
]


# MARK: Cross-compatible helpers -------------------------------------------------------


class QuartFlaskWrapper:
    """
    Proxy to Quart or Flask source objects.

    This object does not implement any magic methods other than meth:`__bool__` and does
    not resolve API differences.
    """

    _quart_source: Any
    _flask_source: Any

    def __init__(self, quart_source: Any, flask_source: Any) -> None:
        object.__setattr__(self, '_quart_source', quart_source)
        object.__setattr__(self, '_flask_source', flask_source)

    def __bool__(self) -> bool:
        return bool(self._quart_source or self._flask_source)

    def __getattr__(self, name: str) -> Any:
        if self._quart_source:
            return getattr(self._quart_source, name)
        return getattr(self._flask_source, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if self._quart_source:
            setattr(self._quart_source, name, value)
        setattr(self._flask_source, name, value)

    def __delattr__(self, name: str) -> None:
        if self._quart_source:
            delattr(self._quart_source, name)
        delattr(self._flask_source, name)


current_app: Union[Flask, Quart]
current_app = QuartFlaskWrapper(  # type: ignore[assignment]
    quart_current_app, flask_current_app
)
request_ctx: Union[FlaskRequestContext, QuartRequestContext]
request_ctx = QuartFlaskWrapper(  # type: ignore[assignment]
    quart_request_ctx, flask_request_ctx
)

request: Union[FlaskRequest, QuartRequest]
request = QuartFlaskWrapper(  # type: ignore[assignment]
    quart_request, flask_request
)


def current_app_object() -> Optional[Union[Flask, Quart]]:
    """Get current app from Quart or Flask (unwrapping the proxy)."""
    # pylint: disable=protected-access
    if quart_current_app:
        return quart_current_app._get_current_object()  # type: ignore[attr-defined]
    if flask_current_app:
        return flask_current_app._get_current_object()  # type: ignore[attr-defined]
    return None


def has_request_context() -> bool:
    """Check for request context in Quart or Flask."""
    return (
        quart_has_request_context is not None and quart_has_request_context()
    ) or flask_has_request_context()


# MARK: Async helpers ------------------------------------------------------------------


class AsyncRequestWrapper:
    """Mimic Quart's async request when operating under Flask."""

    def __bool__(self) -> bool:
        return bool(quart_request or flask_request)

    @property
    async def data(self) -> bytes:
        if quart_request:
            return await quart_request.data
        return flask_request.data

    @overload
    async def get_data(
        self, cache: bool, as_text: Literal[False], parse_form_data: bool
    ) -> bytes: ...

    @overload
    async def get_data(
        self, cache: bool, as_text: Literal[True], parse_form_data: bool
    ) -> str: ...

    @overload
    async def get_data(
        self, cache: bool = True, as_text: bool = False, parse_form_data: bool = False
    ) -> AnyStr: ...

    async def get_data(
        self, cache: bool = True, as_text: bool = False, parse_form_data: bool = False
    ) -> AnyStr:
        if quart_request:
            return await quart_request.get_data(cache, as_text, parse_form_data)
        return flask_request.get_data(  # type: ignore[call-overload, return-value]
            cache, as_text, parse_form_data
        )

    @property
    async def json(self) -> Optional[Any]:
        if quart_request:
            return await quart_request.json
        return flask_request.json

    async def get_json(self) -> Optional[Any]:
        if quart_request:
            return await quart_request.get_json()
        return flask_request.get_json()

    @property
    async def form(self) -> MultiDict:
        if quart_request:
            return await quart_request.form
        return flask_request.form

    @property
    async def files(self) -> MultiDict:
        if quart_request:
            return await quart_request.files
        return flask_request.files

    @property
    async def values(self) -> CombinedMultiDict:
        if quart_request:
            return await quart_request.values
        return flask_request.values

    async def send_push_promise(self, path: str) -> None:
        if quart_request:
            await quart_request.send_push_promise(path)
        # Do nothing if Flask

    async def close(self) -> None:
        if quart_request:
            return await quart_request.close()
        return flask_request.close()

    # Proxy all other attributes to Quart or Flask

    def __getattr__(self, name: str) -> Any:
        if quart_request:
            return getattr(quart_request, name)
        return getattr(flask_request, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if quart_request:
            setattr(quart_request, name, value)
        setattr(flask_request, name, value)

    def __delattr__(self, name: str) -> None:
        if quart_request:
            delattr(quart_request, name)
        delattr(flask_request, name)


async_request = AsyncRequestWrapper()


async def async_make_response(*args: Any) -> Union[WerkzeugResponse, QuartResponse]:
    """Make a response, auto-selecting between Quart and Flask."""
    if quart_current_app:
        return await quart_make_response(*args)
    return flask_make_response(*args)


async def async_render_template(
    template_name_or_list: Union[str, list[str]], **context: Any
) -> str:
    """Async render_template, auto-selecting between Quart and Flask."""
    if quart_current_app:
        return await quart_render_template(template_name_or_list, **context)
    return flask_render_template(
        template_name_or_list,  # type: ignore[arg-type]
        **context,
    )


async def async_render_template_string(source: str, **context: Any) -> str:
    """Async render_template_string, auto-selecting between Quart and Flask."""
    if quart_current_app:
        return await quart_render_template_string(source, **context)
    return flask_render_template_string(source, **context)


# MARK: Async to Sync helpers ----------------------------------------------------------

_P = ParamSpec('_P')
_R_co = TypeVar('_R_co', covariant=True)


@async_to_sync
async def sync_await(awaitable: Awaitable[_R_co]) -> _R_co:
    """Implement await statement in a sync context."""
    return await awaitable


def ensure_sync(
    func: Union[
        Callable[_P, Awaitable[_R_co]],
        Callable[_P, _R_co],
    ],
) -> Callable[_P, _R_co]:
    """Run a possibly-async function in a sync context."""
    if not callable(func):
        raise TypeError("Function is not callable.")
    if iscoroutinefunction(func) or iscoroutinefunction(
        getattr(func, '__call__', func)  # noqa: B004
    ):
        return async_to_sync(func)  # type: ignore[arg-type]

    def check_return(*args: _P.args, **kwargs: _P.kwargs) -> _R_co:
        result = func(*args, **kwargs)
        if isawaitable(result):
            return sync_await(result)
        # The typeguard for isawaitable doesn't narrow in the negative context, so we
        # need a type-ignore here:
        return result  # type: ignore[return-value]

    return check_return
