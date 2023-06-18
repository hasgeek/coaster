"""
Date, time and timezone utilities
---------------------------------
"""

from __future__ import annotations

import typing as t
from datetime import date, datetime, timedelta, tzinfo

import isoweek
import pytz
from aniso8601 import parse_datetime, parse_duration
from aniso8601.exceptions import ISOFormatError as ParseError
from pytz import BaseTzInfo, utc

__all__ = [
    'utcnow',
    'parse_isoformat',
    'parse_duration',
    'isoweek_datetime',
    'midnight_to_utc',
    'sorted_timezones',
    'ParseError',
]

# --- Thread safety fix ----------------------------------------------------------------

# Force import of strptime. This was previously used in :func:`parse_isoformat`,
# but we have left this in because it could break elsewhere.
# https://stackoverflow.com/q/16309650/78903
datetime.strptime('20160816', '%Y%m%d')


def utcnow() -> datetime:
    """Return the current time at UTC with `tzinfo` set."""
    return datetime.now(utc)


def parse_isoformat(text: str, naive: bool = True, delimiter: str = 'T') -> datetime:
    """
    Parse an ISO 8601 timestamp as generated by `datetime.isoformat()`.

    Timestamps without a timezone are assumed to be at UTC. Raises :exc:`ParseError` if
    the timestamp cannot be parsed.

    :param bool naive: If `True`, strips timezone and returns datetime at UTC.
    """
    try:
        dt = parse_datetime(text, delimiter)
    except NotImplementedError:
        # aniso8601 misinterprets junk data and returns NotImplementedError with
        # "ISO 8601 extended year representation not supported"
        raise ParseError(f"Unparseable datetime {text}") from None
    if dt.tzinfo is not None and naive:
        dt = dt.astimezone(utc).replace(tzinfo=None)
    return dt


def isoweek_datetime(
    year: int,
    week: int,
    timezone: t.Union[tzinfo, BaseTzInfo, str] = 'UTC',
    naive: bool = False,
) -> datetime:
    """
    Return a datetime matching the starting point of a specified ISO week.

    The return value is in the specified timezone, or in the specified timezone (default
    `UTC`). Returns a naive datetime in UTC if requested (default `False`).

    >>> isoweek_datetime(2017, 1)
    datetime.datetime(2017, 1, 2, 0, 0, tzinfo=<UTC>)
    >>> isoweek_datetime(2017, 1, 'Asia/Kolkata')
    datetime.datetime(2017, 1, 1, 18, 30, tzinfo=<UTC>)
    >>> isoweek_datetime(2017, 1, 'Asia/Kolkata', naive=True)
    datetime.datetime(2017, 1, 1, 18, 30)
    >>> isoweek_datetime(2008, 1, 'Asia/Kolkata')
    datetime.datetime(2007, 12, 30, 18, 30, tzinfo=<UTC>)
    """
    naivedt = datetime.combine(isoweek.Week(year, week).day(0), datetime.min.time())
    if isinstance(timezone, str):
        tz: tzinfo = pytz.timezone(timezone)
    else:
        tz = timezone
    if isinstance(tz, BaseTzInfo):
        dt = tz.localize(naivedt).astimezone(utc)
    else:
        dt = naivedt.replace(tzinfo=tz).astimezone(utc)
    if naive:
        return dt.replace(tzinfo=None)
    return dt


