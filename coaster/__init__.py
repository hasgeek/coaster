# -*- coding: utf-8 -*-

from __future__ import absolute_import
from datetime import datetime
from random import randint, randrange
import uuid
from base64 import urlsafe_b64encode, b64encode, b64decode
import hashlib
import string
import re
from BeautifulSoup import BeautifulSoup, Comment
from warnings import warn

# Compatibility import
from coaster.app import configure as configureapp


# --- Common delimiters and punctuation ---------------------------------------

_strip_re = re.compile(ur'[\'"`‘’“”′″‴]+')
_punctuation_re = re.compile(ur'[\t +!#$%&()*\-/<=>?@\[\\\]^_{|}:;,.…‒–—―«»]+')
_username_valid_re = re.compile('^[a-z0-9][a-z0-9-]*[a-z0-9]$')


# --- Utilities ---------------------------------------------------------------

def newid():
    """
    Return a new random id that is exactly 22 characters long. See
    http://en.wikipedia.org/wiki/Base64#Variants_summary_table
    for URL-safe Base64

    >>> len(newid())
    22
    >>> newid() == newid()
    False
    """
    return urlsafe_b64encode(uuid.uuid4().bytes).rstrip('=')


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


def make_name(text, delim=u'-', maxlength=50, checkused=None):
    u"""
    Generate a Unicode name slug. If a checkused filter is provided, it will
    be called with the candidate. If it returns True, make_name will add
    counter numbers starting from 1 until a suitable candidate is found.

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
    >>> make_name('Candidate', checkused=lambda c: c in ['candidate', 'candidate1'])
    u'candidate2'
    >>> make_name('Long title, but snipped', maxlength=20)
    u'long-title-but-snipp'
    >>> len(make_name('Long title, but snipped', maxlength=20))
    20
    >>> make_name('Long candidate', maxlength=10, checkused=lambda c: c in ['long-candi', 'long-cand1'])
    u'long-cand2'
    """
    name = unicode(delim.join([_strip_re.sub('', x) for x in _punctuation_re.split(text.lower()) if x != '']))
    if checkused is None:
        return _sniplen(name, maxlength)
    candidate = _sniplen(name, maxlength)
    existing = checkused(candidate)
    counter = 0
    while existing:
        counter += 1
        candidate = _sniplen(name, maxlength - len(unicode(counter))) + unicode(counter)
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


def get_email_domain(email):
    """
    Return the domain component of an email address. Returns None if the
    provided string cannot be parsed as an email address.

    >>> get_email_domain('jace@pobox.com')
    'pobox.com'
    >>> get_email_domain('jace+test@pobox.com')
    'pobox.com'
    >>> get_email_domain('foobar')
    """
    try:
        return email.split('@')[1]
    except IndexError:
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
                tag.attrs = [(attr, value) for attr, value in tag.attrs if attr in valid_tags[tag.name]]
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
    """
    return not _username_valid_re.search(candidate) is None
