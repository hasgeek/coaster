# -*- coding: utf-8 -*-

"""
Miscellaneous utilities
-----------------------
"""

from __future__ import absolute_import
import collections
import time
from datetime import datetime
from random import randint, randrange
import uuid
from base64 import urlsafe_b64encode, urlsafe_b64decode, b64encode, b64decode
import hashlib
import re
import binascii
import email.utils
from email.header import decode_header
import bcrypt
import pytz
import tldextract
from unidecode import unidecode
import isoweek
import six
from six.moves import range
from six.moves.urllib.parse import urlparse


# --- Thread safety fix -------------------------------------------------------

# Force import of strptime, used in :func:`parse_isoformat`
# http://stackoverflow.com/questions/16309650/python-importerror-for-strptime-in-spyder-for-windows-7
datetime.strptime('20160816', '%Y%m%d')


# --- Common delimiters and punctuation ---------------------------------------

_strip_re = re.compile(u'[\'"`‘’“”′″‴]+')
_punctuation_re = re.compile(u'[\x01-\x1f +!#$%&()*\\-/<=>?@\\[\\\\\\]^_{|}:;,.…‒–—―«»]+')
_username_valid_re = re.compile('^[a-z0-9]([a-z0-9-]*[a-z0-9])?$')
_ipv4_re = re.compile(r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$')
_tag_re = re.compile('<.*?>')


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
    return not isinstance(item, six.string_types) and isinstance(item, (collections.Set, collections.Sequence))


def buid():
    """
    Return a new random id that is exactly 22 characters long,
    by encoding a UUID4 in URL-safe Base64. See
    http://en.wikipedia.org/wiki/Base64#Variants_summary_table

    >>> len(buid())
    22
    >>> buid() == buid()
    False
    >>> isinstance(buid(), six.text_type)
    True
    """
    if six.PY3:  # pragma: no cover
        return urlsafe_b64encode(uuid.uuid4().bytes).decode('utf-8').rstrip('=')
    else:  # pragma: no cover
        return six.text_type(urlsafe_b64encode(uuid.uuid4().bytes).rstrip('='))


def uuid1mc():
    """
    Return a UUID1 with a random multicast MAC id
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
    timestamp = int(nanoseconds // 100) + 0x01b21dd213814000
    time_low = timestamp & 0xffffffff
    time_mid = (timestamp >> 32) & 0xffff
    time_hi_version = (timestamp >> 48) & 0x0fff

    fields[0] = time_low
    fields[1] = time_mid
    fields[2] = time_hi_version

    return uuid.UUID(fields=tuple(fields))


def uuid2buid(value):
    """
    Convert a UUID object to a 22-char BUID string

    >>> u = uuid.UUID('33203dd2-f2ef-422f-aeb0-058d6f5f7089')
    >>> uuid2buid(u)
    'MyA90vLvQi-usAWNb19wiQ'
    """
    if six.PY3:  # pragma: no cover
        return urlsafe_b64encode(value.bytes).decode('utf-8').rstrip('=')
    else:
        return six.text_type(urlsafe_b64encode(value.bytes).rstrip('='))


def buid2uuid(value):
    """
    Convert a 22-char BUID string to a UUID object

    >>> b = u'MyA90vLvQi-usAWNb19wiQ'
    >>> buid2uuid(b)
    UUID('33203dd2-f2ef-422f-aeb0-058d6f5f7089')
    """
    return uuid.UUID(bytes=urlsafe_b64decode(str(value) + '=='))


def newsecret():
    """
    Make a secret key for email confirmation and all that stuff.
    44 characters long.

    >>> len(newsecret())
    44
    >>> newsecret() == newsecret()
    False
    """
    return buid() + buid()


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
    randnum = randint(0, 10 ** digits)
    while len(str(randnum)) > digits:
        randnum = randint(0, 10 ** digits)
    return (u'%%0%dd' % digits) % randnum


def make_name(text, delim=u'-', maxlength=50, checkused=None, counter=2):
    u"""
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
    >>> make_name(u"How’s that?")
    'hows-that'
    >>> make_name(u'K & D')
    'k-d'
    >>> make_name('billion+ pageviews')
    'billion-pageviews'
    >>> make_name(u'हिन्दी slug!')
    'hindii-slug'
    >>> make_name(u'Your webapps should talk not just in English, but in español, Kiswahili, 廣州話 and অসমীয়া too.', maxlength=250)
    u'your-webapps-should-talk-not-just-in-english-but-in-espanol-kiswahili-guang-zhou-hua-and-asmiiyaa-too'
    >>> make_name(u'__name__', delim=u'_')
    'name'
    >>> make_name(u'how_about_this', delim=u'_')
    'how_about_this'
    >>> make_name(u'and-that', delim=u'_')
    'and_that'
    >>> make_name(u'Umlauts in Mötörhead')
    'umlauts-in-motorhead'
    >>> make_name('Candidate', checkused=lambda c: c in ['candidate'])
    'candidate2'
    >>> make_name('Candidate', checkused=lambda c: c in ['candidate'], counter=1)
    'candidate1'
    >>> make_name('Candidate', checkused=lambda c: c in ['candidate', 'candidate1', 'candidate2'], counter=1)
    'candidate3'
    >>> make_name('Long title, but snipped', maxlength=20)
    'long-title-but-snipp'
    >>> len(make_name('Long title, but snipped', maxlength=20))
    20
    >>> make_name('Long candidate', maxlength=10, checkused=lambda c: c in ['long-candi', 'long-cand1'])
    'long-cand2'
    >>> make_name(u'Lǝnkǝran')
    'lankaran'
    >>> make_name(u'example@example.com')
    'example-example-com'
    >>> make_name('trailing-delimiter', maxlength=10)
    'trailing-d'
    >>> make_name('trailing-delimiter', maxlength=9)
    'trailing'
    >>> make_name('''test this
    ... newline''')
    'test-this-newline'
    >>> make_name(u"testing an emoji😁")
    u'testing-an-emoji'
    >>> make_name('''testing\\t\\nmore\\r\\nslashes''')
    'testing-more-slashes'
    >>> make_name('What if a HTML <tag/>')
    'what-if-a-html-tag'
    >>> make_name('These are equivalent to \x01 through \x1A')
    'these-are-equivalent-to-through'
    """
    name = text.replace('@', delim)
    name = unidecode(name).replace('@', 'a')  # We don't know why unidecode uses '@' for 'a'-like chars
    name = six.text_type(delim.join([_strip_re.sub('', x) for x in _punctuation_re.split(name.lower()) if x != '']))
    if isinstance(text, six.text_type):
        # Unidecode returns str. Restore to a unicode string if original was unicode
        name = six.text_type(name)
    candidate = name[:maxlength]
    if candidate.endswith(delim):
        candidate = candidate[:-1]
    if checkused is None:
        return candidate
    existing = checkused(candidate)
    while existing:
        candidate = name[:maxlength - len(str(counter))] + str(counter)
        counter += 1
        existing = checkused(candidate)
    return candidate


def make_password(password, encoding='BCRYPT'):
    """
    Make a password with PLAIN, SSHA or BCRYPT (default) encoding.

    >>> make_password('foo', encoding='PLAIN')
    '{PLAIN}foo'
    >>> make_password(u're-foo', encoding='SSHA')[:6]
    '{SSHA}'
    >>> make_password(u're-foo')[:8]
    '{BCRYPT}'
    >>> make_password('foo') == make_password('foo')
    False
    """
    if encoding not in ['PLAIN', 'SSHA', 'BCRYPT']:
        raise ValueError("Unknown encoding %s" % encoding)
    if encoding == 'PLAIN':
        if isinstance(password, str) and six.PY2:
            password = six.text_type(password, 'utf-8')
        return '{PLAIN}%s' % password
    elif encoding == 'SSHA':
        # SSHA is a modification of the SHA digest scheme with a salt
        # starting at byte 20 of the base64-encoded string.
        # Source: http://developer.netscape.com/docs/technote/ldap/pass_sha.html
        # This implementation is from Zope2's AccessControl.AuthEncoding.

        salt = ''
        for n in range(7):
            salt += chr(randrange(256))
        # b64encode accepts only bytes in Python 3, so salt also has to be encoded
        salt = salt.encode('utf-8') if six.PY3 else salt
        if isinstance(password, six.text_type):
            password = password.encode('utf-8')
        else:
            password = str(password)
        b64_encoded = b64encode(hashlib.sha1(password + salt).digest() + salt)
        b64_encoded = b64_encoded.decode('utf-8') if six.PY3 else b64_encoded
        return '{SSHA}%s' % b64_encoded
    elif encoding == 'BCRYPT':
        # BCRYPT is the recommended hash for secure passwords
        password_hashed = bcrypt.hashpw(
            password.encode('utf-8') if isinstance(password, six.text_type) else password,
            bcrypt.gensalt())
        if six.PY3:  # pragma: no cover
            password_hashed = password_hashed.decode('utf-8')
        return '{BCRYPT}%s' % password_hashed


def check_password(reference, attempt):
    """
    Compare a reference password with the user attempt.

    >>> check_password('{PLAIN}foo', 'foo')
    True
    >>> check_password(u'{PLAIN}bar', 'bar')
    True
    >>> check_password(u'{UNKNOWN}baz', 'baz')
    False
    >>> check_password(u'no-encoding', u'no-encoding')
    False
    >>> check_password(u'{SSHA}q/uVU8r15k/9QhRi92CWUwMJu2DM6TUSpp25', u're-foo')
    True
    >>> check_password(u'{BCRYPT}$2b$12$NfKivgz7njR3/rWZ56EsDe7..PPum.fcmFLbdkbP.chtMTcS1s01C', 'foo')
    True
    """
    if reference.startswith(u'{PLAIN}'):
        if reference[7:] == attempt:
            return True
    elif reference.startswith(u'{SSHA}'):
        # In python3 b64decode takes inputtype as bytes as opposed to str in python 2, and returns
        # binascii.Error as opposed to TypeError
        if six.PY3:  # pragma: no cover
            try:
                if isinstance(reference, six.text_type):
                    ref = b64decode(reference[6:].encode('utf-8'))
                else:
                    ref = b64decode(reference[6:])
            except binascii.Error:
                return False  # Not Base64
        else:  # pragma: no cover
            try:
                ref = b64decode(reference[6:])
            except TypeError:
                return False  # Not Base64
        if isinstance(attempt, six.text_type):
            attempt = attempt.encode('utf-8')
        salt = ref[20:]
        b64_encoded = b64encode(hashlib.sha1(attempt + salt).digest() + salt)
        if six.PY3:  # pragma: no cover
            # type(b64_encoded) is bytes and can't be compared with type(reference) which is str
            compare = six.text_type('{SSHA}%s' % b64_encoded.decode('utf-8') if type(b64_encoded) is bytes else b64_encoded)
        else:  # pragma: no cover
            compare = six.text_type('{SSHA}%s' % b64_encoded)
        return (compare == reference)
    elif reference.startswith(u'{BCRYPT}'):
        # bcrypt.hashpw() accepts either a unicode encoded string or the basic string (python 2)
        if isinstance(attempt, six.text_type) or isinstance(reference, six.text_type):
            attempt = attempt.encode('utf-8')
            reference = reference.encode('utf-8')
        if six.PY3:  # pragma: no cover
            return bcrypt.hashpw(attempt, reference[8:]) == reference[8:]
        else:  # pragma: no cover
            return bcrypt.hashpw(
                attempt.encode('utf-8') if isinstance(attempt, six.text_type) else attempt,
                str(reference[8:])) == reference[8:]
    return False


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
    number, decimal = ((u'%%.%df' % decimals) % value).split(u'.')
    parts = []
    while len(number) > 3:
        part, number = number[-3:], number[:-3]
        parts.append(part)
    parts.append(number)
    parts.reverse()
    if int(decimal) == 0:
        return u','.join(parts)
    else:
        return u','.join(parts) + u'.' + decimal


def md5sum(data):
    """
    Return md5sum of data as a 32-character string.

    >>> md5sum('random text')
    'd9b9bec3f4cc5482e7c5ef43143e563a'
    >>> md5sum(u'random text')
    'd9b9bec3f4cc5482e7c5ef43143e563a'
    >>> len(md5sum('random text'))
    32
    """
    if six.PY3:  # pragma: no cover
        return hashlib.md5(data.encode('utf-8')).hexdigest()
    else:  # pragma: no cover
        return hashlib.md5(data).hexdigest()


def parse_isoformat(text):
    try:
        return datetime.strptime(text, '%Y-%m-%dT%H:%M:%S.%fZ')
    except ValueError:
        return datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ')


def isoweek_datetime(year, week, timezone='UTC', naive=False):
    """
    Returns a datetime matching the starting point of a specified ISO week
    in the specified timezone (default UTC). Returns a naive datetime in
    UTC if requested (default False).

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
    if isinstance(timezone, six.string_types):
        tz = pytz.timezone(timezone)
    else:
        tz = timezone
    dt = tz.localize(naivedt).astimezone(pytz.UTC)
    if naive:
        return dt.replace(tzinfo=None)
    else:
        return dt


def midnight_to_utc(dt, timezone=None, naive=False):
    """
    Returns a UTC datetime matching the midnight for the given date or datetime.

    >>> from datetime import date
    >>> midnight_to_utc(datetime(2017, 1, 1))
    datetime.datetime(2017, 1, 1, 0, 0, tzinfo=<UTC>)
    >>> midnight_to_utc(pytz.timezone('Asia/Kolkata').localize(datetime(2017, 1, 1)))
    datetime.datetime(2016, 12, 31, 18, 30, tzinfo=<UTC>)
    >>> midnight_to_utc(datetime(2017, 1, 1), naive=True)
    datetime.datetime(2017, 1, 1, 0, 0)
    >>> midnight_to_utc(pytz.timezone('Asia/Kolkata').localize(datetime(2017, 1, 1)), naive=True)
    datetime.datetime(2016, 12, 31, 18, 30)
    >>> midnight_to_utc(date(2017, 1, 1))
    datetime.datetime(2017, 1, 1, 0, 0, tzinfo=<UTC>)
    >>> midnight_to_utc(date(2017, 1, 1), naive=True)
    datetime.datetime(2017, 1, 1, 0, 0)
    >>> midnight_to_utc(date(2017, 1, 1), timezone='Asia/Kolkata')
    datetime.datetime(2016, 12, 31, 18, 30, tzinfo=<UTC>)
    >>> midnight_to_utc(datetime(2017, 1, 1), timezone='Asia/Kolkata')
    datetime.datetime(2016, 12, 31, 18, 30, tzinfo=<UTC>)
    >>> midnight_to_utc(pytz.timezone('Asia/Kolkata').localize(datetime(2017, 1, 1)), timezone='UTC')
    datetime.datetime(2017, 1, 1, 0, 0, tzinfo=<UTC>)
    """
    if timezone:
        if isinstance(timezone, six.string_types):
            tz = pytz.timezone(timezone)
        else:
            tz = timezone
    elif isinstance(dt, datetime) and dt.tzinfo:
        tz = dt.tzinfo
    else:
        tz = pytz.UTC

    utc_dt = tz.localize(datetime.combine(dt, datetime.min.time())).astimezone(pytz.UTC)
    if naive:
        return utc_dt.replace(tzinfo=None)
    return utc_dt


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
    if value:
        return int(value)


def nullstr(value):
    """
    Return unicode(value) if bool(value) is not False. Return None otherwise.
    Useful for coercing optional values to a string.

    >>> nullstr(10) == '10'
    True
    >>> nullstr('') is None
    True
    """
    if value:
        return six.text_type(value)


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

    if six.PY3:  # pragma: no cover
        count = len(kwargs) - tuple(kwargs.values()).count(None)
    else:  # pragma: no cover
        count = len(kwargs) - kwargs.values().count(None)

    if count == 0:
        raise TypeError("One of these parameters is required: " + ', '.join(kwargs.keys()))
    elif count != 1:
        raise TypeError("Only one of these parameters is allowed: " + ', '.join(kwargs.keys()))

    if _return:
        keys, values = zip(*[(k, 1 if v is not None else 0) for k, v in kwargs.items()])
        k = keys[values.index(1)]
        return k, kwargs[k]


def unicode_http_header(value):
    """
    Convert an ASCII HTTP header string into a unicode string with the
    appropriate encoding applied. Expects headers to be RFC 2047 compliant.

    >>> unicode_http_header('=?iso-8859-1?q?p=F6stal?=') == u'p\xf6stal'
    True
    >>> unicode_http_header(b'=?iso-8859-1?q?p=F6stal?=') == u'p\xf6stal'
    True
    >>> unicode_http_header('p\xf6stal') == u'p\xf6stal'
    True
    """
    if six.PY3:  # pragma: no cover
        # email.header.decode_header expects strings, not bytes. Your input data may be in bytes.
        # Since these bytes are almost always ASCII, calling `.decode()` on it without specifying
        # a charset should work fine.
        if isinstance(value, six.binary_type):
            value = value.decode()
    return u''.join([six.text_type(s, e or 'iso-8859-1') if not isinstance(s, six.text_type) else s
        for s, e in decode_header(value)])


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
    >>> get_email_domain('foo@bar@baz')
    'bar'
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
    >>> valid_username('a-') or valid_username('ab-') or valid_username('-a') or valid_username('-ab')
    False
    """
    return not _username_valid_re.search(candidate) is None


def sorted_timezones():
    """
    Return a list of timezones sorted by offset from UTC.
    """
    def hourmin(delta):
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

    # Make a list of timezones, discarding the US/* and Canada/* zones since they aren't reliable for
    # DST, and discarding UTC and GMT since timezones in that zone have their own names
    timezones = [(pytz.timezone(tzname).utcoffset(now, is_dst=False), tzname) for tzname in pytz.common_timezones
        if not tzname.startswith('US/') and not tzname.startswith('Canada/') and tzname not in ('GMT', 'UTC')]
    # Sort timezones by offset from UTC and their human-readable name
    presorted = [(delta, '%s%s - %s%s (%s)' % (
        (delta.days < 0 and '-') or (delta.days == 0 and delta.seconds == 0 and ' ') or '+',
        '%02d:%02d' % hourmin(delta),
        (pytz.country_names[timezone_country[name]] + ': ') if name in timezone_country else '',
        name.replace('_', ' '),
        pytz.timezone(name).tzname(now, is_dst=False)), name) for delta, name in timezones]
    presorted.sort()
    # Return a list of (timezone, label) with the timezone offset included in the label.
    return [(name, label) for (delta, label, name) in presorted]


def namespace_from_url(url):
    """
    Construct a dotted namespace string from a URL.
    """
    parsed = urlparse(url)
    if parsed.hostname is None or parsed.hostname in ['localhost', 'localhost.localdomain'] or (
            _ipv4_re.search(parsed.hostname)):
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
