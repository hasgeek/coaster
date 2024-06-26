"""Test view helpers."""

# pylint: disable=redefined-outer-name

import unittest
from typing import Any, Optional

import pytest
from flask import Flask
from quart import Quart
from werkzeug.exceptions import BadRequest, Forbidden

from coaster.app import load_config_from_file
from coaster.auth import current_auth
from coaster.compat import json_loads, session
from coaster.views import (
    get_current_url,
    get_next_url,
    jsonp,
    requestargs,
    requestform,
    requestvalues,
    requires_permission,
)


def index() -> str:
    return "index"


def external() -> str:
    return "external"


def somewhere() -> str:
    return "somewhere"


@requires_permission('allow-this')
def permission1() -> str:
    return 'allowed1'


@requires_permission({'allow-this', 'allow-that'})
def permission2() -> str:
    return 'allowed2'


# --- MARK: Tests ----------------------------------------------------------------------


class TestCoasterViews(unittest.TestCase):
    def setUp(self) -> None:
        self.app = Flask(__name__)
        load_config_from_file(self.app, 'settings.py')
        self.app.add_url_rule('/', 'index', index)
        self.app.add_url_rule('/', 'external', external)
        self.app.add_url_rule('/somewhere', 'somewhere')

    def test_get_current_url(self) -> None:
        with self.app.test_request_context('/'):
            assert get_current_url() == '/'

        with self.app.test_request_context('/?q=hasgeek'):
            assert get_current_url() == '/?q=hasgeek'

        self.app.config['SERVER_NAME'] = 'example.com'

        with self.app.test_request_context(
            '/somewhere', environ_overrides={'HTTP_HOST': 'example.com'}
        ):
            assert get_current_url() == '/somewhere'

        with self.app.test_request_context(
            '/somewhere', environ_overrides={'HTTP_HOST': 'sub.example.com'}
        ):
            assert get_current_url() == 'http://sub.example.com/somewhere'

    def test_get_next_url(self) -> None:
        with self.app.test_request_context('/?next=http://example.com'):
            assert get_next_url(external=True) == 'http://example.com'
            assert get_next_url() == '/'
            assert get_next_url(default='default') == 'default'

        with self.app.test_request_context('/'):
            session['next'] = '/next_url'
            assert get_next_url(session=True) == '/next_url'

        with self.app.test_request_context('/?next=Http://example.com'):
            assert get_next_url(external=True) == 'Http://example.com'
            assert get_next_url() == '/'
            assert get_next_url(default='default') == 'default'

        with self.app.test_request_context('/?next=ftp://example.com'):
            assert get_next_url(external=True) == 'ftp://example.com'
            assert get_next_url() == '/'
            assert get_next_url(default='default') == 'default'

        with self.app.test_request_context(
            '/somewhere?next=https://sub.example.com/elsewhere',
            environ_overrides={'HTTP_HOST': 'example.com'},
        ):
            assert get_next_url() == 'https://sub.example.com/elsewhere'
            assert get_next_url(external=True) == 'https://sub.example.com/elsewhere'
            assert (
                get_next_url(default='default') == 'https://sub.example.com/elsewhere'
            )

        with self.app.test_request_context(
            '/somewhere?next=//sub.example.com/elsewhere',
            environ_overrides={'HTTP_HOST': 'example.com'},
        ):
            assert get_next_url() == '//sub.example.com/elsewhere'
            assert get_next_url(external=True) == '//sub.example.com/elsewhere'
            assert get_next_url(default='default') == '//sub.example.com/elsewhere'

    def test_jsonp(self) -> None:
        with self.app.test_request_context('/?callback=callback'):
            kwargs = {'lang': 'en-us', 'query': 'python'}
            r = jsonp(**kwargs)
            assert isinstance(r, self.app.response_class)
            # pylint: disable=consider-using-f-string
            response = (
                'callback({\n  "%s": "%s",\n  "%s": "%s"\n});'  # noqa: UP031
                % ('lang', kwargs['lang'], 'query', kwargs['query'])
            ).encode('utf-8')

            assert response == r.get_data()

        with self.app.test_request_context('/'):
            param1, param2 = 1, 2
            r = jsonp(param1=param1, param2=param2)
            assert isinstance(r, self.app.response_class)
            resp = json_loads(r.get_data())
            assert resp['param1'] == param1
            assert resp['param2'] == param2
            r = jsonp({'param1': param1, 'param2': param2})
            assert isinstance(r, self.app.response_class)
            resp = json_loads(r.get_data())
            assert resp['param1'] == param1
            assert resp['param2'] == param2
            r = jsonp([('param1', param1), ('param2', param2)])
            assert isinstance(r, self.app.response_class)
            resp = json_loads(r.get_data())
            assert resp['param1'] == param1
            assert resp['param2'] == param2

    def test_requires_permission(self) -> None:
        with self.app.test_request_context():
            assert permission1.is_available() is False  # type: ignore[attr-defined]
            assert permission2.is_available() is False  # type: ignore[attr-defined]

            with pytest.raises(Forbidden):
                permission1()
            with pytest.raises(Forbidden):
                permission2()

            assert permission1.is_available() is False  # type: ignore[attr-defined]
            assert permission2.is_available() is False  # type: ignore[attr-defined]

            with pytest.raises(Forbidden):
                permission1()
            with pytest.raises(Forbidden):
                permission2()

            current_auth.permissions |= {'allow-that'}

            assert permission1.is_available() is False  # type: ignore[attr-defined]
            assert permission2.is_available() is True  # type: ignore[attr-defined]

            with pytest.raises(Forbidden):
                permission1()
            assert permission2() == 'allowed2'

            current_auth.permissions |= {'allow-this'}

            assert permission1.is_available() is True  # type: ignore[attr-defined]
            assert permission2.is_available() is True  # type: ignore[attr-defined]

            assert permission1() == 'allowed1'
            assert permission2() == 'allowed2'


