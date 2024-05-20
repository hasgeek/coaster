"""Async compatibility between Flask and Quart."""

# pyright: reportMissingImports=false
# pylint: disable=ungrouped-imports

from __future__ import annotations

import asyncio
import json as _json
from collections.abc import (
    Awaitable,
    Callable,
    Collection,
    Iterator,
    Mapping,
    MutableMapping,
)
from functools import wraps
from inspect import isawaitable, iscoroutinefunction
from types import SimpleNamespace
from typing import (
    IO,
    TYPE_CHECKING,
    Any,
    AnyStr,
    NoReturn,
    Optional,
    TypeVar,
    Union,
    overload,
)
from typing_extensions import Literal, ParamSpec

from asgiref.sync import async_to_sync
from flask import (
    abort as flask_abort,
    current_app as flask_current_app,
    g as flask_g,
    has_request_context as flask_has_request_context,
    make_response as flask_make_response,
    redirect as flask_redirect,
    render_template as flask_render_template,
    render_template_string as flask_render_template_string,
    request as flask_request,
    session as flask_session,
    url_for as flask_url_for,
)
from flask.globals import app_ctx as flask_app_ctx, request_ctx as flask_request_ctx
from flask.json.provider import DefaultJSONProvider
from werkzeug.datastructures import CombinedMultiDict, MultiDict
from werkzeug.wrappers import Response as WerkzeugResponse

# MARK: Gated imports ------------------------------------------------------------------

try:  # Flask >= 3.0
    from flask.sansio.app import App as BaseApp
    from flask.sansio.blueprints import Blueprint as BaseBlueprint, BlueprintSetupState
except ModuleNotFoundError:  # Flask < 3.0
    from flask import Blueprint as BaseBlueprint, Flask as BaseApp
    from flask.blueprints import BlueprintSetupState

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
        abort as quart_abort,
        current_app as quart_current_app,
        g as quart_g,
        has_request_context as quart_has_request_context,
        make_response as quart_make_response,
        redirect as quart_redirect,
        render_template as quart_render_template,
        render_template_string as quart_render_template_string,
        request as quart_request,
        session as quart_session,
        url_for as quart_url_for,
    )
    from quart.globals import app_ctx as quart_app_ctx, request_ctx as quart_request_ctx
except ModuleNotFoundError:
    quart_abort = None  # type: ignore[assignment]
    quart_app_ctx = None  # type: ignore[assignment]
    quart_current_app = None  # type: ignore[assignment]
    quart_g = None  # type: ignore[assignment]
    quart_has_request_context = None  # type: ignore[assignment]
    quart_redirect = None  # type: ignore[assignment]
    quart_render_template = None  # type: ignore[assignment]
    quart_render_template_string = None  # type: ignore[assignment]
    quart_request = None  # type: ignore[assignment]
    quart_request_ctx = None  # type: ignore[assignment]
    quart_session = None  # type: ignore[assignment]
    quart_url_for = None  # type: ignore[assignment]


if TYPE_CHECKING:
    from flask import Flask, Request as FlaskRequest
    from flask.ctx import (
        AppContext as FlaskAppContext,
        RequestContext as FlaskRequestContext,
        _AppCtxGlobals as FlaskAppCtxGlobals,
    )
    from flask.sessions import SessionMixin
    from quart import Quart, Request as QuartRequest, Response as QuartResponse
    from quart.ctx import (
        AppContext as QuartAppContext,
        RequestContext as QuartRequestContext,
        _AppCtxGlobals as QuartAppCtxGlobals,
    )

__all__ = [
    'BaseApp',
    'BaseBlueprint',
    'BaseRequest',
    'BaseResponse',
    'BlueprintSetupState',
    'JSONProvider',
    'abort',
    'app_ctx',
    'async_make_response',
    'async_render_template_string',
    'async_render_template',
    'async_request',
    'current_app_object',
    'current_app',
    'ensure_sync',
    'g',
    'has_request_context',
    'json_dump',
    'json_dumps',
    'json_load',
    'json_loads',
    'json',
    'jsonify',
    'make_response',
    'redirect',
    'render_template_string',
    'render_template',
    'request_ctx',
    'request_ctx',
    'request',
    'session',
    'sync_await',
    'url_for',
]


# MARK: Cross-compatible helpers -------------------------------------------------------


