# -*- coding: utf-8 -*-

import unittest
from flask import Flask, session, request
from werkzeug.exceptions import ClientDisconnected
from coaster.app import load_config_from_file
from coaster.views import get_current_url, get_next_url, jsonp, requestargs


def index():
    return "index"


def external():
    return "external"


@requestargs('p1', ('p2', int), ('p3[]', int))
def f(p1, p2=None, p3=None):
    return p1, p2, p3


class TestCoasterViews(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        load_config_from_file(self.app, "settings.py")
        self.app.add_url_rule('/', 'index', index)
        self.app.add_url_rule('/', 'external', external)

    def test_get_current_url(self):
        with self.app.test_request_context('/'):
            self.assertEqual(get_current_url(), '/')

        with self.app.test_request_context('/?q=hasgeek'):
            self.assertEqual(get_current_url(), '/?q=hasgeek')

    def test_get_next_url(self):
        with self.app.test_request_context('/?next=http://example.com'):
            self.assertEqual(get_next_url(external=True), 'http://example.com')
            self.assertEqual(get_next_url(), '/')
            self.assertEqual(get_next_url(default=()), ())
        
        with self.app.test_request_context('/'):
            session['next'] = '/external'
            self.assertEqual(get_next_url(session=True), '/external')

    def test_jsonp(self):
        with self.app.test_request_context('/?callback=http://example.com'):
            r = jsonp(lang='en-us', query='python')
            self.assertEqual(r.headers['Content-Type'], 'application/json')

        with self.app.test_request_context('/?callback=callback'):
            r = jsonp(lang='en-us', query='python')
            self.assertEqual(r.headers['Content-Type'], 'application/javascript')

    def test_requestargs(self):
        with self.app.test_request_context('/?p3=1&p3=2&p2=3&p1=1'):
            print request.args, f()
            #self.assertEqual(f(p1='2', p2='2'), (1, 3))
            


if __name__ == '__main__':
    unittest.main()
