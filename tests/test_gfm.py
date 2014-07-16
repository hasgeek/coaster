import unittest
from coaster.gfm import gfm, markdown


class TestMarkdown(unittest.TestCase):
    def test_single_underscores(self):
        """Don't touch single underscores inside words."""
        self.assertEqual(
            gfm('foo_bar'),
            'foo_bar',
        )

    def test_underscores_code_blocks(self):
        """Don't touch underscores in code blocks."""
        self.assertEqual(
            gfm('    foo_bar_baz'),
            '    foo_bar_baz',
        )
        # Now with extra indentation
        self.assertEqual(
            gfm('        foo_bar_baz'),
            '        foo_bar_baz',
        )

    def test_underscores_inline_code_blocks(self):
        """Don't touch underscores in code blocks."""
        self.assertEqual(
            gfm('foo `foo_bar_baz`'),
            'foo `foo_bar_baz`',
        )

    def test_underscores_pre_blocks(self):
        """Don't touch underscores in pre blocks."""
        self.assertEqual(
            gfm('<pre>\nfoo_bar_baz\n</pre>'),
            '<pre>\nfoo_bar_baz\n</pre>',
        )

    def test_pre_block_pre_text(self):
        """Don't treat pre blocks with pre-text differently."""
        a = '\n\n<pre>\nthis is `a\\_test` and this\\_too\n</pre>'
        b = 'hmm<pre>\nthis is `a\\_test` and this\\_too\n</pre>'
        self.assertEqual(
            gfm(a)[2:],
            gfm(b)[3:],
        )

    def test_two_underscores(self):
        """Escape two or more underscores inside words."""
        self.assertEqual(
            gfm('foo_bar_baz'),
            'foo\\_bar\\_baz',
        )
        self.assertEqual(
            gfm('something else then foo_bar_baz'),
            'something else then foo\\_bar\\_baz',
        )

    def test_newlines_simple(self):
        """Turn newlines into br tags in simple cases."""
        self.assertEqual(
            gfm('foo\nbar'),
            'foo  \nbar',
        )

    def test_newlines_group(self):
        """Convert newlines in all groups."""
        self.assertEqual(
            gfm('apple\npear\norange\n\nruby\npython\nerlang'),
            'apple  \npear  \norange\n\nruby  \npython  \nerlang',
        )

    def test_newlines_long_group(self):
        """Convert newlines in even long groups."""
        self.assertEqual(
            gfm('apple\npear\norange\nbanana\n\nruby\npython\nerlang'),
            'apple  \npear  \norange  \nbanana\n\nruby  \npython  \nerlang',
        )

    def test_newlines_list(self):
        """Don't convert newlines in lists."""
        self.assertEqual(
            gfm('# foo\n# bar'),
            '# foo\n# bar',
        )
        self.assertEqual(
            gfm('* foo\n* bar'),
            '* foo\n* bar',
        )
        self.assertEqual(
            gfm('+ foo\n+ bar'),
            '+ foo\n+ bar',
        )
        self.assertEqual(
            gfm('- foo\n- bar'),
            '- foo\n- bar',
        )

    def test_underscores_urls(self):
        """Don't replace underscores in URLs"""
        self.assertEqual(
            gfm('[foo](http://example.com/a_b_c)'),
            '[foo](http://example.com/a_b_c)'
            )

    def test_underscores_in_html(self):
        """Don't replace underscores in HTML blocks"""
        self.assertEqual(
            gfm('<img src="http://example.com/a_b_c" />'),
            '<img src="http://example.com/a_b_c" />'
            )

    def test_linkify_naked_urls(self):
        """Wrap naked URLs in []() so they become clickable links."""
        self.assertEqual(
            gfm(" http://www.example.com:80/foo?bar=bar&biz=biz"),
            " [http://www.example.com:80/foo?bar=bar&biz=biz](http://www.example.com:80/foo?bar=bar&biz=biz)"
            )

    def test_gfm_code_blocks(self):
        """Turn ```code_blocks``` into 4-space indented code blocks."""
        # Without a syntax header
        self.assertEqual(
            gfm("```\nprint 'Hello'\n```"),
            "    print 'Hello'"
            )
        # With a syntax header
        self.assertEqual(
            gfm("```python\nprint 'Hello'\n```"),
            "    :::python\n    print 'Hello'"
            )
        # Embedded in some text
        self.assertEqual(gfm(
            "Some code:\n"
            "\n"
            "```python\n"
            "print 'Hello world'\n"
            "for x in range(10):\n"
            "    print x\n"
            "```\n"
            "\n"
            "Works?"),

            "Some code:\n"
            "\n"
            "    :::python\n"
            "    print 'Hello world'\n"
            "    for x in range(10):\n"
            "        print x\n"
            "\n"
            "Works?")

        # Embedded in some text, with \r\n line endings
        self.assertEqual(gfm(
            "Some code:\r\n"
            "\r\n"
            "```python\r\n"
            "print 'Hello world'\r\n"
            "for x in range(10):\r\n"
            "    print x\r\n"
            "```\r\n"
            "\r\n"
            "Works?"),

            "Some code:\r\n"
            "\r\n"
            "    :::python\r\n"
            "    print 'Hello world'\r\n"
            "    for x in range(10):\r\n"
            "        print x\r\n"
            "\r\n"
            "Works?")

    def test_markdown(self):
        """Markdown rendering"""
        self.assertEqual(markdown('hello'), '<p>hello</p>')

    def test_text_markdown(self):
        """Markdown rendering with HTML disabled (default)"""
        self.assertEqual(markdown('hello <del>there</del>'), '<p>hello &lt;del&gt;there&lt;/del&gt;</p>')

    def test_html_markdown(self):
        """Markdown rendering with HTML enabled"""
        self.assertEqual(markdown('hello <del>there</del>', html=True), '<p>hello <del>there</del></p>')

    def test_empty_markdown(self):
        """Don't choke on None"""
        self.assertEqual(markdown(None), None)
