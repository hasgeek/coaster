"""Test `renderwith` view decorator."""

import unittest
from collections.abc import Mapping
from typing import Any

import pytest
from flask import Flask
from jinja2 import TemplateNotFound

from coaster.compat import SansIoResponse, current_app, jsonify
from coaster.views import render_with

# --- Test setup -----------------------------------------------------------------------

app = Flask(__name__)


def viewcallable(data: Mapping[str, Any]) -> SansIoResponse:
    return current_app.response_class(repr(data), mimetype='text/plain')


def anycallable(data) -> SansIoResponse:
    return current_app.response_class(repr(data), mimetype='*/*')


def returns_string(data) -> str:
    return f"Not of Response: {data!r}"


@app.route('/renderedview1')
@render_with('renderedview1.html')
def myview() -> dict[str, str]:
    return {'data': 'value'}


@app.route('/renderedview2')
@render_with(
    {
        'text/html': 'renderedview2.html',
        'text/xml': 'renderedview2.xml',
        'text/plain': viewcallable,
    },
    json=True,
)
def otherview() -> tuple[dict, int]:
    return {'data': 'value'}, 201


@app.route('/renderedview3')
@render_with(
    {
        'text/html': 'renderedview2.html',
        'text/xml': 'renderedview2.xml',
        'text/plain': viewcallable,
    }
)
def onemoreview() -> dict[str, str]:
    return {'data': 'value'}


@app.route('/renderedview4')
@render_with({'text/plain': viewcallable})
def view_for_text() -> tuple[dict, int, dict[str, str]]:
    return {'data': 'value'}, 201, {'Referrer': 'http://example.com'}


@app.route('/renderedview5')
@render_with({'text/plain': returns_string})
def view_for_star() -> tuple[dict, int]:
    return {'data': 'value'}, 201


# --- Tests ----------------------------------------------------------------------------


class TestLoadModels(unittest.TestCase):
    def setUp(self) -> None:
        app.testing = True
        self.client = app.test_client()

    def test_render(self) -> None:
        """Test rendered views."""
        # For this test to pass, the render_view decorator must call render_template
        # with the correct template name. Since the templates don't actually exist,
        # we'll get a TemplateNotFound exception, so our "test" is to confirm that the
        # missing template is the one that was supposed to be rendered.
        with pytest.raises(TemplateNotFound, match='renderedview1.html'):
            self.client.get('/renderedview1')

        for acceptheader, template in [
            ('text/html;q=0.9,text/xml;q=0.8,*/*', 'renderedview2.html'),
            ('text/xml;q=0.9,text/html;q=0.8,*/*', 'renderedview2.xml'),
            (
                'Text/Html,Application/Xhtml+Xml,Application/Xml;Q=0.9,*/*;Q=0.8',
                'renderedview2.html',
            ),
        ]:
            with pytest.raises(TemplateNotFound, match=template):
                self.client.get('/renderedview2', headers=[('Accept', acceptheader)])

        # The application/json and text/plain renderers do exist, so we should get
        # a valid return value from them.
        response = self.client.get(
            '/renderedview2', headers=[('Accept', 'application/json')]
        )
        assert isinstance(response, SansIoResponse)
        assert response.mimetype == 'application/json'
        with app.test_request_context():
            # jsonify needs a request context
            assert response.data == jsonify({"data": "value"}).data
        response = self.client.get('/renderedview2', headers=[('Accept', 'text/plain')])
        assert isinstance(response, SansIoResponse)
        assert response.data.decode('utf-8') == "{'data': 'value'}"
        response = self.client.get('/renderedview3', headers=[('Accept', 'text/plain')])
        assert isinstance(response, SansIoResponse)
        resp = self.client.get('/renderedview4', headers=[('Accept', 'text/plain')])
        assert resp.headers['Referrer'] == "http://example.com"
        # resp = self.app.get('/renderedview5', headers=[('Accept', 'text/plain')])
        # self.assertEqual(resp.status_code, 201)
