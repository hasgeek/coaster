# -*- coding: utf-8 -*-

from __future__ import absolute_import
import six
from datetime import datetime
from random import randint, randrange
import uuid
from base64 import urlsafe_b64encode, urlsafe_b64decode, b64encode, b64decode
import hashlib
import string
import re
from urlparse import urlparse
from collections import namedtuple, OrderedDict

import bcrypt
import pytz
import tldextract
from unidecode import unidecode
import html5lib
import bleach

if six.PY3:
    from html import unescape
else:
    import HTMLParser
    unescape = HTMLParser.HTMLParser().unescape
    del HTMLParser

from ._version import *  # NOQA


# --- Common delimiters and punctuation ---------------------------------------

_strip_re = re.compile(ur'[\'"`‘’“”′″‴]+')
_punctuation_re = re.compile(ur'[\t +!#$%&()*\-/<=>?@\[\\\]^_{|}:;,.…‒–—―«»]+')
_username_valid_re = re.compile('^[a-z0-9]([a-z0-9-]*[a-z0-9])?$')
_ipv4_re = re.compile('^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$')
_tag_re = re.compile('<.*?>')


# --- Utilities ---------------------------------------------------------------

def buid():
    """
    Return a new random id that is exactly 22 characters long,
    by encoding a UUID4 in URL-safe Base64. See
    http://en.wikipedia.org/wiki/Base64#Variants_summary_table

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


def uuid1mc():
    """
    Return a UUID1 with a random multicast MAC id
    """
    return uuid.uuid1(node=uuid._random_getnode())


def uuid2buid(value):
    """
    Convert a UUID object to a 22-char BUID string

    >>> u = uuid.UUID('33203dd2-f2ef-422f-aeb0-058d6f5f7089')
    >>> uuid2buid(u)
    u'MyA90vLvQi-usAWNb19wiQ'
    """
    return unicode(urlsafe_b64encode(value.bytes).rstrip('='))


def buid2uuid(value):
    """
    Convert a 22-char BUID string to a UUID object

    >>> b = u'MyA90vLvQi-usAWNb19wiQ'
    >>> buid2uuid(b)
    UUID('33203dd2-f2ef-422f-aeb0-058d6f5f7089')
    """
    return uuid.UUID(bytes=urlsafe_b64decode(str(value + '==')))


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
    u'hows-that'
    >>> make_name(u'K & D')
    u'k-d'
    >>> make_name('billion+ pageviews')
    'billion-pageviews'
    >>> make_name(u'हिन्दी slug!')
    u'hindii-slug'
    >>> make_name(u'__name__', delim=u'_')
    u'name'
    >>> make_name(u'how_about_this', delim=u'_')
    u'how_about_this'
    >>> make_name(u'and-that', delim=u'_')
    u'and_that'
    >>> make_name(u'Umlauts in Mötörhead')
    u'umlauts-in-motorhead'
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
    u'lankaran'
    >>> make_name(u'example@example.com')
    u'example-example-com'
    """
    name = unicode(delim.join([_strip_re.sub('', x) for x in _punctuation_re.split(text.lower()) if x != '']))
    name = unidecode(name).replace('@', 'a')  # We don't know why unidecode uses '@' for 'a'-like chars
    if isinstance(text, unicode):
        # Unidecode returns str. Restore to a unicode string if original was unicode
        name = unicode(name)
    if checkused is None:
        return name[:maxlength]
    candidate = name[:maxlength]
    existing = checkused(candidate)
    while existing:
        candidate = name[:maxlength - len(str(counter))] + str(counter)
        counter += 1
        existing = checkused(candidate)
    return candidate


