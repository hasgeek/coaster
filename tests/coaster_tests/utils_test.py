"""Test utility functions."""

import datetime
import unittest
from collections.abc import Iterator, MutableSet
from typing import Any, Callable, ClassVar
from typing_extensions import Self

import pytest
from pytz import UTC, common_timezones

from coaster.utils import (
    InspectableSet,
    LabeledEnum,
    ParseError,
    compress_whitespace,
    deobfuscate_email,
    isoweek_datetime,
    midnight_to_utc,
    namespace_from_url,
    nary_op,
    parse_duration,
    parse_isoformat,
    require_one_of,
    sanitize_html,
    sorted_timezones,
    ulstrip,
    urstrip,
    ustrip,
    utcnow,
)


class MY_ENUM(LabeledEnum):  # noqa: N801
    FIRST = (1, "First")
    SECOND = (2, "Second")
    THIRD = (3, "Third")


class MY_ENUM_TWO(LabeledEnum):  # noqa: N801
    FIRST = (1, 'first', "First")
    SECOND = (2, 'second', "Second")
    THIRD = (3, 'third', "Third")


class TestCoasterUtils(unittest.TestCase):
    def test_labeled_enum(self) -> None:
        assert MY_ENUM.FIRST == 1
        assert MY_ENUM.SECOND == 2
        assert MY_ENUM.THIRD == 3

        assert MY_ENUM[MY_ENUM.FIRST] == "First"
        assert MY_ENUM[MY_ENUM.SECOND] == "Second"
        assert MY_ENUM[MY_ENUM.THIRD] == "Third"

        assert MY_ENUM.items() == [(1, "First"), (2, "Second"), (3, "Third")]

        assert MY_ENUM_TWO.nametitles() == [
            ('first', "First"),
            ('second', "Second"),
            ('third', "Third"),
        ]
        assert MY_ENUM_TWO.value_for('second') == 2

        with pytest.raises(TypeError):
            # pylint: disable=unsupported-assignment-operation
            MY_ENUM[2] = "SECOND"  # type: ignore[index]

    def test_parse_isoformat(self) -> None:
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

        tz639 = datetime.timezone(datetime.timedelta(hours=-6, minutes=-39))
        assert parse_isoformat(
            '1882-12-11T00:00:00-06:39', naive=False
        ) == datetime.datetime(1882, 12, 11, 0, 0, 0, tzinfo=tz639)

        assert parse_isoformat(
            '1882-12-11T00:00:00-06:39', naive=True
        ) == datetime.datetime(1882, 12, 11, 6, 39, 0)

        assert parse_isoformat('1882-12-11T00:00:00', naive=True) == datetime.datetime(
            1882, 12, 11, 0, 0, 0
        )

        with pytest.raises(
            ValueError, match='Delimiter "T" is not in combined date time string'
        ):
            # lacking the T delimiter
            assert parse_isoformat('1882-12-11 00:00:00.1234Z') == datetime.datetime(
                1882, 12, 11, 0, 0, 0, 123400
            )

        # will pass with delimiter
        assert parse_isoformat(
            '1882-12-11 00:00:00.1234Z', delimiter=' '
        ) == datetime.datetime(1882, 12, 11, 0, 0, 0, 123400)

        assert parse_isoformat(
            "2012-05-21 23:06:08", naive=False, delimiter=' '
        ) == datetime.datetime(2012, 5, 21, 23, 6, 8)

        with pytest.raises(ParseError):
            parse_isoformat('2019-05-03T05:02:26.340937Z\'')

        with pytest.raises(ParseError):
            parse_isoformat('2019-05-03T05:02:26.340937Z\'', naive=False)

        # These are from logged attempts at SQL injections

        with pytest.raises(ParseError):
            parse_isoformat('-7199 UNION ALL SELECT 31,31,31,31,31,31,31,31,31,31#')

        with pytest.raises(ParseError):
            parse_isoformat(
                '((CHR(113)||CHR(107)||CHR(113)||CHR(113)||CHR(113))||(SELECT'
                ' (CASE WHEN (1020=1020) THEN 1 ELSE 0 END))::TEXT||(CHR(113)||CHR(98)'
                '||CHR(107)||CHR(107)||CHR(113)) AS NUMERIC) AND (2521=2521'
            )

    def test_parse_duration(self) -> None:
        assert parse_duration('P1Y2M3DT4H54M6S') == datetime.timedelta(
            days=428, seconds=17646
        )
        assert parse_duration('PT10M1S') == datetime.timedelta(seconds=601)
        assert parse_duration('PT1H1S') == datetime.timedelta(seconds=3601)
        with pytest.raises(ParseError):
            # no time separator
            assert parse_duration('P2M10M1S')

    def test_sanitize_html(self) -> None:
        html = """<html><head><title>Test sanitize_html</title><script src="jquery.js"></script></head><body><!-- Body Comment-->Body<script type="application/x-some-script">alert("foo");</script></body></html>"""
        assert sanitize_html(html) == 'Test sanitize_htmlBodyalert("foo");'
        assert (
            sanitize_html(
                "<html><head><title>Test sanitize_html</title></head><p>P</p><body><!-- Body Comment-><p>Body</p></body></html>"
            )
            == 'Test sanitize_html<p>P</p>'
        )

    def test_sorted_timezones(self) -> None:
        assert isinstance(sorted_timezones(), list)

    def test_namespace_from_url(self) -> None:
        assert namespace_from_url('https://github.com/hasgeek/coaster') == 'com.github'
        assert (
            namespace_from_url(
                'https://funnel.hasgeek.com/metarefresh2014/938-making-design-decisions'
            )
            == 'com.hasgeek.funnel'
        )
        assert namespace_from_url('http://www.hasgeek.com') == 'com.hasgeek'
        assert namespace_from_url('www.hasgeek.com') is None
        assert namespace_from_url('This is an invalid url') is None
        # IP addresses are rejected
        assert namespace_from_url('127.0.0.1') is None
        # Return string type is the input type
        assert isinstance(namespace_from_url('https://github.com/hasgeek/coaster'), str)
        assert isinstance(namespace_from_url('https://github.com/hasgeek/coaster'), str)

    def test_deobfuscate_email(self) -> None:
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
        assert deobfuscate_email(in_text) == out_text

    def test_isoweek_datetime_all_timezones(self) -> None:
        """Test that isoweek_datetime works for all timezones."""
        for timezone in common_timezones:
            for week in range(53):
                isoweek_datetime(2017, week + 1, timezone)

    def test_midnight_to_utc_all_timezones(self) -> None:
        """Test that midnight_to_utc works for all timezones."""
        for timezone in common_timezones:
            for day in range(365):
                midnight_to_utc(
                    datetime.date(2017, 1, 1) + datetime.timedelta(days=day), timezone
                )

    def test_utcnow(self) -> None:
        """Test that Coaster's utcnow works correctly."""
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

    def test_require_one_of(self) -> None:
        # Valid scenarios
        require_one_of(solo='solo')
        require_one_of(first='first', second=None)
        # Invalid scenarios
        with pytest.raises(TypeError):
            require_one_of()
        with pytest.raises(TypeError):
            require_one_of(solo=None)
        with pytest.raises(TypeError):
            require_one_of(first=None, second=None)
        with pytest.raises(TypeError):
            require_one_of(first='first', second='second')
        with pytest.raises(TypeError):
            require_one_of(first='first', second='second', third=None)
        with pytest.raises(TypeError):
            require_one_of(first='first', second='second', third='third')
        # Ask for which was passed in
        assert require_one_of(True, first='a', second=None) == ('first', 'a')
        assert require_one_of(True, first=None, second='b') == ('second', 'b')

    def test_inspectable_set(self) -> None:
        s0: InspectableSet[set] = InspectableSet()
        assert not s0

        s1 = InspectableSet(['all', 'anon'])
        assert s1
        assert 'all' in s1
        assert 'auth' not in s1
        assert s1['all']
        assert not s1['auth']
        assert s1.all
        assert not s1.auth

        s2 = InspectableSet({'all', 'anon', 'other'})
        assert s2
        assert 'all' in s2
        assert 'auth' not in s2
        assert s2['all']
        assert not s2['auth']
        assert s2.all
        assert not s2.auth

        assert len(s0) == 0
        assert len(s1) == 2
        assert len(s2) == 3
        assert s1 != {'all', 'anon'}  # s1 will behave like a list
        assert s1 == ['all', 'anon']
        assert s2 == {'all', 'anon', 'other'}

        with pytest.raises(AttributeError):
            s1.auth = True

    def test_ulstrip(self) -> None:
        assert ulstrip(' Test this ') == 'Test this '
        assert ulstrip('\u200b Test this \u200b') == 'Test this \u200b'

    def test_urstrip(self) -> None:
        assert urstrip(' Test this ') == ' Test this'
        assert urstrip('\u200b Test this \u200b') == '\u200b Test this'

    def test_ustrip(self) -> None:
        assert ustrip(' Test this ') == 'Test this'
        assert ustrip('\u200b Test this \u200b') == 'Test this'

    def test_compress_whitespace(self) -> None:
        assert compress_whitespace("This is normal text") == "This is normal text"
        assert compress_whitespace("This\tis\ttabbed\ttext") == "This is tabbed text"
        assert compress_whitespace("This  is  spaced  out") == "This is spaced out"
        assert compress_whitespace("  Leading whitespace") == "Leading whitespace"
        assert compress_whitespace("Trailing whitespace  ") == "Trailing whitespace"
        assert (
            compress_whitespace(
                """
            This is a multiline
            piece of text.
            """
            )
            == "This is a multiline piece of text."
        )
        assert (
            compress_whitespace("Unicode\u2002whitespace\u2003here")
            == "Unicode whitespace here"
        )

    def test_nary_op(self) -> None:
        class DemoSet(MutableSet):
            def __init__(self, members: Any) -> None:
                self.set = set(members)

            def __contains__(self, value: Any) -> bool:
                return value in self.set

            def __iter__(self) -> Iterator:
                return iter(self.set)

            def __len__(self) -> int:
                return len(self.set)

            def add(self, value: Any) -> None:
                return self.set.add(value)

            def discard(self, value: Any) -> None:
                return self.set.discard(value)

            update: ClassVar[Callable[..., Self]] = nary_op(
                MutableSet.__ior__, "Custom docstring"
            )

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
