# -*- coding: utf-8 -*-

from six.moves.collections_abc import MutableSet
import six

import datetime
import unittest
import uuid

from pytz import UTC, common_timezones

from coaster.utils import (
    InspectableSet,
    LabeledEnum,
    ParseError,
    check_password,
    deobfuscate_email,
    isoweek_datetime,
    make_password,
    midnight_to_utc,
    namespace_from_url,
    nary_op,
    parse_isoformat,
    parse_duration,
    require_one_of,
    sanitize_html,
    sorted_timezones,
    suuid,
    suuid2uuid,
    ulstrip,
    urstrip,
    ustrip,
    utcnow,
    uuid2suuid,
)


class MY_ENUM(LabeledEnum):  # NOQA: N801
    FIRST = (1, "First")
    SECOND = (2, "Second")
    THIRD = (3, "Third")


class MY_ENUM_TWO(LabeledEnum):  # NOQA: N801
    FIRST = (1, 'first', "First")
    SECOND = (2, 'second', "Second")
    THIRD = (3, 'third', "Third")
    __order__ = (FIRST, SECOND, THIRD)


class TestCoasterUtils(unittest.TestCase):
    def test_labeled_enum(self):
        self.assertEqual(MY_ENUM.FIRST, 1)
        self.assertEqual(MY_ENUM.SECOND, 2)
        self.assertEqual(MY_ENUM.THIRD, 3)

        self.assertEqual(MY_ENUM[MY_ENUM.FIRST], "First")
        self.assertEqual(MY_ENUM[MY_ENUM.SECOND], "Second")
        self.assertEqual(MY_ENUM[MY_ENUM.THIRD], "Third")

        if six.PY2:
            self.assertEqual(
                sorted(MY_ENUM.items()), [(1, "First"), (2, "Second"), (3, "Third")]
            )
        else:
            self.assertEqual(
                MY_ENUM.items(), [(1, "First"), (2, "Second"), (3, "Third")]
            )

        self.assertEqual(
            MY_ENUM_TWO.nametitles(),
            [('first', "First"), ('second', "Second"), ('third', "Third")],
        )
        self.assertEqual(MY_ENUM_TWO.value_for('second'), 2)

        with self.assertRaises(TypeError):
            MY_ENUM[2] = "SECOND"

    def test_unlisted_make_password_encoding(self):
        """Test for unsupported password encryption schemes."""
        self.assertRaises(  # NOQA: S106
            ValueError, make_password, password='password', encoding=u'DES'
        )

    def test_check_password(self):
        self.assertFalse(
            check_password(u'{SSHA}ManThisIsPassword', u'ManThisIsPassword')
        )
        self.assertTrue(
            check_password(u'{PLAIN}ManThisIsPassword', u'ManThisIsPassword')
        )
        self.assertTrue(
            check_password(u'{SSHA}0MToxERtorjT+1Avyrrpgd3KuOtnuHt4qhgp', u'test')
        )
        self.assertTrue(
            check_password(
                u'{BCRYPT}$2a$12$8VF760ysexo5rozFSZhGbuvNVnbZnHeMHQwJ8fQWmUa8h2nd4exsi',
                u'test',
            )
        )

    def test_parse_isoformat(self):
        assert parse_isoformat('1882-12-11T00:00:00.1234Z') == datetime.datetime(
            1882, 12, 11, 0, 0, 0, 123400
        )
        assert parse_isoformat('1882-12-11T00:00:00Z'), datetime.datetime(
            1882, 12, 11, 0, 0
        )
        assert parse_isoformat(
            '1882-12-11T00:00:00.1234Z', naive=False
        ) == datetime.datetime(1882, 12, 11, 0, 0, 0, 123400, tzinfo=UTC)
        assert parse_isoformat(
            '1882-12-11T00:00:00Z', naive=False
        ) == datetime.datetime(1882, 12, 11, 0, 0, tzinfo=UTC)

        with self.assertRaises(ParseError):
            parse_isoformat('2019-05-03T05:02:26.340937Z\'')

        with self.assertRaises(ParseError):
            parse_isoformat('2019-05-03T05:02:26.340937Z\'', naive=False)

    def test_parse_duration(self):
        assert parse_duration('P1Y2M3DT4H54M6S') == datetime.timedelta(days=428, seconds=17646)
        assert parse_duration('PT10M1S') == datetime.timedelta(seconds=601)
        assert parse_duration('PT1H1S') == datetime.timedelta(seconds=3601)
        with self.assertRaises(ParseError):
            # no time separator
            assert parse_duration('P2M10M1S')

    def test_sanitize_html(self):
        html = """<html><head><title>Test sanitize_html</title><script src="jquery.js"></script></head><body><!-- Body Comment-->Body<script type="application/x-some-script">alert("foo");</script></body></html>"""
        self.assertEqual(sanitize_html(html), u'Test sanitize_htmlBodyalert("foo");')
        self.assertEqual(
            sanitize_html(
                "<html><head><title>Test sanitize_html</title></head><p>P</p><body><!-- Body Comment-><p>Body</p></body></html>"
            ),
            u'Test sanitize_html<p>P</p>',
        )

    def test_sorted_timezones(self):
        assert isinstance(sorted_timezones(), list)

    def test_namespace_from_url(self):
        self.assertEqual(
            namespace_from_url(u'https://github.com/hasgeek/coaster'), u'com.github'
        )
        self.assertEqual(
            namespace_from_url(
                u'https://funnel.hasgeek.com/metarefresh2014/938-making-design-decisions'
            ),
            u'com.hasgeek.funnel',
        )
        self.assertEqual(namespace_from_url(u'http://www.hasgeek.com'), u'com.hasgeek')
        assert namespace_from_url(u'www.hasgeek.com') is None
        assert namespace_from_url(u'This is an invalid url') is None
        # IP addresses are rejected
        assert namespace_from_url('127.0.0.1') is None
        # Return string type is the input type
        assert isinstance(
            namespace_from_url(u'https://github.com/hasgeek/coaster'), six.text_type
        )
        assert isinstance(namespace_from_url('https://github.com/hasgeek/coaster'), str)

    def test_deobfuscate_email(self):
        in_text = """
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
        out_text = """
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
        self.assertEqual(deobfuscate_email(in_text), out_text)

    def test_isoweek_datetime_all_timezones(self):
        """Test that isoweek_datetime works for all timezones"""
        for timezone in common_timezones:
            for week in range(53):
                isoweek_datetime(2017, week + 1, timezone)

    def test_midnight_to_utc_all_timezones(self):
        """Test that midnight_to_utc works for all timezones"""
        for timezone in common_timezones:
            for day in range(365):
                midnight_to_utc(
                    datetime.date(2017, 1, 1) + datetime.timedelta(days=day), timezone
                )

    def test_utcnow(self):
        """Test that Coaster's utcnow works correctly"""
        # Get date from function being tested
        now1 = utcnow()
        # Get date from Python stdlib
        now2 = datetime.datetime.utcnow()

        # 1. Our function returns a date that has a timezone
        assert now1.tzinfo is not None
        # 2. The timezone is UTC because its offset is zero
        assert now1.tzinfo.utcoffset(now1) == datetime.timedelta(0)
        # 3. And it's within a second of the comparison date (the runtime environment
        # cannot possibly have taken over a second between two consecutive statements)
        assert abs(now2 - now1.replace(tzinfo=None)) < datetime.timedelta(seconds=1)

    def test_suuid(self):
        """Test the ShortUUID functions"""
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
        self.assertEqual(require_one_of(True, first='a', second=None), ('first', 'a'))
        self.assertEqual(require_one_of(True, first=None, second='b'), ('second', 'b'))

    def test_inspectable_set(self):
        s1 = InspectableSet(['all', 'anon'])
        assert 'all' in s1
        assert 'auth' not in s1
        self.assertTrue(s1['all'])
        self.assertFalse(s1['auth'])
        self.assertTrue(s1.all)
        self.assertFalse(s1.auth)

        s2 = InspectableSet({'all', 'anon', 'other'})
        assert 'all' in s2
        assert 'auth' not in s2
        self.assertTrue(s2['all'])
        self.assertFalse(s2['auth'])
        self.assertTrue(s2.all)
        self.assertFalse(s2.auth)

        self.assertEqual(len(s1), 2)
        self.assertEqual(len(s2), 3)
        self.assertEqual(s1, {'all', 'anon'})
        self.assertEqual(s2, {'all', 'anon', 'other'})

        with self.assertRaises(AttributeError):
            s1.auth = True

    def test_ulstrip(self):
        assert ulstrip(u' Test this ') == u'Test this '
        assert ulstrip(u'\u200b Test this \u200b') == u'Test this \u200b'

    def test_urstrip(self):
        assert urstrip(u' Test this ') == u' Test this'
        assert urstrip(u'\u200b Test this \u200b') == u'\u200b Test this'

    def test_ustrip(self):
        assert ustrip(u' Test this ') == u'Test this'
        assert ustrip(u'\u200b Test this \u200b') == u'Test this'

    def test_nary_op(self):
        class DemoSet(MutableSet):
            def __init__(self, members):
                self.set = set(members)

            def __contains__(self, value):
                return value in self.set

            def __iter__(self):
                return iter(self.set)

            def __len__(self):
                return len(self.set)

            def add(self, value):
                return self.set.add(value)

            def discard(self, value):
                return self.set.discard(value)

            update = nary_op(MutableSet.__ior__, "Custom docstring")

        # Confirm docstrings are added
        assert DemoSet.update.__doc__ == "Custom docstring"

        d = DemoSet(set())
        assert d == set()
        # Confirm the wrapped operator works with a single parameter
        d.update(['a'])
        assert d == {'a'}
        # Confirm the wrapped operator works with multiple parameters
        d.update(['b', 'c'], ['d', 'e'])
        assert d == {'a', 'b', 'c', 'd', 'e'}