def make_password(password, encoding=u'BCRYPT'):
    """
    Make a password with PLAIN, SSHA or BCRYPT (default) encoding.

    >>> make_password('foo', encoding='PLAIN')
    u'{PLAIN}foo'
    >>> make_password(u'bar', encoding='PLAIN')
    u'{PLAIN}bar'
    >>> make_password(u're-foo', encoding='SSHA')[:6]
    u'{SSHA}'
    >>> make_password('bar-foo', encoding='SSHA')[:6]
    u'{SSHA}'
    >>> make_password(u're-foo')[:8]
    u'{BCRYPT}'
    >>> make_password('bar-foo')[:8]
    u'{BCRYPT}'
    >>> make_password('foo') == make_password('foo')
    False
    >>> check_password(make_password('ascii'), 'ascii')
    True
    >>> check_password(make_password('mixed'), u'mixed')
    True
    >>> check_password(make_password(u'unicode'), u'unicode')
    True
    """
    if encoding not in [u'PLAIN', u'SSHA', u'BCRYPT']:
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
        return u'{SSHA}%s' % b64encode(hashlib.sha1(password + salt).digest() + salt)
    elif encoding == u'BCRYPT':
        # BCRYPT is the recommended hash for secure passwords
        return u'{BCRYPT}%s' % bcrypt.hashpw(
            password.encode('utf-8') if isinstance(password, unicode) else password,
            bcrypt.gensalt())


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
    if reference.startswith(u'{PLAIN}'):
        if reference[7:] == attempt:
            return True
    elif reference.startswith(u'{SSHA}'):
        try:
            ref = b64decode(reference[6:])
        except TypeError:
            return False  # Not Base64
        if isinstance(attempt, unicode):
            attempt = attempt.encode('utf-8')
        salt = ref[20:]
        compare = unicode('{SSHA}%s' % b64encode(hashlib.sha1(attempt + salt).digest() + salt))
        return (compare == reference)
    elif reference.startswith(u'{BCRYPT}'):
        return bcrypt.hashpw(
            attempt.encode('utf-8') if isinstance(attempt, unicode) else attempt,
            reference[8:]) == reference[8:]
    return False


