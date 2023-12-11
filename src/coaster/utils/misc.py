"""
Miscellaneous utilities
-----------------------
"""

from __future__ import annotations

import email.utils
import hashlib
import re
import time
import typing as t
import typing_extensions as te
import uuid
from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections import abc
from datetime import datetime
from functools import wraps
from random import SystemRandom
from secrets import token_bytes
from typing import overload
from urllib.parse import urlparse

import base58
import tldextract
from unidecode import unidecode

__all__ = [
    'base_domain_matches',
    'buid',
    'buid2uuid',
    'domain_namespace_match',
    'format_currency',
    'get_email_domain',
    'getbool',
    'is_collection',
    'make_name',
    'md5sum',
    'namespace_from_url',
    'nary_op',
    'newpin',
    'newsecret',
    'nullint',
    'nullstr',
    'require_one_of',
    'uuid1mc',
    'uuid1mc_from_datetime',
    'uuid2buid',
    'uuid_b58',
    'uuid_b64',
    'uuid_from_base58',
    'uuid_from_base64',
    'uuid_to_base58',
    'uuid_to_base64',
]

# --- Common delimiters and punctuation ------------------------------------------------

_strip_re = re.compile('[\'"`‘’“”′″‴]+')
_punctuation_re = re.compile(
    '[\x00-\x1f +!#$%&()*\\-/<=>?@\\[\\\\\\]^_{|}:;,.…‒–—―«»]+'
)
_ipv4_re = re.compile(
    r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}'
    r'(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
)


# --- Utilities ------------------------------------------------------------------------


def is_collection(item: t.Any) -> bool:
    """
    Return True if the item is a collection class but not a string or dict.

    List, tuple, set, frozenset or any other class that resembles one of these (using
    abstract base classes). Using ``collections.abc.Collection`` directly is not
    suitable as it also matches strings and dicts.

    >>> is_collection(0)
    False
    >>> is_collection(0.1)
    False
    >>> is_collection('')
    False
    >>> is_collection(b'')
    False
    >>> is_collection({})
    False
    >>> is_collection({}.keys())
    True
    >>> is_collection([])
    True
    >>> is_collection(())
    True
    >>> is_collection(set())
    True
    >>> is_collection(frozenset())
    True
    >>> from coaster.utils import InspectableSet
    >>> is_collection(InspectableSet({1, 2}))
    True
    """
    return not isinstance(item, (str, bytes, dict)) and isinstance(item, abc.Collection)


def uuid_b64() -> str:
    """
    Return a UUID4 encoded in URL-safe Base64, for use as a random identifier.

    >>> len(buid())
    22
    >>> buid() == buid()
    False
    >>> isinstance(buid(), str)
    True
    """
    return urlsafe_b64encode(uuid.uuid4().bytes).decode().rstrip('=')


#: Legacy name
buid = uuid_b64


def uuid_b58() -> str:
    """
    Return a UUID4 encoded in Base58 using the Bitcoin alphabet.

    >>> len(uuid_b58()) in (21, 22)
    True
    >>> uuid_b58() == uuid_b58()
    False
    >>> isinstance(uuid_b58(), str)
    True
    """
    return base58.b58encode(uuid.uuid4().bytes).decode()


def uuid1mc() -> uuid.UUID:
    """
    Return a UUID1 with a random multicast MAC id.

    >>> isinstance(uuid1mc(), uuid.UUID)
    True
    """
    # pylint: disable=protected-access
    return uuid.uuid1(node=uuid._random_getnode())  # type: ignore[attr-defined]


