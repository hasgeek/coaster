# -*- coding: utf-8 -*-
import unittest
import uuid
import datetime
import six
from pytz import common_timezones
from coaster.utils import (LabeledEnum, make_password, check_password, parse_isoformat, sanitize_html,
    sorted_timezones, namespace_from_url, deobfuscate_email, isoweek_datetime, midnight_to_utc,
    suuid, suuid2uuid, uuid2suuid, require_one_of)


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
        self.assertTrue(check_password(u'{SSHA}0MToxERtorjT+1Avyrrpgd3KuOtnuHt4qhgp', u'test'))
        self.assertTrue(check_password(u'{BCRYPT}$2a$12$8VF760ysexo5rozFSZhGbuvNVnbZnHeMHQwJ8fQWmUa8h2nd4exsi', u'test'))

    def test_parse_isoformat(self):
        self.assertEqual(parse_isoformat("1882-12-11T00:00:00.1234Z"), datetime.datetime(1882, 12, 11, 0, 0, 0, 123400))
        self.assertEqual(parse_isoformat("1882-12-11T00:00:00Z"), datetime.datetime(1882, 12, 11, 0, 0))

    def test_sanitize_html(self):
        html = """<html><head><title>Test sanitize_html</title><script src="jquery.js"></script></head><body><!-- Body Comment-->Body<script type="application/x-some-script">alert("foo");</script></body></html>"""
        self.assertEqual(sanitize_html(html), u'Test sanitize_htmlBodyalert("foo");')
        self.assertEqual(sanitize_html("<html><head><title>Test sanitize_html</title></head><p>P</p><body><!-- Body Comment-><p>Body</p></body></html>"), u'Test sanitize_html<p>P</p>')

    def test_sorted_timezones(self):
        self.assertTrue(isinstance(sorted_timezones(), list))

    def test_namespace_from_url(self):
        self.assertEqual(namespace_from_url(u'https://github.com/hasgeek/coaster'), u'com.github')
        self.assertEqual(namespace_from_url(u'https://funnel.hasgeek.com/metarefresh2014/938-making-design-decisions'),
            u'com.hasgeek.funnel')
        self.assertEqual(namespace_from_url(u'http://www.hasgeek.com'), u'com.hasgeek')
        self.assertEqual(namespace_from_url(u'www.hasgeek.com'), None)
        self.assertEqual(namespace_from_url(u'This is an invalid url'), None)
        # IP addresses are rejected
        self.assertEqual(namespace_from_url('127.0.0.1'), None)
        # Return string type is the input type
        self.assertTrue(isinstance(namespace_from_url(u'https://github.com/hasgeek/coaster'), six.text_type))
        self.assertTrue(isinstance(namespace_from_url('https://github.com/hasgeek/coaster'), str))

    def test_deobfuscate_email(self):
        input = """
            test at example dot com
            test@example dot com
            test at example.com
            test[at]example[dot]com
            test{at}example(dot)com
            For real, mail me at hahaha at example dot com.
            Laughing at polka-dot commercials
            Quick attack. Organize resistance.
            We are at lunch. Come over.
            <li>and at scale.</li>
            <a href="mailto:test@example.com">this</a>
            <test@example.com>
            """
        output = """
            test@example.com
            test@example.com
            test@example.com
            test@example.com
            test@example.com
            For real, mail me@hahaha@example.com.
            Laughing@polka.commercials
            Quick attack. Organize resistance.
            We are@lunch. Come over.
            <li>and@scale.</li>
            <a href="mailto:test@example.com">this</a>
            <test@example.com>
            """
        self.assertEqual(deobfuscate_email(input), output)

    def test_isoweek_datetime_all_timezones(self):
        """Test that isoweek_datetime works for all timezones"""
        for timezone in common_timezones:
            for week in range(53):
                isoweek_datetime(2017, week + 1, timezone)

    def test_midnight_to_utc_all_timezones(self):
        """Test that midnight_to_utc works for all timezones"""
        for timezone in common_timezones:
            for day in range(365):
                midnight_to_utc(datetime.date(2017, 1, 1) + datetime.timedelta(days=day), timezone)

    def test_suuid(self):
        """
        Test the ShortUUID functions
        """
        s1 = suuid()
        self.assertEqual(len(s1), 22)
        u1 = suuid2uuid(s1)
        self.assertIsInstance(u1, uuid.UUID)
        self.assertEqual(u1.version, 4)  # ShortUUID uses v4 UUIDs by default
        s2 = uuid2suuid(u1)
        self.assertEqual(s1, s2)

    def test_require_one_of(self):
        # Valid scenarios
        require_one_of(solo='solo')
        require_one_of(first='first', second=None)
        # Invalid scenarios
        with self.assertRaises(TypeError):
            require_one_of()
        with self.assertRaises(TypeError):
            require_one_of(solo=None)
        with self.assertRaises(TypeError):
            require_one_of(first=None, second=None)
        with self.assertRaises(TypeError):
            require_one_of(first='first', second='second')
        with self.assertRaises(TypeError):
            require_one_of(first='first', second='second', third=None)
        with self.assertRaises(TypeError):
            require_one_of(first='first', second='second', third='third')
        # Ask for which was passed in
        self.assertEqual(require_one_of(True, first='a', second=None), 'first')
        self.assertEqual(require_one_of(True, first=None, second='b'), 'second')
