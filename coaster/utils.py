# -*- coding: utf-8 -*-

from __future__ import absolute_import
from datetime import datetime
from random import randint, randrange
import uuid
from base64 import urlsafe_b64encode, b64encode, b64decode
import hashlib
import string
import unicodedata
import re
from warnings import warn
from BeautifulSoup import BeautifulSoup, Comment
import pytz
from urlparse import urlparse

try:
    from collections import OrderedDict
except ImportError:
    from ordereddict import OrderedDict

from ._version import *


# --- Common delimiters and punctuation ---------------------------------------

_strip_re = re.compile(ur'[\'"`‘’“”′″‴]+')
_punctuation_re = re.compile(ur'[\t +!#$%&()*\-/<=>?@\[\\\]^_{|}:;,.…‒–—―«»]+')
_diacritics_re = re.compile(u'[\u0300-\u036F]+')
_username_valid_re = re.compile('^[a-z0-9]([a-z0-9-]*[a-z0-9])?$')
_ipv4_re = re.compile('^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$')


# --- Utilities ---------------------------------------------------------------

def buid():
    """
    Return a new random id that is exactly 22 characters long. See
    http://en.wikipedia.org/wiki/Base64#Variants_summary_table
    for URL-safe Base64

    >>> len(newid())
    22
    >>> newid() == newid()
    False
    >>> isinstance(newid(), unicode)
    True
    """
    return unicode(urlsafe_b64encode(uuid.uuid4().bytes).rstrip('='))

# Retain old name
newid = buid


def newsecret():
    """
    Make a secret key for email confirmation and all that stuff.

    >>> len(newsecret())
    44
    >>> newsecret() == newsecret()
    False
    """
    return newid() + newid()


def newpin(digits=4):
    """
    Return a random numeric string with the specified number of digits,
    default 4.

    >>> len(newpin())
    4
    >>> len(newpin(5))
    5
    >>> isinstance(int(newpin()), int)
    True
    """
    return (u'%%0%dd' % digits) % randint(0, 10 ** digits)


def _sniplen(text, length):
    """
    Cut text at specified length.

    >>> _sniplen('test', 4)
    'test'
    >>> _sniplen('test', 10)
    'test'
    >>> _sniplen('test', 3)
    'tes'
    """
    if len(text) > length:
        return text[:length]
    else:
        return text


def make_name(text, delim=u'-', maxlength=50, checkused=None, counter=2):
    u"""
    Generate a Unicode name slug. If a checkused filter is provided, it will
    be called with the candidate. If it returns True, make_name will add
    counter numbers starting from 2 until a suitable candidate is found.

    :param string delim: Delimiter between words, default '-'
    :param int maxlength: Maximum length of name, default 50
    :param checkused: Function to check if a generated name is available for use
    :param int counter: Starting position for name counter

    >>> make_name('This is a title')
    u'this-is-a-title'
    >>> make_name('Invalid URL/slug here')
    u'invalid-url-slug-here'
    >>> make_name('this.that')
    u'this-that'
    >>> make_name('this:that')
    u'this-that'
    >>> make_name("How 'bout this?")
    u'how-bout-this'
    >>> make_name(u"How’s that?")
    u'hows-that'
    >>> make_name(u'K & D')
    u'k-d'
    >>> make_name('billion+ pageviews')
    u'billion-pageviews'
    >>> make_name(u'हिन्दी slug!') == u'हिन्दी-slug'
    True
    >>> make_name(u'__name__', delim=u'_')
    u'name'
    >>> make_name(u'how_about_this', delim=u'_')
    u'how_about_this'
    >>> make_name(u'and-that', delim=u'_')
    u'and_that'
    >>> make_name(u'Umlauts in Mötörhead')
    u'umlauts-in-motorhead'
    >>> make_name('Candidate', checkused=lambda c: c in ['candidate'])
    u'candidate2'
    >>> make_name('Candidate', checkused=lambda c: c in ['candidate'], counter=1)
    u'candidate1'
    >>> make_name('Candidate', checkused=lambda c: c in ['candidate', 'candidate1', 'candidate2'], counter=1)
    u'candidate3'
    >>> make_name('Long title, but snipped', maxlength=20)
    u'long-title-but-snipp'
    >>> len(make_name('Long title, but snipped', maxlength=20))
    20
    >>> make_name('Long candidate', maxlength=10, checkused=lambda c: c in ['long-candi', 'long-cand1'])
    u'long-cand2'
    """
    name = unicode(delim.join([_strip_re.sub('', x) for x in _punctuation_re.split(text.lower()) if x != '']))
    name = _diacritics_re.sub('', unicodedata.normalize('NFD', name))
    if checkused is None:
        return _sniplen(name, maxlength)
    candidate = _sniplen(name, maxlength)
    existing = checkused(candidate)
    while existing:
        candidate = _sniplen(name, maxlength - len(unicode(counter))) + unicode(counter)
        counter += 1
        existing = checkused(candidate)
    return candidate


