from typing import Optional
import unittest

from flask import Flask

from coaster.views import endpoint_for


def view():
    return "view"


class TestScaffolding(unittest.TestCase):
    server_name: Optional[str] = None

    def setUp(self):
        self.app = Flask(
            __name__, subdomain_matching=True if self.server_name else False
        )
        # Use `view` as the view function for all routes as it's not actually called
        self.app.add_url_rule('/', 'index', view)
        self.app.add_url_rule('/slashed/', 'slashed', view)
        self.app.add_url_rule('/sub', 'un_subdomained', view)
        self.app.add_url_rule('/sub', 'subdomained', view, subdomain='<subdomain>')
        if self.server_name:
            self.app.config['SERVER_NAME'] = self.server_name

        self.ctx = self.app.test_request_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()


class TestNoServerName(TestScaffolding):
    def test_localhost_index(self):
        assert endpoint_for('http://localhost/') == ('index', {})

    def test_localhost_slashed(self):
        assert endpoint_for('http://localhost/slashed/') == ('slashed', {})

    def test_localhost_unslashed(self):
        assert endpoint_for('http://localhost/slashed') == ('slashed', {})

    def test_localhost_unslashed_noredirect(self):
        assert endpoint_for('http://localhost/slashed', follow_redirects=False) == (
            None,
            {},
        )

    def test_localhost_sub(self):
        assert endpoint_for('http://localhost/sub') == ('un_subdomained', {})

    def test_example_index(self):
        assert endpoint_for('http://example.com/') == ('index', {})

    def test_example_slashed(self):
        assert endpoint_for('http://example.com/slashed/') == ('slashed', {})

    def test_example_unslashed(self):
        assert endpoint_for('http://example.com/slashed') == ('slashed', {})

    def test_example_unslashed_noredirect(self):
        assert endpoint_for('http://example.com/slashed', follow_redirects=False) == (
            None,
            {},
        )

    def test_example_sub(self):
        assert endpoint_for('http://example.com/sub') == ('un_subdomained', {})

    def test_subexample_index(self):
        assert endpoint_for('http://sub.example.com/') == ('index', {})

    def test_subexample_slashed(self):
        assert endpoint_for('http://sub.example.com/slashed/') == ('slashed', {})

    def test_subexample_unslashed(self):
        assert endpoint_for('http://sub.example.com/slashed') == ('slashed', {})

    def test_subexample_unslashed_noredirect(self):
        assert endpoint_for(
            'http://sub.example.com/slashed', follow_redirects=False
        ) == (None, {})

    def test_subexample_sub(self):
        assert endpoint_for('http://sub.example.com/sub') == ('un_subdomained', {})


class TestWithServerName(TestScaffolding):
    server_name = 'example.com'

    def test_localhost_index(self):
        assert endpoint_for('http://localhost/') == (None, {})

    def test_localhost_slashed(self):
        assert endpoint_for('http://localhost/slashed/') == (None, {})

    def test_localhost_unslashed(self):
        assert endpoint_for('http://localhost/slashed') == (None, {})

    def test_localhost_unslashed_noredirect(self):
        assert endpoint_for('http://localhost/slashed', follow_redirects=False) == (
            None,
            {},
        )

    def test_localhost_sub(self):
        assert endpoint_for('http://localhost/sub') == (None, {})

    def test_example_index(self):
        assert endpoint_for('http://example.com/') == ('index', {})

    def test_example_slashed(self):
        assert endpoint_for('http://example.com/slashed/') == ('slashed', {})

    def test_example_unslashed(self):
        assert endpoint_for('http://example.com/slashed') == ('slashed', {})

    def test_example_unslashed_noredirect(self):
        assert endpoint_for('http://example.com/slashed', follow_redirects=False) == (
            None,
            {},
        )

    def test_example_sub(self):
        assert endpoint_for('http://example.com/sub') == ('un_subdomained', {})

    def test_subexample_index(self):
        assert endpoint_for('http://sub.example.com/') == (None, {})

    def test_subexample_slashed(self):
        assert endpoint_for('http://sub.example.com/slashed/') == (None, {})

    def test_subexample_unslashed(self):
        assert endpoint_for('http://sub.example.com/slashed') == (None, {})

    def test_subexample_unslashed_noredirect(self):
        assert endpoint_for(
            'http://sub.example.com/slashed', follow_redirects=False
        ) == (None, {})

    def test_subexample_sub(self):
        assert endpoint_for('http://sub.example.com/sub') == (
            'subdomained',
            {'subdomain': 'sub'},
        )
