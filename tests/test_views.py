# -*- coding: utf-8 -*-

import unittest
from flask import Flask, session, json
from coaster.app import load_config_from_file
from coaster.views import get_current_url, get_next_url, jsonp, requestargs, BadRequest


def index():
    return "index"


def external():
    return "external"


def somewhere():
    return "somewhere"


@requestargs('p1', ('p2', int), ('p3[]', int))
def f(p1, p2=None, p3=None):
    return p1, p2, p3


@requestargs('p1', ('p2', int), ('p3[]'))
def f1(p1, p2=None, p3=None):
    return p1, p2, p3


class TestCoasterViews(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        load_config_from_file(self.app, "settings.py")
        self.app.add_url_rule('/', 'index', index)
        self.app.add_url_rule('/', 'external', external)
        self.app.add_url_rule('/somewhere', 'somewhere', )

    def test_get_current_url(self):
        with self.app.test_request_context('/'):
            self.assertEqual(get_current_url(), '/')

        with self.app.test_request_context('/?q=hasgeek'):
            self.assertEqual(get_current_url(), '/?q=hasgeek')

        self.app.config['SERVER_NAME'] = 'example.com'

        with self.app.test_request_context('/somewhere', environ_overrides={'HTTP_HOST': 'example.com'}):
            self.assertEqual(get_current_url(), '/somewhere')

        with self.app.test_request_context('/somewhere', environ_overrides={'HTTP_HOST': 'sub.example.com'}):
            self.assertEqual(get_current_url(), 'http://sub.example.com/somewhere')

    def test_get_next_url(self):
        with self.app.test_request_context('/?next=http://example.com'):
            self.assertEqual(get_next_url(external=True), 'http://example.com')
            self.assertEqual(get_next_url(), '/')
            self.assertEqual(get_next_url(default=()), ())

        with self.app.test_request_context('/'):
            session['next'] = '/external'
            self.assertEqual(get_next_url(session=True), '/external')

    def test_jsonp(self):
        with self.app.test_request_context('/?callback=callback'):
            kwargs = {'lang': 'en-us', 'query': 'python'}
            r = jsonp(**kwargs)
            response = 'callback({\n  "%s": "%s",\n  "%s": "%s"\n});' % ('lang', kwargs['lang'], 'query', kwargs['query'])
            self.assertEqual(response, r.data)

        with self.app.test_request_context('/'):
            param1, param2 = 1, 2
            r = jsonp(param1=param1, param2=param2)
            resp = json.loads(r.response[0])
            self.assertEqual(resp['param1'], param1)
            self.assertEqual(resp['param2'], param2)
            r = jsonp({'param1': param1, 'param2': param2})
            resp = json.loads(r.response[0])
            self.assertEqual(resp['param1'], param1)
            self.assertEqual(resp['param2'], param2)
            r = jsonp([('param1', param1), ('param2', param2)])
            resp = json.loads(r.response[0])
            self.assertEqual(resp['param1'], param1)
            self.assertEqual(resp['param2'], param2)

    def test_requestargs(self):
        with self.app.test_request_context('/?p3=1&p3=2&p2=3&p1=1'):
            self.assertEqual(f(), (u'1', 3, [1, 2]))

        with self.app.test_request_context('/?p2=2'):
            self.assertEqual(f(p1='1'), (u'1', 2, None))

        with self.app.test_request_context('/?p3=1&p3=2&p2=3&p1=1'):
            self.assertEqual(f1(), (u'1', 3, [u'1', u'2']))

        with self.app.test_request_context('/?p2=2&p4=4'):
            self.assertRaises(TypeError, f, p4='4')
            self.assertRaises(BadRequest, f, p4='4')