def format_currency(value, decimals=2):
    """
    Return a number suitably formatted for display as currency, with
    thousands separated by commas and up to two decimal points.

    >>> format_currency(1000)
    u'1,000'
    >>> format_currency(100)
    u'100'
    >>> format_currency(999.95)
    u'999.95'
    >>> format_currency(99.95)
    u'99.95'
    >>> format_currency(100000)
    u'100,000'
    >>> format_currency(1000.00)
    u'1,000'
    >>> format_currency(1000.41)
    u'1,000.41'
    >>> format_currency(23.21, decimals=3)
    u'23.210'
    >>> format_currency(1000, decimals=3)
    u'1,000'
    >>> format_currency(123456789.123456789)
    u'123,456,789.12'
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


_tsquery_tokens_re = re.compile(r'(:\*|\*|&|!|\||AND|OR|NOT|-|\(|\))', re.U)
_whitespace_re = re.compile('\s+', re.U)


def for_tsquery(text):
    """
    Tokenize text into a valid PostgreSQL to_tsquery query.

    >>> for_tsquery(" ")
    ''
    >>> for_tsquery("This is a test")
    "'This is a test'"
    >>> for_tsquery('Match "this AND phrase"')
    "'Match this'&'phrase'"
    >>> for_tsquery('Match "this & phrase"')
    "'Match this'&'phrase'"
    >>> for_tsquery("This NOT that")
    "'This'&!'that'"
    >>> for_tsquery("This & NOT that")
    "'This'&!'that'"
    >>> for_tsquery("This > that")
    "'This > that'"
    >>> for_tsquery("Ruby AND (Python OR JavaScript)")
    "'Ruby'&('Python'|'JavaScript')"
    >>> for_tsquery("Ruby AND NOT (Python OR JavaScript)")
    "'Ruby'&!('Python'|'JavaScript')"
    >>> for_tsquery("Ruby NOT (Python OR JavaScript)")
    "'Ruby'&!('Python'|'JavaScript')"
    >>> for_tsquery("Ruby (Python OR JavaScript) Golang")
    "'Ruby'&('Python'|'JavaScript')&'Golang'"
    >>> for_tsquery("Ruby (Python OR JavaScript) NOT Golang")
    "'Ruby'&('Python'|'JavaScript')&!'Golang'"
    >>> for_tsquery("Java*")
    "'Java':*"
    >>> for_tsquery("Java**")
    "'Java':*"
    >>> for_tsquery("Android || Python")
    "'Android'|'Python'"
    >>> for_tsquery("Missing (bracket")
    "'Missing'&('bracket')"
    >>> for_tsquery("Extra bracket)")
    "('Extra bracket')"
    >>> for_tsquery("Android (Python ())")
    "'Android'&('Python')"
    >>> for_tsquery("Android (Python !())")
    "'Android'&('Python')"
    >>> for_tsquery("()")
    ''
    >>> for_tsquery("() Python")
    "'Python'"
    >>> for_tsquery("!() Python")
    "'Python'"
    >>> for_tsquery("*")
    ''
    """
    tokens = [{'AND': '&', 'OR': '|', 'NOT': '!', '-': '!', '*': ':*'}.get(t, t)
        for t in _tsquery_tokens_re.split(_whitespace_re.sub(' ', text.replace("'", " ").replace('"', ' ')))]
    for counter in range(len(tokens)):
        if tokens[counter] not in ('&', '|', '!', ':*', '(', ')', ' '):
            tokens[counter] = "'" + tokens[counter].strip() + "'"
    tokens = [t for t in tokens if t not in ('', ' ', "''")]
    if not tokens:
        return ''
    counterlength = len(tokens)
    counter = 1
    while counter < counterlength:
        if tokens[counter] == '!' and tokens[counter - 1] not in ('&', '|', '('):
            tokens.insert(counter, '&')
            counter += 1
            counterlength += 1
        elif tokens[counter] == '(' and tokens[counter - 1] not in ('&', '|', '!'):
            tokens.insert(counter, '&')
            counter += 1
            counterlength += 1
        elif tokens[counter] == ')' and tokens[counter - 1] == '(':
            # Empty ()
            tokens.pop(counter)
            tokens.pop(counter - 1)
            counter -= 2
            counterlength -= 2
            # Pop the join with previous segment too
            if tokens and tokens[counter] in ('&', '|'):
                tokens.pop(counter)
                counter -= 1
                counterlength -= 1
            elif tokens and counter == 0 and tokens[counter] == '!':
                tokens.pop(counter)
                counter -= 1
                counterlength -= 1
            elif tokens and counter > 0 and tokens[counter - 1:counter + 1] in (['&', '!'], ['|', '!']):
                tokens.pop(counter)
                tokens.pop(counter - 1)
                counter -= 2
                counterlength -= 2
        elif tokens[counter].startswith("'") and tokens[counter - 1] not in ('&', '|', '!', '('):
            tokens.insert(counter, '&')
            counter += 1
            counterlength += 1
        elif (
                tokens[counter] in ('&', '|') and tokens[counter - 1] in ('&', '|')) or (
                tokens[counter] == '!' and tokens[counter - 1] not in ('&', '|')) or (
                tokens[counter] == ':*' and not tokens[counter - 1].startswith("'")):
            # Invalid token: is a dupe or follows a token it shouldn't follow
            tokens.pop(counter)
            counter -= 1
            counterlength -= 1
        counter += 1
    while tokens and tokens[0] in ('&', '|', ':*', ')', '!', '*'):
        tokens.pop(0)  # Can't start with a binary or suffix operator
    if tokens:
        while tokens[-1] in ('&', '|', '!', '('):
            tokens.pop(-1)  # Can't end with a binary or prefix operator
    if not tokens:
        return ''  # Did we just eliminate all tokens?
    missing_brackets = sum([1 if t == '(' else -1 for t in tokens if t in ('(', ')')])
    if missing_brackets > 0:
        tokens.append(')' * missing_brackets)
    elif missing_brackets < 0:
        tokens.insert(0, '(' * -missing_brackets)
    return ''.join(tokens)


VALID_TAGS = {
    'a': ['href', 'title', 'target', 'rel'],
    'abbr': ['title'],
    'b': [],
    'br': [],
    'blockquote': [],
    'cite': [],
    'code': [],
    'dd': [],
    'del': [],
    'dl': [],
    'dt': [],
    'em': [],
    'h3': [],
    'h4': [],
    'h5': [],
    'h6': [],
    'hr': [],
    'i': [],
    'img': ['src', 'width', 'height', 'align', 'alt'],
    'ins': [],
    'li': ['start'],
    'mark': [],
    'p': [],
    'pre': [],
    'ol': [],
    'strong': [],
    'sup': [],
    'sub': [],
    'ul': [],
    }


def sanitize_html(value, valid_tags=VALID_TAGS, strip=True):
    """
    Strips unwanted markup out of HTML.
    """
    return bleach.clean(value, tags=VALID_TAGS.keys(), attributes=VALID_TAGS, strip=strip)


blockish_tags = set([
    'address', 'article', 'aside', 'audio', 'blockquote', 'canvas', 'dd', 'div', 'dl', 'dt', 'fieldset', 'figcaption',
    'figure', 'footer', 'form', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'header', 'hgroup', 'hr', 'li', 'noscript', 'ol',
    'output', 'p', 'pre', 'section', 'table', 'td', 'tfoot', 'th', 'tr', 'ul', 'video'])


def text_blocks(html_text, skip_pre=True):
    # doc = html.fromstring(html_text)
    doc = html5lib.parseFragment(html_text)
    text_blocks = []

    def subloop(parent_tag, element, lastchild=False):
        if callable(element.tag):  # Comments have a callable tag. TODO: Find out, anything else?
            tag = '<!-->'
            text = ''
            tail = element.tail or u''
        else:
            tag = element.tag.split('}')[-1]  # Extract tag from namespace: {http://www.w3.org/1999/xhtml}html
            text = element.text or u''
            tail = element.tail or u''

        if tag == 'pre' and skip_pre:
            text = u''

        if tag in blockish_tags or tag == 'DOCUMENT_FRAGMENT':
            text = text.lstrip()  # Leading whitespace is insignificant in a block tag
            if not len(element):
                text = text.rstrip()  # No children? Then trailing whitespace is insignificant
            # If there's text, add it.
            # If there's no text but the next element is not a block tag, add a blank anyway
            # (unless it's a pre tag and we want to skip_pre, in which case ignore it again).
            if text:
                text_blocks.append(text)
            elif (len(element) and isinstance(element[0].tag, basestring) and
                    element[0].tag.split('}')[-1] not in blockish_tags and not (skip_pre and tag == 'pre')):
                text_blocks.append('')
        else:
            if not text_blocks:
                if text:
                    text_blocks.append(text)
            else:
                text_blocks[-1] += text

        if len(element) > 0 and not (skip_pre and tag == 'pre'):
            for child in element[:-1]:
                subloop(tag, child)
            subloop(tag, element[-1], lastchild=True)

        if tag in blockish_tags:
            tail = tail.lstrip()  # Leading whitespace is insignificant after a block tag
            if tail:
                text_blocks.append(tail)
        else:
            if parent_tag in blockish_tags and lastchild:
                tail = tail.rstrip()  # Trailing whitespace is insignificant before a block tag end
            if not text_blocks:
                if tail:
                    text_blocks.append(tail)
            else:
                if tag == 'br' and tail:
                    text_blocks[-1] += '\n' + tail
                else:
                    text_blocks[-1] += tail

    subloop(None, doc)
    # Replace &nbsp; with ' '
    text_blocks = [t.replace(u'\xa0', ' ') for t in text_blocks]
    return text_blocks


def word_count(text, html=True):
    """
    Return the count of words in the given text. If the text is HTML (default True),
    tags are stripped before counting. Handles punctuation and bad formatting like.this
    when counting words, but assumes conventions for Latin script languages. May not
    be reliable for other languages.
    """
    if html:
        text = _tag_re.sub(' ', text)
    text = _strip_re.sub('', text)
    text = _punctuation_re.sub(' ', text)
    return len(text.split())


# Based on http://jasonpriem.org/obfuscation-decoder/
_deobfuscate_dot1_re = re.compile(r'\W+\.\W+|\W+dot\W+|\W+d0t\W+', re.U | re.I)
_deobfuscate_dot2_re = re.compile(r'([a-z0-9])DOT([a-z0-9])')
_deobfuscate_dot3_re = re.compile(r'([A-Z0-9])dot([A-Z0-9])')
_deobfuscate_at1_re = re.compile(r'\W*@\W*|\W+at\W+', re.U | re.I)
_deobfuscate_at2_re = re.compile(r'([a-z0-9])AT([a-z0-9])')
_deobfuscate_at3_re = re.compile(r'([A-Z0-9])at([A-Z0-9])')


def deobfuscate_email(text):
    """
    Deobfuscate email addresses in provided text
    """
    text = unescape(text)
    # Find the "dot"
    text = _deobfuscate_dot1_re.sub('.', text)
    text = _deobfuscate_dot2_re.sub(r'\1.\2', text)
    text = _deobfuscate_dot3_re.sub(r'\1.\2', text)
    # Find the "at"
    text = _deobfuscate_at1_re.sub('@', text)
    text = _deobfuscate_at2_re.sub(r'\1@\2', text)
    text = _deobfuscate_at3_re.sub(r'\1@\2', text)

    return text


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
            pytz.timezone(name).tzname(now, is_dst=False)),
        name) for delta, name in timezones]
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
    return '.'.join(namespace)


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


NameTitle = namedtuple('NameTitle', ['name', 'title'])


class _LabeledEnumMeta(type):
    """Construct labeled enumeration"""
    def __new__(cls, name, bases, attrs):
        labels = {}
        for key, value in tuple(attrs.items()):
            if key != '__order__' and isinstance(value, tuple):
                if len(value) == 2:
                    labels[value[0]] = value[1]
                    attrs[key] = value[0]
                elif len(value) == 3:
                    labels[value[0]] = NameTitle(value[1], value[2])
                    attrs[key] = value[0]

        if '__order__' in attrs:
            sorted_labels = OrderedDict()
            for value in attrs['__order__']:
                sorted_labels[value[0]] = labels.pop(value[0])
            for key, value in sorted(labels.items()):  # Left over items after processing the list in __order__
                sorted_labels[key] = value
        else:
            sorted_labels = OrderedDict(sorted(labels.items()))
        attrs['__labels__'] = sorted_labels
        return type.__new__(cls, name, bases, attrs)

    def __getitem__(cls, key):
        return cls.__labels__[key]

    def __setitem__(cls, key, value):
        raise TypeError("LabeledEnum is immutable")


class LabeledEnum(six.with_metaclass(_LabeledEnumMeta)):
    """
    Labeled enumerations. Declarate an enumeration with values and labels
    (for use in UI)::

        >>> class MY_ENUM(LabeledEnum):
        ...     FIRST = (1, "First")
        ...     THIRD = (3, "Third")
        ...     SECOND = (2, "Second")

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
        >>> MY_ENUM.get(3)
        'Third'
        >>> MY_ENUM.get(4) is None
        True

    Retrieve a full list of values and labels with ``.items()``. Items are
    sorted by value regardless of the original definition order since Python
    doesn't provide a way to preserve that order::

        >>> MY_ENUM.items()
        [(1, 'First'), (2, 'Second'), (3, 'Third')]
        >>> MY_ENUM.keys()
        [1, 2, 3]
        >>> MY_ENUM.values()
        ['First', 'Second', 'Third']

    However, if you really want manual sorting, add an __order__ list. Anything not in it will
    be sorted by value as usual::

        >>> class RSVP(LabeledEnum):
        ...     RSVP_Y = ('Y', "Yes")
        ...     RSVP_N = ('N', "No")
        ...     RSVP_M = ('M', "Maybe")
        ...     RSVP_B = ('U', "Unknown")
        ...     RSVP_A = ('A', "Awaiting")
        ...     __order__ = (RSVP_Y, RSVP_N, RSVP_M)

        >>> RSVP.items()
        [('Y', 'Yes'), ('N', 'No'), ('M', 'Maybe'), ('A', 'Awaiting'), ('U', 'Unknown')]

    Three value tuples are assumed to be (value, name, title) and the name and
    title are converted into NameTitle(name, title)::

        >>> class NAME_ENUM(LabeledEnum):
        ...     FIRST = (1, 'first', "First")
        ...     THIRD = (3, 'third', "Third")
        ...     SECOND = (2, 'second', "Second")

        >>> NAME_ENUM.FIRST
        1
        >>> NAME_ENUM[NAME_ENUM.FIRST]
        NameTitle(name='first', title='First')
        >>> NAME_ENUM[NAME_ENUM.SECOND].name
        'second'
        >>> NAME_ENUM[NAME_ENUM.THIRD].title
        'Third'

    Given a name, the value can be looked up::

        >>> NAME_ENUM.value_for('first')
        1
        >>> NAME_ENUM.value_for('second')
        2
    """

    @classmethod
    def get(cls, key, default=None):
        return cls.__labels__.get(key, default)

    @classmethod
    def keys(cls):
        return cls.__labels__.keys()

    @classmethod
    def values(cls):
        return cls.__labels__.values()

    @classmethod
    def items(cls):
        return cls.__labels__.items()

    @classmethod
    def value_for(cls, name):
        for key, value in cls.__labels__.items():
            if isinstance(value, NameTitle) and value.name == name:
                return key
