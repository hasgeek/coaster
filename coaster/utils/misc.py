"""
Miscellaneous utilities
-----------------------
"""

from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime
from email.header import decode_header
from functools import wraps
from random import SystemRandom
from urllib.parse import urlparse
import collections.abc as abc
import email.utils
import hashlib
import re
import time
import uuid

from unidecode import unidecode
import base58
import tldextract

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
    'unicode_http_header',
    'uuid1mc',
    'uuid1mc_from_datetime',
    'uuid2buid',
    'uuid_b58',
    'uuid_b64',
    'uuid_from_base58',
    'uuid_from_base64',
    'uuid_to_base58',
    'uuid_to_base64',
    'valid_username',
]

# --- Common delimiters and punctuation ---------------------------------------

_strip_re = re.compile('[\'"`‘’“”′″‴]+')
_punctuation_re = re.compile(
    '[\x00-\x1f +!#$%&()*\\-/<=>?@\\[\\\\\\]^_{|}:;,.…‒–—―«»]+'
)
_username_valid_re = re.compile('^[a-z0-9]([a-z0-9-]*[a-z0-9])?$')
_ipv4_re = re.compile(
    r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}'
    r'(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
)


# --- Utilities ---------------------------------------------------------------


def is_collection(item):
    """
    Returns True if the item is a collection class: list, tuple, set, frozenset
    or any other class that resembles one of these (using abstract base classes).

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
    return not isinstance(item, (str, bytes)) and isinstance(
        item, (abc.Set, abc.Sequence)
    )


def uuid_b64():
    """
    Return a new random id that is exactly 22 characters long,
    by encoding a UUID4 in URL-safe Base64. See
    http://en.wikipedia.org/wiki/Base64#Variants_summary_table

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


def uuid_b58():
    """
    Return a UUID4 encoded in base58 and rendered as a string. Will be 21 or 22
    characters long

    >>> len(uuid_b58()) in (21, 22)
    True
    >>> uuid_b58() == uuid_b58()
    False
    >>> isinstance(uuid_b58(), str)
    True
    """
    return base58.b58encode(uuid.uuid4().bytes).decode()


def uuid1mc():
    """
    Return a UUID1 with a random multicast MAC id.

    >>> isinstance(uuid1mc(), uuid.UUID)
    True
    """
    return uuid.uuid1(node=uuid._random_getnode())


def uuid1mc_from_datetime(dt):
    """
    Return a UUID1 with a random multicast MAC id and with a timestamp
    matching the given datetime object or timestamp value.

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

    return uuid.UUID(fields=tuple(fields))


def uuid_to_base64(value):
    """
    Convert a UUID object to a 22-char URL-safe Base64 string (BUID)

    >>> uuid_to_base64(uuid.UUID('33203dd2-f2ef-422f-aeb0-058d6f5f7089'))
    'MyA90vLvQi-usAWNb19wiQ'
    """
    return urlsafe_b64encode(value.bytes).decode().rstrip('=')


#: Legacy name
uuid2buid = uuid_to_base64


def uuid_from_base64(value):
    """
    Convert a 22-char URL-safe Base64 string (BUID) to a UUID object

    >>> uuid_from_base64('MyA90vLvQi-usAWNb19wiQ')
    UUID('33203dd2-f2ef-422f-aeb0-058d6f5f7089')
    """
    return uuid.UUID(bytes=urlsafe_b64decode(str(value) + '=='))


#: Legacy name
buid2uuid = uuid_from_base64


def uuid_to_base58(value):
    """
    Render a UUID in Base58 and return as a string

    >>> uuid_to_base58(uuid.UUID('33203dd2-f2ef-422f-aeb0-058d6f5f7089'))
    '7KAmj837MyuJWUYPwtqAfz'
    >>> # The following UUID to Base58 encoding is from NPM uuid-base58, for comparison
    >>> uuid_to_base58(uuid.UUID('d7ce8475-e77c-43b0-9dde-56b428981999'))
    'TedLUruK7MosG1Z88urTkk'
    """
    return base58.b58encode(value.bytes).decode()


def uuid_from_base58(value):
    """
    Convert a Base58-encoded UUID back into a UUID object

    >>> uuid_from_base58('7KAmj837MyuJWUYPwtqAfz')
    UUID('33203dd2-f2ef-422f-aeb0-058d6f5f7089')
    >>> # The following UUID to Base58 encoding is from NPM uuid-base58, for comparison
    >>> uuid_from_base58('TedLUruK7MosG1Z88urTkk')
    UUID('d7ce8475-e77c-43b0-9dde-56b428981999')
    """
    return uuid.UUID(bytes=base58.b58decode(str(value)))


def newsecret():
    """
    Make a secret key for non-cryptographic use cases like email account verification.
    Mashes two UUID4s into a Base58 rendering, between 42 and 44 characters long. The
    resulting string consists of only ASCII strings and so will typically not be
    word-wrapped by email clients.

    >>> len(newsecret()) in (42, 43, 44)
    True
    >>> newsecret() == newsecret()
    False
    """
    return uuid_b58() + uuid_b58()


def newpin(digits=4):
    """
    Return a random numeric string with the specified number of digits,
    default 4.

    >>> len(newpin())
    4
    >>> len(newpin(5))
    5
    >>> newpin().isdigit()
    True
    """
    random = SystemRandom()
    randnum = random.randint(0, 10 ** digits)  # noqa: S311 # nosec
    while len(str(randnum)) > digits:
        randnum = random.randint(0, 10 ** digits)  # noqa: S311 # nosec
    return ('%%0%dd' % digits) % randnum


def make_name(text, delim='-', maxlength=50, checkused=None, counter=2):
    """
    Generate an ASCII name slug. If a checkused filter is provided, it will
    be called with the candidate. If it returns True, make_name will add
    counter numbers starting from 2 until a suitable candidate is found.

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
    >>> make_name('''testing\\t\\nmore\\r\\nslashes''')
    'testing-more-slashes'
    >>> make_name('What if a HTML <tag/>')
    'what-if-a-html-tag'
    >>> make_name('These are equivalent to \\x01 through \\x1A')
    'these-are-equivalent-to-through'
    >>> make_name("feedback;\\x00")
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