def uuid1mc_from_datetime(dt: t.Union[datetime, float]) -> uuid.UUID:
    """
    Return a UUID1 with a specific timestamp and a random multicast MAC id.

    .. warning::
        This function does not consider the timezone, and is not guaranteed to
        return a unique UUID. Use under controlled conditions only.

    >>> dt = datetime.now()
    >>> u1 = uuid1mc()
    >>> u2 = uuid1mc_from_datetime(dt)
    >>> # Both timestamps should be very close to each other but not an exact match
    >>> u1.time > u2.time
    True
    >>> u1.time - u2.time < 5000
    True
    >>> d2 = datetime.fromtimestamp((u2.time - 0x01b21dd213814000) * 100 / 1e9)
    >>> d2 == dt
    True
    """
    fields = list(uuid1mc().fields)
    if isinstance(dt, datetime):
        timeval = time.mktime(dt.timetuple()) + dt.microsecond / 1e6
    else:
        # Assume we got an actual timestamp
        timeval = dt

    # The following code is borrowed from the UUID module source:
    nanoseconds = int(timeval * 1e9)
    # 0x01b21dd213814000 is the number of 100-ns intervals between the
    # UUID epoch 1582-10-15 00:00:00 and the Unix epoch 1970-01-01 00:00:00.
    timestamp = int(nanoseconds // 100) + 0x01B21DD213814000
    time_low = timestamp & 0xFFFFFFFF
    time_mid = (timestamp >> 32) & 0xFFFF
    time_hi_version = (timestamp >> 48) & 0x0FFF

    fields[0] = time_low
    fields[1] = time_mid
    fields[2] = time_hi_version

    return uuid.UUID(fields=tuple(fields))  # type: ignore[arg-type]


def uuid_to_base64(value: uuid.UUID) -> str:
    """
    Encode a UUID as a 22-char URL-safe Base64 string.

    >>> uuid_to_base64(uuid.UUID('33203dd2-f2ef-422f-aeb0-058d6f5f7089'))
    'MyA90vLvQi-usAWNb19wiQ'
    """
    return urlsafe_b64encode(value.bytes).decode().rstrip('=')


#: Legacy name
uuid2buid = uuid_to_base64


def uuid_from_base64(value: str) -> uuid.UUID:
    """
    Decode a UUID from a URL-safe Base64 string.

    >>> uuid_from_base64('MyA90vLvQi-usAWNb19wiQ')
    UUID('33203dd2-f2ef-422f-aeb0-058d6f5f7089')
    """
    return uuid.UUID(bytes=urlsafe_b64decode(str(value) + '=='))


#: Legacy name
buid2uuid = uuid_from_base64


def uuid_to_base58(value: uuid.UUID) -> str:
    """
    Encode a UUID as a Base58 string using the Bitcoin alphabet.

    >>> uuid_to_base58(uuid.UUID('33203dd2-f2ef-422f-aeb0-058d6f5f7089'))
    '7KAmj837MyuJWUYPwtqAfz'
    >>> # The following UUID to Base58 encoding is from NPM uuid-base58, for comparison
    >>> uuid_to_base58(uuid.UUID('d7ce8475-e77c-43b0-9dde-56b428981999'))
    'TedLUruK7MosG1Z88urTkk'
    """
    return base58.b58encode(value.bytes).decode()


def uuid_from_base58(value: str) -> uuid.UUID:
    """
    Decode a UUID from Base58 using the Bitcoin alphabet.

    >>> uuid_from_base58('7KAmj837MyuJWUYPwtqAfz')
    UUID('33203dd2-f2ef-422f-aeb0-058d6f5f7089')
    >>> # The following UUID to Base58 encoding is from NPM uuid-base58, for comparison
    >>> uuid_from_base58('TedLUruK7MosG1Z88urTkk')
    UUID('d7ce8475-e77c-43b0-9dde-56b428981999')
    """
    return uuid.UUID(bytes=base58.b58decode(str(value)))


def newsecret() -> str:
    """
    Make a secret key.

    Uses :func:`secrets.token_bytes` with 32 characters and renders into Base58 for a
    URL-friendly token, with a resulting length between 42 and 44 characters long.

    >>> len(newsecret()) in (42, 43, 44)
    True
    >>> isinstance(newsecret(), str)
    True
    >>> newsecret() == newsecret()
    False
    """
    return base58.b58encode(token_bytes(32)).decode()


def newpin(digits: int = 4) -> str:
    """
    Return a random numeric string with the specified number of digits, default 4.

    >>> len(newpin())
    4
    >>> len(newpin(5))
    5
    >>> newpin().isdigit()
    True
    >>> newpin() != newpin()
    True
    >>> newpin(6) != newpin(6)
    True
    """
    random = SystemRandom()
    pin = '00' * digits
    while len(pin) > digits:
        randnum = random.randint(0, 10**digits)  # nosec
        pin = str(randnum).zfill(digits)
    return pin


def make_name(
    text: str,
    delim: str = '-',
    maxlength: int = 50,
    checkused: t.Optional[t.Callable[[str], bool]] = None,
    counter: int = 2,
) -> str:
    r"""
    Generate an ASCII name slug.

    If a checkused filter is provided, it will be called with the candidate. If it
    returns True, make_name will add counter numbers starting from 2 until a suitable
    candidate is found.

    :param string delim: Delimiter between words, default '-'
    :param int maxlength: Maximum length of name, default 50
    :param checkused: Function to check if a generated name is available for use
    :param int counter: Starting position for name counter

    >>> make_name('This is a title')
    'this-is-a-title'
    >>> make_name('Invalid URL/slug here')
    'invalid-url-slug-here'
    >>> make_name('this.that')
    'this-that'
    >>> make_name('this:that')
    'this-that'
    >>> make_name("How 'bout this?")
    'how-bout-this'
    >>> make_name("How’s that?")
    'hows-that'
    >>> make_name('K & D')
    'k-d'
    >>> make_name('billion+ pageviews')
    'billion-pageviews'
    >>> make_name('हिन्दी slug!')
    'hindii-slug'
    >>> make_name('Talk in español, Kiswahili, 廣州話 and অসমীয়া too.', maxlength=250)
    'talk-in-espanol-kiswahili-guang-zhou-hua-and-asmiiyaa-too'
    >>> make_name('__name__', delim='_')
    'name'
    >>> make_name('how_about_this', delim='_')
    'how_about_this'
    >>> make_name('and-that', delim='_')
    'and_that'
    >>> make_name('Umlauts in Mötörhead')
    'umlauts-in-motorhead'
    >>> make_name('Candidate', checkused=lambda c: c in ['candidate'])
    'candidate2'
    >>> make_name('Candidate', checkused=lambda c: c in ['candidate'], counter=1)
    'candidate1'
    >>> make_name('Candidate',
    ...   checkused=lambda c: c in ['candidate', 'candidate1', 'candidate2'], counter=1)
    'candidate3'
    >>> make_name('Long title, but snipped', maxlength=20)
    'long-title-but-snipp'
    >>> len(make_name('Long title, but snipped', maxlength=20))
    20
    >>> make_name('Long candidate', maxlength=10,
    ...   checkused=lambda c: c in ['long-candi', 'long-cand1'])
    'long-cand2'
    >>> make_name('Lǝnkǝran')
    'lankaran'
    >>> make_name('example@example.com')
    'example-example-com'
    >>> make_name('trailing-delimiter', maxlength=10)
    'trailing-d'
    >>> make_name('trailing-delimiter', maxlength=9)
    'trailing'
    >>> make_name('''test this
    ... newline''')
    'test-this-newline'
    >>> make_name("testing an emoji😁")
    'testing-an-emoji'
    >>> make_name('''testing\t\nmore\r\nslashes''')
    'testing-more-slashes'
    >>> make_name('What if a HTML <tag/>')
    'what-if-a-html-tag'
    >>> make_name('These are equivalent to \x01 through \x1A')
    'these-are-equivalent-to-through'
    >>> make_name("feedback;\x00")
    'feedback'
    """
    name = text.replace('@', delim)
    name = unidecode(name).replace(
        '@', 'a'
    )  # We don't know why unidecode uses '@' for 'a'-like chars
    name = str(
        delim.join(
            [
                _strip_re.sub('', x)
                for x in _punctuation_re.split(name.lower())
                if x != ''
            ]
        )
    )
    candidate = name[:maxlength]
    if candidate.endswith(delim):
        candidate = candidate[:-1]
    if checkused is None:
        return candidate
    existing = checkused(candidate)
    while existing:
        candidate = name[: maxlength - len(str(counter))] + str(counter)
        counter += 1
        existing = checkused(candidate)
    return candidate


def format_currency(value: t.Union[int, float], decimals: int = 2) -> str:
    """
    Return a number suitably formatted for display as currency.

    Separates thousands with commas and includes up to two decimal points.

    .. deprecated:: 0.7.0
        Use Babel for context-sensitive formatting.

    >>> format_currency(1000)
    '1,000'
    >>> format_currency(100)
    '100'
    >>> format_currency(999.95)
    '999.95'
    >>> format_currency(99.95)
    '99.95'
    >>> format_currency(100000)
    '100,000'
    >>> format_currency(1000.00)
    '1,000'
    >>> format_currency(1000.41)
    '1,000.41'
    >>> format_currency(23.21, decimals=3)
    '23.210'
    >>> format_currency(1000, decimals=3)
    '1,000'
    >>> format_currency(123456789.123456789)
    '123,456,789.12'
    """
    # pylint: disable=consider-using-f-string
    number, decimal = (('%%.%df' % decimals) % value).split('.')
    parts = []
    while len(number) > 3:
        part, number = number[-3:], number[:-3]
        parts.append(part)
    parts.append(number)
    parts.reverse()
    if int(decimal) == 0:
        return ','.join(parts)
    return ','.join(parts) + '.' + decimal


def md5sum(data: str) -> str:
    """
    Return md5sum of data as a 32-character string.

    >>> md5sum('random text')
    'd9b9bec3f4cc5482e7c5ef43143e563a'
    >>> md5sum('random text')
    'd9b9bec3f4cc5482e7c5ef43143e563a'
    >>> len(md5sum('random text'))
    32
    """
    return hashlib.md5(data.encode('utf-8')).hexdigest()  # nosec  # skipcq: PTC-W1003


def getbool(value: t.Union[str, int, bool, None]) -> t.Optional[bool]:
    """
    Return a boolean from any of a range of boolean-like values.

    * Returns `True` for ``1``, ``t``, ``true``, ``y`` and ``yes``
    * Returns `False` for ``0``, ``f``, ``false``, ``n`` and ``no``
    * Returns `None` for unrecognized values. Numbers other than 0 and 1 are considered
      unrecognized

    >>> getbool(True)
    True
    >>> getbool(1)
    True
    >>> getbool('1')
    True
    >>> getbool('t')
    True
    >>> getbool(2)
    >>> getbool(0)
    False
    >>> getbool(False)
    False
    >>> getbool('n')
    False
    """
    value = str(value).lower()
    if value in ['1', 't', 'true', 'y', 'yes']:
        return True
    if value in ['0', 'f', 'false', 'n', 'no']:
        return False
    return None


def nullint(value: t.Optional[t.Any]) -> t.Optional[int]:
    """
    Return `int(value)` if `bool(value)` is not `False`. Return `None` otherwise.

    Useful for coercing optional values to an integer.

    >>> nullint('10')
    10
    >>> nullint('') is None
    True
    """
    return int(value) if value else None


def nullstr(value: t.Optional[t.Any]) -> t.Optional[str]:
    """
    Return `str(value)` if `bool(value)` is not `False`. Return `None` otherwise.

    Useful for coercing optional values to a string.

    >>> nullstr(10) == '10'
    True
    >>> nullstr('') is None
    True
    """
    return str(value) if value else None


@overload
def require_one_of(__return: te.Literal[False] = False, /, **kwargs: t.Any) -> None:
    ...


@overload
def require_one_of(
    __return: te.Literal[True], /, **kwargs: t.Any
) -> t.Tuple[str, t.Any]:
    ...


def require_one_of(
    __return: bool = False, /, **kwargs: t.Any
) -> t.Optional[t.Tuple[str, t.Any]]:
    """
    Validate that only one of multiple parameters has a non-None value.

    Use this inside functions that take multiple parameters, but allow only one of them
    to be specified::

        def my_func(this=None, that=None, other=None):
            # Require one and only one of `this` or `that`
            require_one_of(this=this, that=that)

            # If we need to know which parameter was passed in:
            param, value = require_one_of(True, this=this, that=that)

            # Carry on with function logic
            pass

    :param __return: Return the matching parameter name and value
    :param kwargs: Parameters, of which one and only one is mandatory
    :return: If `__return`, matching parameter name and value
    :raises TypeError: If the count of parameters that aren't ``None`` is not 1

    .. deprecated:: 0.7.0
        Use static type checking with @overload declarations to avoid runtime overhead
    """
    # Two ways to count number of non-None parameters:
    #
    # 1. sum([1 if v is not None else 0 for v in kwargs.values()])
    #
    #    This uses a list comprehension instead of a generator comprehension as the
    #    parameter to `sum` is faster on both Python 2 and 3.
    #
    # 2. len(kwargs) - kwargs.values().count(None)
    #
    #    This is 2x faster than the first method under Python 2.7. Unfortunately,
    #    it doesn't work in Python 3 because `kwargs.values()` is a view that doesn't
    #    have a `count` method. It needs to be cast into a tuple/list first, but
    #    remains faster despite the cast's slowdown. Tuples are faster than lists.

    count = len(kwargs) - tuple(kwargs.values()).count(None)

    if count == 0:
        raise TypeError(
            "One of these parameters is required: " + ', '.join(kwargs.keys())
        )
    if count != 1:
        raise TypeError(
            "Only one of these parameters is allowed: " + ', '.join(kwargs.keys())
        )

    if __return:
        keys, values = zip(*((k, 1 if v is not None else 0) for k, v in kwargs.items()))
        k = keys[values.index(1)]
        return k, kwargs[k]
    return None


def get_email_domain(emailaddr: str) -> t.Optional[str]:
    """
    Return the domain component of an email address.

    Returns None if the provided string cannot be parsed as an email address.

    >>> get_email_domain('test@example.com')
    'example.com'
    >>> get_email_domain('test+trailing@example.com')
    'example.com'
    >>> get_email_domain('Example Address <test@example.com>')
    'example.com'
    >>> get_email_domain('foobar')
    >>> get_email_domain('foobar@')
    >>> get_email_domain('@foobar')
    """
    _realname, address = email.utils.parseaddr(emailaddr)
    try:
        username, domain = address.split('@')
        if not username:
            return None
        return domain or None
    except ValueError:
        return None


def namespace_from_url(url: str) -> t.Optional[str]:
    """Construct a dotted namespace string from a URL."""
    parsed = urlparse(url)
    if (
        parsed.hostname is None
        or parsed.hostname in ['localhost', 'localhost.localdomain']
        or (_ipv4_re.search(parsed.hostname))
    ):
        return None

    namespace = parsed.hostname.split('.')
    namespace.reverse()
    if namespace and not namespace[0]:
        namespace.pop(0)
    if namespace and namespace[-1] == 'www':
        namespace.pop(-1)
    return type(url)('.'.join(namespace))


def base_domain_matches(d1: str, d2: str) -> bool:
    """
    Check if two domains have the same base domain, using the Public Suffix List.

    >>> base_domain_matches('https://hasjob.co', 'hasjob.co')
    True
    >>> base_domain_matches('hasgeek.hasjob.co', 'hasjob.co')
    True
    >>> base_domain_matches('hasgeek.com', 'hasjob.co')
    False
    >>> base_domain_matches('static.hasgeek.co.in', 'hasgeek.com')
    False
    >>> base_domain_matches('static.hasgeek.co.in', 'hasgeek.co.in')
    True
    >>> base_domain_matches('example@example.com', 'example.com')
    True
    """
    r1 = tldextract.extract(d1)
    r2 = tldextract.extract(d2)
    # r1 and r2 contain subdomain, domain and suffix.
    # We want to confirm that domain and suffix match.
    return r1.domain == r2.domain and r1.suffix == r2.suffix


def domain_namespace_match(domain: str, namespace: str) -> bool:
    """
    Check if namespace is related to the domain because the base domain matches.

    >>> domain_namespace_match('hasgeek.com', 'com.hasgeek')
    True
    >>> domain_namespace_match('funnel.hasgeek.com', 'com.hasgeek.funnel')
    True
    >>> domain_namespace_match('app.hasgeek.com', 'com.hasgeek.peopleflow')
    True
    >>> domain_namespace_match('app.hasgeek.in', 'com.hasgeek.peopleflow')
    False
    >>> domain_namespace_match('peopleflow.local', 'local.peopleflow')
    True
    """
    return base_domain_matches(domain, '.'.join(namespace.split('.')[::-1]))


T = t.TypeVar('T')


class _CallableSameArgs(te.Protocol):  # pylint: disable=too-few-public-methods
    """Protocl for callable that accepts multiple arguments of the same type."""

    def __call__(self, lhs: T, *others: T) -> T:
        ...


def nary_op(f: t.Callable, doc: t.Optional[str] = None) -> _CallableSameArgs:
    """
    Convert a binary operator function into a chained n-ary operator.

    Example::

        >>> @nary_op
        ... def subtract_all(lhs, rhs):
        ...     return lhs - rhs

    This converts ``subtract_all`` to accept multiple parameters::

        >>> subtract_all(10, 2, 3)
        5
    """

    @wraps(f)
    def inner(lhs: T, *others: T) -> T:
        for other in others:
            lhs = f(lhs, other)
        return lhs

    if doc is not None:
        inner.__doc__ = doc
    return inner
