# -*- coding: utf-8 -*-

import datetime
import unittest
from coaster import LabeledEnum, make_password, check_password, parse_isoformat, sanitize_html, sorted_timezones


class MY_ENUM(LabeledEnum):
    FIRST = (1, "First")
    SECOND = (2, "Second")
    THIRD = (3, "Third")


class TestCoasterUtils(unittest.TestCase):
    def test_labeled_enum(self):
        self.assertEqual(MY_ENUM.FIRST, 1)
        self.assertEqual(MY_ENUM.SECOND, 2)
        self.assertEqual(MY_ENUM.THIRD, 3)

        self.assertEqual(MY_ENUM[MY_ENUM.FIRST], "First")
        self.assertEqual(MY_ENUM[MY_ENUM.SECOND], "Second")
        self.assertEqual(MY_ENUM[MY_ENUM.THIRD], "Third")

        self.assertEqual(MY_ENUM.items(), [(1, "First"), (2, "Second"), (3, "Third")])

        # self.assertRaises doesn't work so workaround
        try:
            MY_ENUM[2] = "SECOND"
        except TypeError:
            pass

    def test_unlisted_make_password_encoding(self):
        """Test for unsupported password encryption schemes.
        """
        self.assertRaises(ValueError, make_password, password='password', encoding=u'DES')

    def test_check_password(self):
        self.assertFalse(check_password(u'{SSHA}ManThisIsPassword', u'ManThisIsPassword'))
        self.assertTrue(check_password(u'{PLAIN}ManThisIsPassword', u'ManThisIsPassword'))

    def test_parse_isoformat(self):
        self.assertEqual(parse_isoformat("1882-12-11T00:00:00.1234Z"), datetime.datetime(1882, 12, 11, 0, 0, 0, 123400))
        self.assertEqual(parse_isoformat("1882-12-11T00:00:00Z"), datetime.datetime(1882, 12, 11, 0, 0))

    def test_sanitize_html(self):
        html = """<html><head><title>Test sanitize_html</title><script src="jquery.js"></script></head><body><!-- Body Comment-->Body<script type="application/x-some-script">alert("foo");</script></body></html>"""
        self.assertEqual(sanitize_html(html), u'Test sanitize_htmlBodyalert("foo");')
        self.assertEqual(sanitize_html("<html><head><title>Test sanitize_html</title></head><p>P</p><body><!-- Body Comment-><p>Body</p></body></html>"), u'Test sanitize_html<p>P</p>')

    def test_sorted_timezones(self):
        self.assertTrue(isinstance(sorted_timezones(), list))


if __name__ == '__main__':
    unittest.main()
