import unittest

from flask import Flask, Response

from jinja2 import TemplateNotFound

from coaster.views import jsonp, render_with

# --- Test setup --------------------------------------------------------------

app = Flask(__name__)


def viewcallable(data):
    return Response(repr(data), mimetype='text/plain')


def anycallable(data):
    return Response(repr(data), mimetype='*/*')


def returns_string(data):
    return "Not of Response: %s" % repr(data)


@app.route('/renderedview1')
@render_with('renderedview1.html')
def myview():
    return {'data': 'value'}


@app.route('/renderedview2')
@render_with(
    {
        'text/html': 'renderedview2.html',
        'text/xml': 'renderedview2.xml',
        'text/plain': viewcallable,
    },
    jsonp=True,
)
def otherview():
    return {'data': 'value'}, 201


@app.route('/renderedview3')
@render_with(
    {
        'text/html': 'renderedview2.html',
        'text/xml': 'renderedview2.xml',
        'text/plain': viewcallable,
    }
)
def onemoreview():
    return ({'data': 'value'},)


@app.route('/renderedview4')
@render_with({'text/plain': viewcallable})
def view_for_text():
    return {'data': 'value'}, 201, {'Referrer': 'http://example.com'}


@app.route('/renderedview5')
@render_with({'text/plain': returns_string})
def view_for_star():
    return {'data': 'value'}, 201


# --- Tests -------------------------------------------------------------------


class TestLoadModels(unittest.TestCase):
    def setUp(self):
        app.testing = True
        self.app = app.test_client()

    def test_render(self):
        """
        Test rendered views.
        """
        # For this test to pass, the render_view decorator must call render_template
        # with the correct template name. Since the templates don't actually exist,
        # we'll get a TemplateNotFound exception, so our "test" is to confirm that the
        # missing template is the one that was supposed to be rendered.
        try:
            self.app.get('/renderedview1')
        except TemplateNotFound as e:
            assert str(e) == 'renderedview1.html'
        else:
            raise Exception("Wrong template rendered")

        for acceptheader, template in [
            ('text/html;q=0.9,text/xml;q=0.8,*/*', 'renderedview2.html'),
            ('text/xml;q=0.9,text/html;q=0.8,*/*', 'renderedview2.xml'),
            (
                'Text/Html,Application/Xhtml Xml,Application/Xml;Q=0.9,*/*;Q=0.8',
                'renderedview2.html',
            ),
        ]:
            try:
                self.app.get('/renderedview2', headers=[('Accept', acceptheader)])
            except TemplateNotFound as e:
                assert str(e) == template
            else:
                raise Exception("Wrong template rendered")

        # The application/json and text/plain renderers do exist, so we should get
        # a valid return value from them.
        response = self.app.get(
            '/renderedview2', headers=[('Accept', 'application/json')]
        )
        assert isinstance(response, Response)
        with app.test_request_context():  # jsonp requires a request context
            assert response.data == jsonp({"data": "value"}).data
        response = self.app.get('/renderedview2', headers=[('Accept', 'text/plain')])
        assert isinstance(response, Response)
        assert response.data.decode('utf-8') == "{'data': 'value'}"
        response = self.app.get('/renderedview3', headers=[('Accept', 'text/plain')])
        assert isinstance(response, Response)
        resp = self.app.get('/renderedview4', headers=[('Accept', 'text/plain')])
        assert resp.headers['Referrer'] == "http://example.com"
        # resp = self.app.get('/renderedview5', headers=[('Accept', 'text/plain')])
        # self.assertEqual(resp.status_code, 201)