@pytest.fixture(scope='module')
def flask_app() -> Flask:
    return Flask(__name__)


@pytest.fixture(scope='module')
def quart_app() -> Quart:
    return Quart(__name__)


# MARK: @requestargs tests -------------------------------------------------------------
# spell-checker:ignore requestargs


@requestvalues('p1', ('p2', int), ('p3[]', int))
def requestvalues_test1(
    p1: str, p2: Optional[int] = None, p3: Optional[list[int]] = None
) -> tuple[Any, ...]:
    return p1, p2, p3


@requestvalues('p1', ('p2', int), 'p3[]')
def requestvalues_test2(
    p1: str, p2: Optional[int] = None, p3: Optional[list[str]] = None
) -> tuple[Any, ...]:
    return p1, p2, p3


@requestvalues('p1', ('p2', int), ('p3[]', int))
def requestvalues_test(
    p1: str, p2: Optional[int] = None, p3: Optional[list[int]] = None
) -> tuple[Any, ...]:
    return p1, p2, p3


@requestform('p1', ('p2', int), ('p3[]', int))
def requestform_test(
    p1: str, p2: Optional[int] = None, p3: Optional[list[int]] = None
) -> tuple[Any, ...]:
    return p1, p2, p3


@requestargs('query1')
@requestform('form1')
def requestcombo_test(query1: str, form1: str) -> tuple[str, str]:
    return query1, form1


@requestvalues('p1', ('p2', int), ('p3[]', int))
async def arequestvalues_test1(
    p1: str, p2: Optional[int] = None, p3: Optional[list[int]] = None
) -> tuple[Any, ...]:
    return p1, p2, p3


@requestvalues('p1', ('p2', int), 'p3[]')
async def arequestvalues_test2(
    p1: str, p2: Optional[int] = None, p3: Optional[list[str]] = None
) -> tuple[Any, ...]:
    return p1, p2, p3


@requestvalues('p1', ('p2', int), ('p3[]', int))
async def arequestvalues_test(
    p1: str, p2: Optional[int] = None, p3: Optional[list[int]] = None
) -> tuple[Any, ...]:
    return p1, p2, p3


@requestform('p1', ('p2', int), ('p3[]', int))
async def arequestform_test(
    p1: str, p2: Optional[int] = None, p3: Optional[list[int]] = None
) -> tuple[Any, ...]:
    return p1, p2, p3


@requestargs('query1')
@requestform('form1')
async def arequestcombo_test(query1: str, form1: str) -> tuple[str, str]:
    return query1, form1