def midnight_to_utc(
    dt: t.Union[date, datetime],
    timezone: t.Optional[t.Union[tzinfo, BaseTzInfo, str]] = None,
    naive: bool = False,
) -> datetime:
    """
    Return a UTC datetime matching the midnight for the given date or datetime.

    >>> from datetime import date
    >>> midnight_to_utc(datetime(2017, 1, 1))
    datetime.datetime(2017, 1, 1, 0, 0, tzinfo=<UTC>)
    >>> midnight_to_utc(pytz.timezone('Asia/Kolkata').localize(datetime(2017, 1, 1)))
    datetime.datetime(2016, 12, 31, 18, 30, tzinfo=<UTC>)
    >>> midnight_to_utc(datetime(2017, 1, 1), naive=True)
    datetime.datetime(2017, 1, 1, 0, 0)
    >>> midnight_to_utc(pytz.timezone('Asia/Kolkata').localize(datetime(2017, 1, 1)),
    ...   naive=True)
    datetime.datetime(2016, 12, 31, 18, 30)
    >>> midnight_to_utc(date(2017, 1, 1))
    datetime.datetime(2017, 1, 1, 0, 0, tzinfo=<UTC>)
    >>> midnight_to_utc(date(2017, 1, 1), naive=True)
    datetime.datetime(2017, 1, 1, 0, 0)
    >>> midnight_to_utc(date(2017, 1, 1), timezone='Asia/Kolkata')
    datetime.datetime(2016, 12, 31, 18, 30, tzinfo=<UTC>)
    >>> midnight_to_utc(datetime(2017, 1, 1), timezone='Asia/Kolkata')
    datetime.datetime(2016, 12, 31, 18, 30, tzinfo=<UTC>)
    >>> midnight_to_utc(pytz.timezone('Asia/Kolkata').localize(datetime(2017, 1, 1)),
    ...   timezone='UTC')
    datetime.datetime(2017, 1, 1, 0, 0, tzinfo=<UTC>)
    """
    tz: t.Union[tzinfo, BaseTzInfo]
    if timezone:
        if isinstance(timezone, str):
            tz = pytz.timezone(timezone)
        else:
            tz = timezone
    elif isinstance(dt, datetime) and dt.tzinfo:
        tz = dt.tzinfo
    else:
        tz = utc

    if isinstance(tz, BaseTzInfo):
        utc_dt = tz.localize(datetime.combine(dt, datetime.min.time())).astimezone(utc)
    else:
        utc_dt = datetime.combine(dt, datetime.min.time()).astimezone(utc)
    if naive:
        return utc_dt.replace(tzinfo=None)
    return utc_dt


def sorted_timezones() -> t.List[t.Tuple[str, str]]:
    """Return a list of timezones sorted by offset from UTC."""

    def hourmin(delta: timedelta) -> t.Tuple[int, int]:
        if delta.days < 0:
            hours, remaining = divmod(86400 - delta.seconds, 3600)
        else:
            hours, remaining = divmod(delta.seconds, 3600)
        minutes, remaining = divmod(remaining, 60)
        return hours, minutes

    now = datetime.utcnow()
    # Make a list of country code mappings
    timezone_country = {}
    for countrycode in pytz.country_timezones:
        for timezone in pytz.country_timezones[countrycode]:
            timezone_country[timezone] = countrycode

    # Make a list of timezones, discarding the US/* and Canada/* zones since they aren't
    # reliable for DST, and discarding UTC and GMT since timezones in that zone have
    # their own names
    timezones = [
        (
            pytz.timezone(tzname).utcoffset(  # type: ignore[call-arg]
                now, is_dst=False
            ),
            tzname,
        )
        for tzname in pytz.common_timezones
        if not tzname.startswith(('US/', 'Canada/')) and tzname not in ('GMT', 'UTC')
    ]
    # Sort timezones by offset from UTC and their human-readable name
    presorted = [
        (
            delta,
            # pylint: disable=consider-using-f-string
            '{sign}{offset} – {country}{zone} ({tzname})'.format(
                sign=(
                    (delta.days < 0 and '-')
                    or (delta.days == 0 and delta.seconds == 0 and ' ')
                    or '+'
                ),
                offset='{:02d}:{:02d}'.format(*hourmin(delta)),
                country=(
                    (f'{pytz.country_names[timezone_country[name]]}: ')
                    if name in timezone_country
                    else ''
                ),
                zone=name.replace('_', ' '),
                tzname=pytz.timezone(name).tzname(  # type: ignore[call-arg]
                    now, is_dst=False
                ),
            ),
            name,
        )
        for delta, name in timezones
    ]
    presorted.sort()
    # Return a list of (timezone, label) with the timezone offset included in the label.
    return [(name, label) for (delta, label, name) in presorted]