class JSONProvider(DefaultJSONProvider):
    """Expand Flask's JSON provider to support the ``__json__`` protocol."""

    @staticmethod
    def default(o: Any) -> Any:
        """Expand default support to check for a ``__json__`` method."""
        if hasattr(o, '__json__'):
            return o.__json__()
        if isinstance(o, Mapping):
            return dict(o)
        return DefaultJSONProvider.default(o)


class QuartFlaskWrapper:
    """
    Proxy to Quart or Flask source objects.

    This object does not implement any magic methods other than meth:`__bool__` and does
    not resolve API differences.
    """

    __name__: str
    _quart_source: Any
    _flask_source: Any

    def __init__(self, name: str, quart_source: Any, flask_source: Any) -> None:
        object.__setattr__(self, '__name__', name)
        object.__setattr__(self, '_quart_source', quart_source)
        object.__setattr__(self, '_flask_source', flask_source)

    def __bool__(self) -> bool:
        return bool(self._quart_source or self._flask_source)

    def __repr__(self) -> str:
        return (
            f'{self.__class__.__qualname__}'
            f'({self.__name__!r}, {self._quart_source!r}, {self._flask_source!r})'
        )

    def __getattr__(self, name: str) -> Any:
        if qs := self._quart_source:
            return getattr(qs, name)
        return getattr(self._flask_source, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if qs := self._quart_source:
            setattr(qs, name, value)
        setattr(self._flask_source, name, value)

    def __delattr__(self, name: str) -> None:
        if qs := self._quart_source:
            delattr(qs, name)
        delattr(self._flask_source, name)


class QuartFlaskCollectionWrapper(QuartFlaskWrapper):
    """Proxy to Quart or Flask source object with iterable API."""

    def __contains__(self, item: str) -> bool:
        if qs := self._quart_source:
            return item in qs
        return item in self._flask_source

    def __iter__(self) -> Iterator[str]:
        if qs := self._quart_source:
            return iter(qs)
        return iter(self._flask_source)

    def __len__(self) -> int:
        if qs := self._quart_source:
            return len(qs)
        return len(self._flask_source)


Collection.register(QuartFlaskCollectionWrapper)


class QuartFlaskDictWrapper(QuartFlaskCollectionWrapper):
    """Proxy to Quart or Flask source objects with a dict API."""

    def __getitem__(self, key: Any) -> Any:
        if qs := self._quart_source:
            return qs[key]
        return self._flask_source[key]

    def __setitem__(self, key: Any, value: Any) -> None:
        if qs := self._quart_source:
            qs[key] = value
        else:
            self._flask_source[key] = value

    def __delitem__(self, key: Any) -> None:
        if qs := self._quart_source:
            del qs[key]
        else:
            del self._flask_source[key]

    def __eq__(self, other: object) -> bool:
        # Don't return NotImplemented as we should not exist for any reverse operator
        if qs := self._quart_source:
            return qs == other
        return self._flask_source == other

    def __ne__(self, other: object) -> bool:
        # Don't return NotImplemented as we should not exist for any reverse operator
        if qs := self._quart_source:
            return qs != other
        return self._flask_source != other


MutableMapping.register(QuartFlaskDictWrapper)

current_app: Union[Flask, Quart]
current_app = QuartFlaskWrapper(  # type: ignore[assignment]
    'current_app', quart_current_app, flask_current_app
)
app_ctx: Union[FlaskAppContext, QuartAppContext]
app_ctx = QuartFlaskWrapper(  # type: ignore[assignment]
    'app_ctx', quart_app_ctx, flask_app_ctx
)
g: Union[FlaskAppCtxGlobals, QuartAppCtxGlobals]
g = QuartFlaskCollectionWrapper('g', quart_g, flask_g)  # type: ignore[assignment]
request_ctx: Union[FlaskRequestContext, QuartRequestContext]
request_ctx = QuartFlaskWrapper(  # type: ignore[assignment]
    'request_ctx', quart_request_ctx, flask_request_ctx
)
request: Union[FlaskRequest, QuartRequest]
request = QuartFlaskWrapper(  # type: ignore[assignment]
    'request', quart_request, flask_request
)
session: SessionMixin
session = QuartFlaskDictWrapper(  # type: ignore[assignment]
    'session', quart_session, flask_session
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


def url_for(*args, **kwargs) -> str:
    """Wrap Quart and Flask's `url_for` methods."""
    if quart_current_app:
        return quart_url_for(*args, **kwargs)
    return flask_url_for(*args, **kwargs)


def abort(*args, **kwargs) -> NoReturn:
    """Wrap Quart and Flask's `abort` methods."""
    if quart_current_app:
        quart_abort(*args, **kwargs)
    flask_abort(*args, **kwargs)


def redirect(*args, **kwargs) -> Union[WerkzeugResponse, QuartResponse]:
    """Wrap Quart and Flask's `redirect` methods."""
    if quart_current_app:
        return quart_redirect(*args, **kwargs)
    return flask_redirect(*args, **kwargs)


def make_response(*args: Any) -> Union[WerkzeugResponse, QuartResponse]:
    """Make a response, auto-selecting between Quart and Flask."""
    if quart_current_app:
        return sync_await(quart_make_response(*args))
    return flask_make_response(*args)


def render_template(
    template_name_or_list: Union[str, list[str]], **context: Any
) -> str:
    """Render a template, auto-selecting between Quart and Flask."""
    if quart_current_app:
        return sync_await(quart_render_template(template_name_or_list, **context))
    return flask_render_template(
        template_name_or_list,  # type: ignore[arg-type]
        **context,
    )


def render_template_string(source: str, **context: Any) -> str:
    """Render a template string, auto-selecting between Quart and Flask."""
    if quart_current_app:
        return sync_await(quart_render_template_string(source, **context))
    return flask_render_template_string(source, **context)


def json_dumps(object_: Any, **kwargs: Any) -> str:
    if current_app:
        return current_app.json.dumps(object_, **kwargs)
    kwargs.setdefault('default', JSONProvider.default)
    return _json.dumps(object_, **kwargs)


def json_dump(object_: Any, fp: IO[str], **kwargs: Any) -> None:
    if current_app:
        current_app.json.dump(object_, fp, **kwargs)
    else:
        kwargs.setdefault("default", JSONProvider.default)
        _json.dump(object_, fp, **kwargs)


def json_loads(object_: str | bytes, **kwargs: Any) -> Any:
    if current_app:
        return current_app.json.loads(object_, **kwargs)
    return _json.loads(object_, **kwargs)


def json_load(fp: IO[str], **kwargs: Any) -> Any:
    if current_app:
        return current_app.json.load(fp, **kwargs)
    return _json.load(fp, **kwargs)


def jsonify(*args: Any, **kwargs: Any) -> Union[WerkzeugResponse, QuartResponse]:
    return current_app.json.response(*args, **kwargs)  # type: ignore[return-value]


#: Export a consolidated `json` namespace mimicking `flask.json` and `quart.json`
json = SimpleNamespace(
    dumps=json_dumps, dump=json_dump, loads=json_loads, load=json_load, jsonify=jsonify
)

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
        return flask_request.get_data(  # type: ignore[call-overload]
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


async def _coroutine_wrapper(awaitable: Awaitable[_R_co]) -> _R_co:
    return await awaitable


def sync_await(awaitable: Awaitable[_R_co]) -> _R_co:
    """
    Implement await statement in a sync context.

    .. warning::
        This pauses the event loop and may break async code that depends on other
        running tasks (eg, any use of ``asyncio.*``). Only use this to extract a scalar
        return value from an awaitable.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_coroutine_wrapper(awaitable))

    a = awaitable.__await__()
    try:
        # The `for` statement swallows StopIteration, so loop using `while`
        while (v := next(a)) is None:
            pass
        raise RuntimeError(f"Awaitable yielded unexpected value: {v!r}")
    except StopIteration as exc:
        return exc.value
    raise RuntimeError("Iterator did not raise StopIteration")  # pragma: no cover


def ensure_sync(
    func: Union[Callable[_P, Awaitable[_R_co]], Callable[_P, _R_co]],
) -> Callable[_P, _R_co]:
    """Run a possibly-async callable in a sync context."""
    if not callable(func):
        raise TypeError(f"{func!r} is not callable")
    if iscoroutinefunction(func) or iscoroutinefunction(
        getattr(func, '__call__', func)  # noqa: B004
    ):
        return async_to_sync(func)  # type: ignore[arg-type]

    @wraps(func)
    def check_return(*args: _P.args, **kwargs: _P.kwargs) -> _R_co:
        result = func(*args, **kwargs)
        if isawaitable(result):
            return sync_await(result)
        # The typeguard for `isawaitable` doesn't narrow in the negative context, so we
        # need a type-ignore here:
        return result  # type: ignore[return-value]

    return check_return