def make_password(password, encoding=u'SSHA'):
    """
    Make a password with PLAIN or SSHA encoding.

    >>> make_password('foo', encoding='PLAIN')
    u'{PLAIN}foo'
    >>> make_password(u'bar', encoding='PLAIN')
    u'{PLAIN}bar'
    >>> make_password(u're-foo')[:6]
    u'{SSHA}'
    >>> make_password('bar-foo')[:6]
    u'{SSHA}'
    >>> make_password('foo') == make_password('foo')
    False
    >>> check_password(make_password('ascii'), 'ascii')
    True
    >>> check_password(make_password('mixed'), u'mixed')
    True
    >>> check_password(make_password(u'unicode'), u'unicode')
    True
    """
    if encoding not in [u'PLAIN', u'SSHA']:
        raise ValueError("Unknown encoding %s" % encoding)
    if encoding == u'PLAIN':
        if isinstance(password, str):
            password = unicode(password, 'utf-8')
        return u"{PLAIN}%s" % password
    elif encoding == u'SSHA':
        # SSHA is a modification of the SHA digest scheme with a salt
        # starting at byte 20 of the base64-encoded string.
        # Source: http://developer.netscape.com/docs/technote/ldap/pass_sha.html
        # This implementation is from Zope2's AccessControl.AuthEncoding.

        salt = ''
        for n in range(7):
            salt += chr(randrange(256))
        if isinstance(password, unicode):
            password = password.encode('utf-8')
        else:
            password = str(password)
        return unicode('{SSHA}%s' % b64encode(hashlib.sha1(password + salt).digest() + salt))


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
    >>> check_password('{SSHA}q/uVU8r15k/9QhRi92CWUwMJu2DM6TUSpp25', 're-foo')
    True
    """
    if reference.startswith('{PLAIN}'):
        if reference[7:] == attempt:
            return True
    elif reference.startswith('{SSHA}'):
        try:
            ref = b64decode(reference[6:])
        except TypeError:
            return False  # Not Base64
        if isinstance(attempt, unicode):
            attempt = attempt.encode('utf-8')
        salt = ref[20:]
        compare = unicode('{SSHA}%s' % b64encode(hashlib.sha1(attempt + salt).digest() + salt))
        return (compare == reference)
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
    if decimal == '00':
        return ','.join(parts)
    else:
        return ','.join(parts) + '.' + decimal


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
    return hashlib.md5(data).hexdigest()


def parse_isoformat(text):
    try:
        return datetime.strptime(text, '%Y-%m-%dT%H:%M:%S.%fZ')
    except ValueError:
        return datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ')


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
    Return str(value) if bool(value) is not False. Return None otherwise.
    Useful for coercing optional values to a string.

    >>> nullstr(10)
    '10'
    >>> nullstr('') is None
    True
    """
    if value:
        return str(value)


def nullunicode(value):
    """
    Return unicode(value) if bool(value) is not False. Return None otherwise.
    Useful for coercing optional values to a string.

    >>> nullunicode(10)
    u'10'
    >>> nullunicode('') is None
    True
    """
    if value:
        return unicode(value)


def get_email_domain(email):
    """
    Return the domain component of an email address. Returns None if the
    provided string cannot be parsed as an email address.

    >>> get_email_domain('test@example.com')
    'example.com'
    >>> get_email_domain('test+trailing@example.com')
    'example.com'
    >>> get_email_domain('foobar')
    >>> get_email_domain('foo@bar@baz')
    >>> get_email_domain('foobar@')
    >>> get_email_domain('@foobar')
    """
    try:
        username, domain = email.split('@')
        if not username:
            return None
        return domain or None
    except ValueError:
        return None


VALID_TAGS = {'strong': [],
              'em': [],
              'p': [],
              'ol': [],
              'ul': [],
              'li': [],
              'br': [],
              'sup': [],
              'sub': [],
              'a': ['href', 'title', 'target'],
              'blockquote': [],
              'h3': [],
              'h4': [],
              'h5': [],
              'h6': [],
              }