def format_currency(value, decimals=2):
    """
    Return a number suitably formatted for display as currency, with
    thousands separated by commas and up to two decimal points.

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
    number, decimal = (('%%.%df' % decimals) % value).split('.')
    parts = []
    while len(number) > 3:
        part, number = number[-3:], number[:-3]
        parts.append(part)
    parts.append(number)
    parts.reverse()
    if int(decimal) == 0:
        return ','.join(parts)
    else:
        return ','.join(parts) + '.' + decimal


def md5sum(data):
    """
    Return md5sum of data as a 32-character string.

    >>> md5sum('random text')
    'd9b9bec3f4cc5482e7c5ef43143e563a'
    >>> md5sum('random text')
    'd9b9bec3f4cc5482e7c5ef43143e563a'
    >>> len(md5sum('random text'))
    32
    """
    return hashlib.md5(  # noqa: S303 # skipcq: PTC-W1003 # nosec
        data.encode('utf-8')
    ).hexdigest()


def getbool(value):
    """
    Returns a boolean from any of a range of values. Returns None for
    unrecognized values. Numbers other than 0 and 1 are considered
    unrecognized.

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
    elif value in ['0', 'f', 'false', 'n', 'no']:
        return False
    return None


def nullint(value):
    """
    Return int(value) if bool(value) is not False. Return None otherwise.
    Useful for coercing optional values to an integer.

    >>> nullint('10')
    10
    >>> nullint('') is None
    True
    """
    return int(value) if value else None


def nullstr(value):
    """
    Return unicode(value) if bool(value) is not False. Return None otherwise.
    Useful for coercing optional values to a string.

    >>> nullstr(10) == '10'
    True
    >>> nullstr('') is None
    True
    """
    return str(value) if value else None


nullunicode = nullstr  # XXX: Deprecated name. Remove soon.


def require_one_of(_return=False, **kwargs):
    """
    Validator that raises :exc:`TypeError` unless one and only one parameter is
    not ``None``. Use this inside functions that take multiple parameters, but
    allow only one of them to be specified::

        def my_func(this=None, that=None, other=None):
            # Require one and only one of `this` or `that`
            require_one_of(this=this, that=that)

            # If we need to know which parameter was passed in:
            param, value = require_one_of(True, this=this, that=that)

            # Carry on with function logic
            pass

    :param _return: Return the matching parameter
    :param kwargs: Parameters, of which one and only one is mandatory
    :return: If `_return`, matching parameter name and value
    :rtype: tuple
    :raises TypeError: If the count of parameters that aren't ``None`` is not 1
    """

    # Two ways to count number of non-None parameters:
    #
    # 1. sum([1 if v is not None else 0 for v in kwargs.values()])
    #
    #    Using a list comprehension instead of a generator comprehension as the
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

    if _return:
        keys, values = zip(*((k, 1 if v is not None else 0) for k, v in kwargs.items()))
        k = keys[values.index(1)]
        return k, kwargs[k]


def unicode_http_header(value):
    r"""
    Convert an ASCII HTTP header string into a unicode string with the
    appropriate encoding applied. Expects headers to be RFC 2047 compliant.

    >>> unicode_http_header('=?iso-8859-1?q?p=F6stal?=') == 'p\xf6stal'
    True
    >>> unicode_http_header(b'=?iso-8859-1?q?p=F6stal?=') == 'p\xf6stal'
    True
    >>> unicode_http_header('p\xf6stal') == 'p\xf6stal'
    True
    """
    # email.header.decode_header expects strings, not bytes. Your input data may be
    # in bytes. Since these bytes are almost always ASCII, calling `.decode()` on
    # it without specifying a charset should work fine.
    if isinstance(value, bytes):
        value = value.decode()
    return ''.join(
        str(s, e or 'iso-8859-1') if not isinstance(s, str) else s
        for s, e in decode_header(value)
    )


def get_email_domain(emailaddr):
    """
    Return the domain component of an email address. Returns None if the
    provided string cannot be parsed as an email address.

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
    realname, address = email.utils.parseaddr(emailaddr)
    try:
        username, domain = address.split('@')
        if not username:
            return None
        return domain or None
    except ValueError:
        return None


def valid_username(candidate):
    """
    Check if a username is valid.

    >>> valid_username('example person')
    False
    >>> valid_username('example_person')
    False
    >>> valid_username('exampleperson')
    True
    >>> valid_username('example-person')
    True
    >>> valid_username('a')
    True
    >>> (valid_username('a-') or valid_username('ab-') or valid_username('-a') or
    ...   valid_username('-ab'))
    False
    """
    return not _username_valid_re.search(candidate) is None


def namespace_from_url(url):
    """
    Construct a dotted namespace string from a URL.
    """
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


def base_domain_matches(d1, d2):
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


def domain_namespace_match(domain, namespace):
    """
    Checks if namespace is related to the domain because the base domain matches.

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
    return base_domain_matches(domain, ".".join(namespace.split(".")[::-1]))


def nary_op(f, doc=None):
    """
    Decorator to convert a binary operator into a chained n-ary operator.
    """

    @wraps(f)
    def inner(lhs, *others):
        for other in others:
            lhs = f(lhs, other)
        return lhs

    if doc is not None:
        inner.__doc__ = doc
    return inner
