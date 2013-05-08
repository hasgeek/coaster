# -*- coding: utf-8 -*-

import unittest
from flask import Flask
from coaster.app import load_config_from_file
from coaster.views import get_current_url, get_next_url, jsonp


def index():
    return "index"


class TestCoasterViews(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        load_config_from_file(self.app, "settings.py")
        self.app.add_url_rule('/', 'index', index)

    def test_get_current_url(self):
        with self.app.test_request_context('/'):
            self.assertEqual(get_current_url(), '/')

        with self.app.test_request_context('/?q=hasgeek'):
            self.assertEqual(get_current_url(), '/?q=hasgeek')

    def test_get_next_url(self):
        with self.app.test_request_context('/?next=http://example.com'):
            print get_next_url(session=False)

    def test_jsonp(self):
        with self.app.test_request_context('/?callback=http://example.com'):
            r = jsonp(lang='en-us', query='python')
            self.assertEqual(r.headers['Content-Type'], 'application/json')

        with self.app.test_request_context('/?callback=callback'):
            r = jsonp(lang='en-us', query='python')
            self.assertEqual(r.headers['Content-Type'], 'application/javascript')


if __name__ == '__main__':
    unittest.main()