def sanitize_html(value, valid_tags=VALID_TAGS):
    """
    Strips unwanted markup out of HTML.

    .. deprecated:: 0.2.5
       Use the bleach library instead.

    """
    # TODO: This function needs unit tests.
    soup = BeautifulSoup(value)
    comments = soup.findAll(text=lambda text: isinstance(text, Comment))
    [comment.extract() for comment in comments]
    # Some markup can be crafted to slip through BeautifulSoup's parser, so
    # we run this repeatedly until it generates the same output twice.
    newoutput = soup.renderContents()
    while 1:
        oldoutput = newoutput
        soup = BeautifulSoup(newoutput)
        for tag in soup.findAll(True):
            if tag.name not in valid_tags:
                tag.hidden = True
            else:
                tag.attrs = [(a, v) for a, v in tag.attrs if a in valid_tags[tag.name]]
        newoutput = soup.renderContents()
        if oldoutput == newoutput:
            break
    warn("This function is deprecated. Please use the bleach library", DeprecationWarning)
    return unicode(newoutput, 'utf-8')


def simplify_text(text):
    """
    Simplify text to allow comparison.

    >>> simplify_text("Awesome Coder wanted at Awesome Company")
    'awesome coder wanted at awesome company'
    >>> simplify_text("Awesome Coder, wanted  at Awesome Company! ")
    'awesome coder wanted at awesome company'
    >>> simplify_text(u"Awesome Coder, wanted  at Awesome Company! ")
    u'awesome coder wanted at awesome company'
    """
    if isinstance(text, unicode):
        text = unicode(text.encode('utf-8').translate(string.maketrans("", ""), string.punctuation).lower(), 'utf-8')
    else:
        text = text.translate(string.maketrans("", ""), string.punctuation).lower()
    return " ".join(text.split())


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
    # Make a list of timezones, discarding the US/* zones since they aren't reliable for
    # DST, and discarding GMT since there's also the equivalent UTC.
    timezones = [(pytz.timezone(tzname).utcoffset(now, is_dst=False), tzname) for tzname in pytz.common_timezones
        if not tzname.startswith('US/') and tzname not in ('GMT', 'UTC')]
    timezones.append((pytz.timezone('UTC').utcoffset(now), 'UTC'))
    # Sort timezones by offset from UTC.
    timezones.sort()
    # Return a list of (timezone, label) with the timezone offset included in the label.
    return [(name, '%s%s - %s' % (
            (delta.days < 0 and '-') or (delta.days == 0 and delta.seconds == 0 and ' ') or '+',
            '%02d:%02d' % hourmin(delta),
            name.replace('_', ' ')),
        ) for delta, name in timezones]


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
    return '.'.join(namespace)


class LabeledEnum(object):
    """
    Labeled enumerations. Declarate an enumeration with values and labels
    (for use in UI)::

        >>> class MY_ENUM(LabeledEnum):
        ...    FIRST = (1, "First")
        ...    THIRD = (3, "Third")
        ...    SECOND = (2, "Second")

    :class:`LabeledEnum` will convert any attribute that is a 2-tuple into
    a value and label pair. Access values as direct attributes of the enumeration::

        >>> MY_ENUM.FIRST
        1
        >>> MY_ENUM.SECOND
        2
        >>> MY_ENUM.THIRD
        3

    Access labels via dictionary lookup on the enumeration::

        >>> MY_ENUM[MY_ENUM.FIRST]
        'First'
        >>> MY_ENUM[2]
        'Second'

    Retrieve a full list of values and labels with ``.items()``. Items are always
    sorted by value regardless of the original definition order (since Python
    doesn't provide a way to preserve that order)::

        >>> MY_ENUM.items()
        [(1, 'First'), (2, 'Second'), (3, 'Third')]
    """
    class __metaclass__(type):
        """Construct labeled enumeration"""
        def __new__(cls, name, bases, attrs):
            labels = {}
            for key, value in tuple(attrs.items()):
                if isinstance(value, tuple) and len(value) == 2:
                    labels[value[0]] = value[1]
                    attrs[key] = value[0]

            sorted_labels = OrderedDict(sorted(labels.items()))
            attrs['__labels__'] = sorted_labels
            return type.__new__(cls, name, bases, attrs)

        def __getitem__(cls, key):
            return cls.__labels__[key]

        def __setitem__(cls, key, value):
            raise TypeError("LabeledEnum is immutable")

    @classmethod
    def items(cls):
        return cls.__labels__.items()
