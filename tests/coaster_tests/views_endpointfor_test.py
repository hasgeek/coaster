"""Tests for endpoint_for view helper."""

# pylint: disable=redefined-outer-name

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Union

import pytest
from flask import Flask
from quart import Quart

from coaster.views import endpoint_for


def view() -> str:
    """Test view, never actually called."""
    return "view"


@pytest.fixture(params=['flask', 'quart'])
def app(request: pytest.FixtureRequest) -> Union[Flask, Quart]:
    """Create a Flask or Quart app."""
    app: Union[Flask, Quart]
    server_name = (
        'example.com' if request.node.get_closest_marker('has_server_name') else None
    )
    if request.param == 'quart':
        app = Quart(__name__, subdomain_matching=bool(server_name))
    else:
        app = Flask(__name__, subdomain_matching=bool(server_name))

    if server_name:
        app.config['SERVER_NAME'] = server_name

    # Use `view` as the view function for all routes as it's not actually called
    app.add_url_rule('/', 'index', view)
    app.add_url_rule('/slashed/', 'slashed', view)
    app.add_url_rule('/sub', 'un_subdomained', view)
    app.add_url_rule('/sub', 'subdomained', view, subdomain='<subdomain>')

    return app


@pytest.fixture
async def arequest_ctx(app: Union[Flask, Quart]) -> AsyncIterator[None]:
    """Create an async test request context."""
    if isinstance(app, Flask):
        with app.test_request_context():
            yield None
    else:
        async with app.test_request_context(path='/'):
            yield None


@pytest.mark.usefixtures('arequest_ctx')
async def test_localhost_index() -> None:
    assert endpoint_for('http://localhost/') == ('index', {})


@pytest.mark.usefixtures('arequest_ctx')
async def test_localhost_slashed() -> None:
    assert endpoint_for('http://localhost/slashed/') == ('slashed', {})


@pytest.mark.usefixtures('arequest_ctx')
async def test_localhost_unslashed() -> None:
    assert endpoint_for('http://localhost/slashed') == ('slashed', {})


@pytest.mark.usefixtures('arequest_ctx')
async def test_localhost_unslashed_noredirect() -> None:
    assert endpoint_for('http://localhost/slashed', follow_redirects=False) == (
        None,
        {},
    )


@pytest.mark.usefixtures('arequest_ctx')
async def test_localhost_sub() -> None:
    assert endpoint_for('http://localhost/sub') == ('un_subdomained', {})


@pytest.mark.usefixtures('arequest_ctx')
async def test_example_index() -> None:
    assert endpoint_for('http://example.com/') == ('index', {})


@pytest.mark.usefixtures('arequest_ctx')
async def test_example_slashed() -> None:
    assert endpoint_for('http://example.com/slashed/') == ('slashed', {})


@pytest.mark.usefixtures('arequest_ctx')
async def test_example_unslashed() -> None:
    assert endpoint_for('http://example.com/slashed') == ('slashed', {})


@pytest.mark.usefixtures('arequest_ctx')
async def test_example_unslashed_noredirect() -> None:
    assert endpoint_for('http://example.com/slashed', follow_redirects=False) == (
        None,
        {},
    )


@pytest.mark.usefixtures('arequest_ctx')
async def test_example_sub() -> None:
    assert endpoint_for('http://example.com/sub') == ('un_subdomained', {})


@pytest.mark.usefixtures('arequest_ctx')
async def test_subexample_index() -> None:
    assert endpoint_for('http://sub.example.com/') == ('index', {})


@pytest.mark.usefixtures('arequest_ctx')
async def test_subexample_slashed() -> None:
    assert endpoint_for('http://sub.example.com/slashed/') == ('slashed', {})


@pytest.mark.usefixtures('arequest_ctx')
async def test_subexample_unslashed() -> None:
    assert endpoint_for('http://sub.example.com/slashed') == ('slashed', {})


@pytest.mark.usefixtures('arequest_ctx')
async def test_subexample_unslashed_noredirect() -> None:
    assert endpoint_for('http://sub.example.com/slashed', follow_redirects=False) == (
        None,
        {},
    )


@pytest.mark.usefixtures('arequest_ctx')
async def test_subexample_sub() -> None:
    assert endpoint_for('http://sub.example.com/sub') == ('un_subdomained', {})


@pytest.mark.usefixtures('arequest_ctx')
@pytest.mark.has_server_name
async def test_named_localhost_index() -> None:
    assert endpoint_for('http://localhost/') == (None, {})


@pytest.mark.usefixtures('arequest_ctx')
@pytest.mark.has_server_name
async def test_named_localhost_slashed() -> None:
    assert endpoint_for('http://localhost/slashed/') == (None, {})


@pytest.mark.usefixtures('arequest_ctx')
@pytest.mark.has_server_name
async def test_named_localhost_unslashed() -> None:
    assert endpoint_for('http://localhost/slashed') == (None, {})


@pytest.mark.usefixtures('arequest_ctx')
@pytest.mark.has_server_name
async def test_named_localhost_unslashed_noredirect() -> None:
    assert endpoint_for('http://localhost/slashed', follow_redirects=False) == (
        None,
        {},
    )


@pytest.mark.usefixtures('arequest_ctx')
@pytest.mark.has_server_name
async def test_named_localhost_sub() -> None:
    assert endpoint_for('http://localhost/sub') == (None, {})


@pytest.mark.usefixtures('arequest_ctx')
@pytest.mark.has_server_name
async def test_named_example_index() -> None:
    assert endpoint_for('http://example.com/') == ('index', {})


@pytest.mark.usefixtures('arequest_ctx')
@pytest.mark.has_server_name
async def test_named_example_slashed() -> None:
    assert endpoint_for('http://example.com/slashed/') == ('slashed', {})


@pytest.mark.usefixtures('arequest_ctx')
@pytest.mark.has_server_name
async def test_named_example_unslashed() -> None:
    assert endpoint_for('http://example.com/slashed') == ('slashed', {})


@pytest.mark.usefixtures('arequest_ctx')
@pytest.mark.has_server_name
async def test_named_example_unslashed_noredirect() -> None:
    assert endpoint_for('http://example.com/slashed', follow_redirects=False) == (
        None,
        {},
    )


@pytest.mark.usefixtures('arequest_ctx')
@pytest.mark.has_server_name
async def test_named_example_sub() -> None:
    assert endpoint_for('http://example.com/sub') == ('un_subdomained', {})


@pytest.mark.usefixtures('arequest_ctx')
@pytest.mark.has_server_name
async def test_named_subexample_index() -> None:
    assert endpoint_for('http://sub.example.com/') == (None, {})


@pytest.mark.usefixtures('arequest_ctx')
@pytest.mark.has_server_name
async def test_named_subexample_slashed() -> None:
    assert endpoint_for('http://sub.example.com/slashed/') == (None, {})


@pytest.mark.usefixtures('arequest_ctx')
@pytest.mark.has_server_name
async def test_named_subexample_unslashed() -> None:
    assert endpoint_for('http://sub.example.com/slashed') == (None, {})


@pytest.mark.usefixtures('arequest_ctx')
@pytest.mark.has_server_name
async def test_named_subexample_unslashed_noredirect() -> None:
    assert endpoint_for('http://sub.example.com/slashed', follow_redirects=False) == (
        None,
        {},
    )


@pytest.mark.usefixtures('arequest_ctx')
@pytest.mark.has_server_name
async def test_named_subexample_sub() -> None:
    assert endpoint_for('http://sub.example.com/sub') == (
        'subdomained',
        {'subdomain': 'sub'},
    )
