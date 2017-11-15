# -*- coding: utf-8 -*-

import unittest
from flask import Flask, session, json
from coaster.app import load_config_from_file
from coaster.views import get_current_url, get_next_url, jsonp, requestargs, requestquery, requestform, BadRequest


def index():
    return "index"


def external():
    return "external"


def somewhere():
    return "somewhere"


@requestargs('p1', ('p2', int), ('p3[]', int))
def requestargs_test1(p1, p2=None, p3=None):
    return p1, p2, p3


@requestargs('p1', ('p2', int), ('p3[]'))
def requestargs_test2(p1, p2=None, p3=None):
    return p1, p2, p3


@requestquery('p1', ('p2', int), ('p3[]', int))
def requestquery_test(p1, p2=None, p3=None):
    return p1, p2, p3


@requestform('p1', ('p2', int), ('p3[]', int))
def requestform_test(p1, p2=None, p3=None):
    return p1, p2, p3


@requestquery('query1')
@requestform('form1')
def requestcombo_test(query1, form1):
    return query1, form1


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
            response = (
                u'callback({\n  "%s": "%s",\n  "%s": "%s"\n});' % (
                    'lang', kwargs['lang'], 'query', kwargs['query'])
                ).encode('utf-8')

            self.assertEqual(response, r.get_data())

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
            self.assertEqual(requestargs_test1(), (u'1', 3, [1, 2]))

        with self.app.test_request_context('/?p2=2'):
            self.assertEqual(requestargs_test1(p1='1'), (u'1', 2, None))

        with self.app.test_request_context('/?p2=2'):
            self.assertEqual(requestargs_test1(p1='1', p2=3), (u'1', 3, None))

        with self.app.test_request_context('/?p3=1&p3=2&p2=3&p1=1'):
            self.assertEqual(requestargs_test2(), (u'1', 3, [u'1', u'2']))

        with self.app.test_request_context('/?p2=2&p4=4'):
            with self.assertRaises(TypeError):
                requestargs_test1(p4='4')
            with self.assertRaises(BadRequest):
                requestargs_test1(p4='4')

        with self.app.test_request_context('/?p3=1&p3=2&p2=3&p1=1'):
            self.assertEqual(requestquery_test(), (u'1', 3, [1, 2]))

        with self.app.test_request_context('/', data={'p3': [1, 2], 'p2': 3, 'p1': 1}, method='POST'):
            self.assertEqual(requestform_test(), (u'1', 3, [1, 2]))

        with self.app.test_request_context('/', query_string='query1=foo', data={'form1': 'bar'}, method='POST'):
            self.assertEqual(requestcombo_test(), ('foo', 'bar'))

        # Calling without a request context works as well
        self.assertEqual(requestargs_test1(p1='1', p2=3, p3=[1, 2]), ('1', 3, [1, 2]))
