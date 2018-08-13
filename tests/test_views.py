# -*- coding: utf-8 -*-

import unittest
from werkzeug.exceptions import BadRequest, Forbidden
from flask import Flask, session, json
from coaster.app import load_config_from_file
from coaster.auth import current_auth, add_auth_attribute
from coaster.views import (get_current_url, get_next_url, jsonp, requestargs, requestquery, requestform,
    requires_permission, endpoint_for)


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


@requires_permission('allow-this')
def permission1():
    return 'allowed1'


@requires_permission({'allow-this', 'allow-that'})
def permission2():
    return 'allowed2'


# --- Tests -------------------------------------------------------------------

class TestCoasterViews(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        load_config_from_file(self.app, 'settings.py')
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

    def test_requires_permission(self):
        with self.app.test_request_context():
            with self.assertRaises(Forbidden):
                permission1()
            with self.assertRaises(Forbidden):
                permission2()

            add_auth_attribute('permissions', set())

            with self.assertRaises(Forbidden):
                permission1()
            with self.assertRaises(Forbidden):
                permission2()

            current_auth.permissions.add('allow-that')  # FIXME! Shouldn't this be a frozenset?
            with self.assertRaises(Forbidden):
                permission1()
            assert permission2() == 'allowed2'

            current_auth.permissions.add('allow-this')
            assert permission1() == 'allowed1'
            assert permission2() == 'allowed2'


class TestCoasterViewsEndpointFor(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__, subdomain_matching=True)
        # Use `index` as the view function for all routes as it's not actually called
        self.app.add_url_rule('/', 'index', index)
        self.app.add_url_rule('/slashed/', 'slashed', index)
        self.app.add_url_rule('/sub', 'subdomained', index, subdomain='<subdomain>')

    def test_endpoint_for(self):
        with self.app.test_request_context():
            assert endpoint_for('http://localhost/') == 'index'
            assert endpoint_for('http://localhost/slashed/') == 'slashed'
            assert endpoint_for('http://localhost/slashed') == 'slashed'
            assert endpoint_for('http://localhost/slashed', follow_redirects=False) is None
            assert endpoint_for('http://localhost/sub') is None  # Requires SERVER_NAME

            assert endpoint_for('http://example.com/') is None
            assert endpoint_for('http://example.com/slashed/') is None
            assert endpoint_for('http://example.com/slashed') is None
            assert endpoint_for('http://example.com/slashed', follow_redirects=False) is None
            assert endpoint_for('http://example.com/sub') is None

            assert endpoint_for('http://sub.example.com/') is None
            assert endpoint_for('http://sub.example.com/slashed/') is None
            assert endpoint_for('http://sub.example.com/slashed') is None
            assert endpoint_for('http://sub.example.com/slashed', follow_redirects=False) is None
            assert endpoint_for('http://sub.example.com/sub') is None

        self.app.config['SERVER_NAME'] = 'example.com'

        with self.app.test_request_context():
            assert endpoint_for('http://localhost/') is None
            assert endpoint_for('http://localhost/slashed/') is None
            assert endpoint_for('http://localhost/slashed') is None
            assert endpoint_for('http://localhost/slashed', follow_redirects=False) is None
            assert endpoint_for('http://localhost/sub') is None

            assert endpoint_for('http://example.com/') == 'index'
            assert endpoint_for('http://example.com/slashed/') == 'slashed'
            assert endpoint_for('http://example.com/slashed') == 'slashed'
            assert endpoint_for('http://example.com/slashed', follow_redirects=False) is None
            assert endpoint_for('http://example.com/sub') == 'subdomained'

            assert endpoint_for('http://sub.example.com/') is None
            assert endpoint_for('http://sub.example.com/slashed/') is None
            assert endpoint_for('http://sub.example.com/slashed') is None
            assert endpoint_for('http://sub.example.com/slashed', follow_redirects=False) is None
            assert endpoint_for('http://sub.example.com/sub') is 'subdomained'