async def test_requestargs(flask_app: Flask, quart_app: Quart) -> None:
    # pylint: disable=no-value-for-parameter
    with flask_app.test_request_context('/?p3=1&p3=2&p2=3&p1=1'):
        assert requestvalues_test1() == ('1', 3, [1, 2])  # type: ignore[call-arg]

    with flask_app.test_request_context(
        '/', method='POST', data={'p3': ['1', '2'], 'p2': '3', 'p1': '1'}
    ):
        assert requestvalues_test1() == ('1', 3, [1, 2])  # type: ignore[call-arg]

    with flask_app.test_request_context('/?p2=2'):
        assert requestvalues_test1(p1='1') == ('1', 2, None)

    with flask_app.test_request_context('/', method='POST', data={'p2': '2'}):
        assert requestvalues_test1(p1='1') == ('1', 2, None)

    with flask_app.test_request_context('/?p2=2'):
        assert requestvalues_test1(p1='1', p2=3) == ('1', 3, None)

    with flask_app.test_request_context('/?p3=1&p3=2&p2=3&p1=1'):
        assert requestvalues_test2() == ('1', 3, ['1', '2'])  # type: ignore[call-arg]

    with flask_app.test_request_context('/?p2=2&p4=4'):
        with pytest.raises(TypeError):
            requestvalues_test1(p4='4')  # type: ignore[call-arg]
        with pytest.raises(BadRequest):
            requestvalues_test1(p4='4')  # type: ignore[call-arg]

    with flask_app.test_request_context('/?p3=1&p3=2&p2=3&p1=1'):
        assert requestvalues_test() == ('1', 3, [1, 2])  # type: ignore[call-arg]

    with flask_app.test_request_context(
        '/', data={'p3': [1, 2], 'p2': 3, 'p1': 1}, method='POST'
    ):
        assert requestform_test() == ('1', 3, [1, 2])  # type: ignore[call-arg]

    with flask_app.test_request_context(
        '/', query_string='query1=foo', data={'form1': 'bar'}, method='POST'
    ):
        assert requestcombo_test() == ('foo', 'bar')  # type: ignore[call-arg]

    with flask_app.test_request_context('/?p3=1&p3=2&p2=3&p1=1'):
        assert await arequestvalues_test1() == ('1', 3, [1, 2])  # type: ignore[call-arg]

    with flask_app.test_request_context(
        '/', method='POST', data={'p3': ['1', '2'], 'p2': '3', 'p1': '1'}
    ):
        assert await arequestvalues_test1() == ('1', 3, [1, 2])  # type: ignore[call-arg]

    with flask_app.test_request_context('/?p2=2'):
        assert await arequestvalues_test1(p1='1') == ('1', 2, None)

    with flask_app.test_request_context('/', method='POST', data={'p2': '2'}):
        assert await arequestvalues_test1(p1='1') == ('1', 2, None)

    with flask_app.test_request_context('/?p2=2'):
        assert await arequestvalues_test1(p1='1', p2=3) == ('1', 3, None)

    with flask_app.test_request_context('/?p3=1&p3=2&p2=3&p1=1'):
        assert await arequestvalues_test2() == ('1', 3, ['1', '2'])  # type: ignore[call-arg]

    with flask_app.test_request_context('/?p2=2&p4=4'):
        with pytest.raises(TypeError):
            await arequestvalues_test1(p4='4')  # type: ignore[call-arg]
        with pytest.raises(BadRequest):
            await arequestvalues_test1(p4='4')  # type: ignore[call-arg]

    with flask_app.test_request_context('/?p3=1&p3=2&p2=3&p1=1'):
        assert await arequestvalues_test() == ('1', 3, [1, 2])  # type: ignore[call-arg]

    with flask_app.test_request_context(
        '/', data={'p3': [1, 2], 'p2': 3, 'p1': 1}, method='POST'
    ):
        assert await arequestform_test() == ('1', 3, [1, 2])  # type: ignore[call-arg]

    with flask_app.test_request_context(
        '/', query_string='query1=foo', data={'form1': 'bar'}, method='POST'
    ):
        assert await arequestcombo_test() == ('foo', 'bar')  # type: ignore[call-arg]

    async with quart_app.test_request_context('/?p3=1&p3=2&p2=3&p1=1'):
        assert requestvalues_test1() == ('1', 3, [1, 2])  # type: ignore[call-arg]

    async with quart_app.test_request_context(
        '/',
        method='POST',
        data='p3=1&p3=2&p2=3&p1=1',
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
    ):
        assert requestvalues_test1() == ('1', 3, [1, 2])  # type: ignore[call-arg]

    async with quart_app.test_request_context('/?p2=2'):
        assert requestvalues_test1(p1='1') == ('1', 2, None)

    async with quart_app.test_request_context('/', method='POST', form={'p2': '2'}):
        assert requestvalues_test1(p1='1') == ('1', 2, None)

    async with quart_app.test_request_context('/?p2=2'):
        assert requestvalues_test1(p1='1', p2=3) == ('1', 3, None)

    async with quart_app.test_request_context('/?p3=1&p3=2&p2=3&p1=1'):
        assert requestvalues_test2() == ('1', 3, ['1', '2'])  # type: ignore[call-arg]

    async with quart_app.test_request_context('/?p2=2&p4=4'):
        with pytest.raises(TypeError):
            requestvalues_test1(p4='4')  # type: ignore[call-arg]
        with pytest.raises(BadRequest):
            requestvalues_test1(p4='4')  # type: ignore[call-arg]

    async with quart_app.test_request_context('/?p3=1&p3=2&p2=3&p1=1'):
        assert requestvalues_test() == ('1', 3, [1, 2])  # type: ignore[call-arg]

    async with quart_app.test_request_context(
        '/',
        data='p3=1&p3=2&p2=3&p1=1',
        method='POST',
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
    ):
        assert requestform_test() == ('1', 3, [1, 2])  # type: ignore[call-arg]

    async with quart_app.test_request_context(
        '/', query_string={'query1': 'foo'}, form={'form1': 'bar'}, method='POST'
    ):
        assert requestcombo_test() == ('foo', 'bar')  # type: ignore[call-arg]

    async with quart_app.test_request_context('/?p3=1&p3=2&p2=3&p1=1'):
        assert await arequestvalues_test1() == ('1', 3, [1, 2])  # type: ignore[call-arg]

    async with quart_app.test_request_context(
        '/',
        method='POST',
        data='p3=1&p3=2&p2=3&p1=1',
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
    ):
        assert await arequestvalues_test1() == ('1', 3, [1, 2])  # type: ignore[call-arg]

    async with quart_app.test_request_context('/?p2=2'):
        assert await arequestvalues_test1(p1='1') == ('1', 2, None)

    async with quart_app.test_request_context('/', method='POST', form={'p2': '2'}):
        assert await arequestvalues_test1(p1='1') == ('1', 2, None)

    async with quart_app.test_request_context('/?p2=2'):
        assert await arequestvalues_test1(p1='1', p2=3) == ('1', 3, None)

    async with quart_app.test_request_context('/?p3=1&p3=2&p2=3&p1=1'):
        assert await arequestvalues_test2() == ('1', 3, ['1', '2'])  # type: ignore[call-arg]

    async with quart_app.test_request_context('/?p2=2&p4=4'):
        with pytest.raises(TypeError):
            await arequestvalues_test1(p4='4')  # type: ignore[call-arg]
        with pytest.raises(BadRequest):
            await arequestvalues_test1(p4='4')  # type: ignore[call-arg]

    async with quart_app.test_request_context('/?p3=1&p3=2&p2=3&p1=1'):
        assert await arequestvalues_test() == ('1', 3, [1, 2])  # type: ignore[call-arg]

    async with quart_app.test_request_context(
        '/',
        data='p3=1&p3=2&p2=3&p1=1',
        method='POST',
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
    ):
        assert await arequestform_test() == ('1', 3, [1, 2])  # type: ignore[call-arg]

    async with quart_app.test_request_context(
        '/', query_string={'query1': 'foo'}, form={'form1': 'bar'}, method='POST'
    ):
        assert await arequestcombo_test() == ('foo', 'bar')  # type: ignore[call-arg]

    # Calling without a request context works as well
    assert requestvalues_test1(p1='1', p2=3, p3=[1, 2]) == ('1', 3, [1, 2])
    assert await arequestvalues_test1(p1='1', p2=3, p3=[1, 2]) == ('1', 3, [1, 2])
