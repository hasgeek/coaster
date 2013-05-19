import unittest
from coaster.gfm import gfm, markdown

# Test suite.
try:
    from nose.tools import assert_equal
except ImportError:
    def assert_equal(a, b):
        assert a == b, '%r != %r' % (a, b)


class TestLoadModels(unittest.TestCase):
    def test_single_underscores(self):
        """Don't touch single underscores inside words."""
        assert_equal(
            gfm('foo_bar'),
            'foo_bar',
        )

    def test_underscores_code_blocks(self):
        """Don't touch underscores in code blocks."""
        assert_equal(
            gfm('    foo_bar_baz'),
            '    foo_bar_baz',
        )

    def test_underscores_inline_code_blocks(self):
        """Don't touch underscores in code blocks."""
        assert_equal(
            gfm('foo `foo_bar_baz`'),
            'foo `foo_bar_baz`',
        )

    def test_underscores_pre_blocks(self):
        """Don't touch underscores in pre blocks."""
        assert_equal(
            gfm('<pre>\nfoo_bar_baz\n</pre>'),
            '<pre>\nfoo_bar_baz\n</pre>',
        )

    def test_pre_block_pre_text(self):
        """Don't treat pre blocks with pre-text differently."""
        a = '\n\n<pre>\nthis is `a\\_test` and this\\_too\n</pre>'
        b = 'hmm<pre>\nthis is `a\\_test` and this\\_too\n</pre>'
        assert_equal(
            gfm(a)[2:],
            gfm(b)[3:],
        )

    def test_two_underscores(self):
        """Escape two or more underscores inside words."""
        assert_equal(
            gfm('foo_bar_baz'),
            'foo\\_bar\\_baz',
        )
        assert_equal(
            gfm('something else then foo_bar_baz'),
            'something else then foo\\_bar\\_baz',
        )

    def test_newlines_simple(self):
        """Turn newlines into br tags in simple cases."""
        assert_equal(
            gfm('foo\nbar'),
            'foo  \nbar',
        )

    def test_newlines_group(self):
        """Convert newlines in all groups."""
        assert_equal(
            gfm('apple\npear\norange\n\nruby\npython\nerlang'),
            'apple  \npear  \norange\n\nruby  \npython  \nerlang',
        )

    def test_newlines_long_group(self):
        """Convert newlines in even long groups."""
        assert_equal(
            gfm('apple\npear\norange\nbanana\n\nruby\npython\nerlang'),
            'apple  \npear  \norange  \nbanana\n\nruby  \npython  \nerlang',
        )

    def test_newlines_list(self):
        """Don't convert newlines in lists."""
        assert_equal(
            gfm('# foo\n# bar'),
            '# foo\n# bar',
        )
        assert_equal(
            gfm('* foo\n* bar'),
            '* foo\n* bar',
        )

    def test_underscores_urls(self):
        """Don't replace underscores in URLs"""
        assert_equal(
            gfm('[foo](http://example.com/a_b_c)'),
            '[foo](http://example.com/a_b_c)'
            )

    def test_underscores_in_html(self):
        """Don't replace underscores in HTML blocks"""
        assert_equal(
            gfm('<img src="http://example.com/a_b_c" />'),
            '<img src="http://example.com/a_b_c" />'
            )

    def test_linkify_naked_urls(self):
        """Wrap naked URLs in []() so they become clickable links."""
        assert_equal(
            gfm(" http://www.example.com:80/foo?bar=bar&biz=biz"),
            " [http://www.example.com:80/foo?bar=bar&biz=biz](http://www.example.com:80/foo?bar=bar&biz=biz)"
            )

    def test_markdown(self):
        """Markdown rendering"""
        assert_equal(markdown('hello'), '<p>hello</p>')
