# -*- coding: utf-8 -*-

"""
Text processing utilities
-------------------------
"""

from __future__ import absolute_import
from functools import partial
import string
import re
import six
import html5lib
from markupsafe import Markup
from bleach.sanitizer import Cleaner
from bleach.linkifier import LinkifyFilter, DEFAULT_CALLBACKS

if six.PY3:  # pragma: no cover
    from html import unescape
else:  # pragma: no cover
    import HTMLParser
    unescape = HTMLParser.HTMLParser().unescape
    del HTMLParser

from .misc import _strip_re, _punctuation_re, _tag_re


__all__ = ['VALID_TAGS', 'unicode_extended_whitespace', 'sanitize_html', 'text_blocks', 'word_count',
    'ulstrip', 'urstrip', 'ustrip', 'deobfuscate_email', 'simplify_text']


#: Unicode's list of whitespace characters is missing some that were previously classified as
#: whitespace but are now considered format characters. These are invisible and usually arrive
#: via copy-paste, so we include them here as characters to be stripped from the ends of text.
unicode_extended_whitespace = (
    u'\t\n\x0b\x0c\r\x1c\x1d\x1e\x1f '  # ASCII whitespace
    u'\x85'    # NEXT LINE (NEL)
    u'\xa0'    # NO-BREAK SPACE
    u'\u1680'  # OGHAM SPACE MARK
    u'\u180e'  # MONGOLIAN VOWEL SEPARATOR
    u'\u2000'  # EN QUAD
    u'\u2001'  # EM QUAD
    u'\u2002'  # EN SPACE
    u'\u2003'  # EM SPACE
    u'\u2004'  # THREE-PER-EM SPACE
    u'\u2005'  # FOUR-PER-EM SPACE
    u'\u2006'  # SIX-PER-EM SPACE
    u'\u2007'  # FIGURE SPACE
    u'\u2008'  # PUNCTUATION SPACE
    u'\u2009'  # THIN SPACE
    u'\u200a'  # HAIR SPACE
    u'\u200b'  # ZERO WIDTH SPACE (format)
    u'\u200c'  # ZERO WIDTH NON-JOINER (format)
    u'\u200d'  # ZERO WIDTH JOINER (format)
    u'\u2028'  # LINE SEPARATOR
    u'\u2029'  # PARAGRAPH SEPARATOR
    u'\u202f'  # NARROW NO-BREAK SPACE (NNBSP)
    u'\u205f'  # MEDIUM MATHEMATICAL SPACE (MMSP)
    u'\u2060'  # WORD JOINER (format)
    u'\u3000'  # IDEOGRAPHIC SPACE
    u'\ufeff'  # ZERO WIDTH NO-BREAK SPACE (format)
    )

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
    'li': [],
    'mark': [],
    'p': [],
    'pre': [],
    'ol': ['start'],
    'strong': [],
    'sup': [],
    'sub': [],
    'ul': [],
    }


def sanitize_html(value, valid_tags=VALID_TAGS, strip=True, linkify=False):
    """
    Strips unwanted markup out of HTML.
    """
    if linkify:
        filters = [partial(LinkifyFilter, skip_tags=['pre'], callbacks=DEFAULT_CALLBACKS)]
    else:
        filters = []
    cleaner = Cleaner(tags=list(valid_tags.keys()), attributes=valid_tags, filters=filters, strip=strip)
    return Markup(cleaner.clean(value))


blockish_tags = {
    'address', 'article', 'aside', 'audio', 'blockquote', 'canvas', 'dd', 'div', 'dl', 'dt', 'fieldset', 'figcaption',
    'figure', 'footer', 'form', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'header', 'hgroup', 'hr', 'li', 'noscript', 'ol',
    'output', 'p', 'pre', 'section', 'table', 'td', 'tfoot', 'th', 'tr', 'ul', 'video'}


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
            elif (len(element) and isinstance(element[0].tag, six.string_types)
                    and element[0].tag.split('}')[-1] not in blockish_tags and not (skip_pre and tag == 'pre')):
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


def ulstrip(text):
    """
    Strip Unicode extended whitespace from the left side of a string
    """
    return text.lstrip(unicode_extended_whitespace)


def urstrip(text):
    """
    Strip Unicode extended whitespace from the right side of a string
    """
    return text.rstrip(unicode_extended_whitespace)


def ustrip(text):
    """
    Strip Unicode extended whitespace from a string
    """
    return text.strip(unicode_extended_whitespace)


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
    >>> simplify_text(u"Awesome Coder, wanted  at Awesome Company! ") == 'awesome coder wanted at awesome company'
    True
    """
    if isinstance(text, six.text_type):
        if six.PY3:  # pragma: no cover
            text = text.translate(text.maketrans("", "", string.punctuation)).lower()
        else:  # pragma: no cover
            text = six.text_type(text.encode('utf-8').translate(string.maketrans("", ""), string.punctuation).lower(), 'utf-8')
    else:
        text = text.translate(string.maketrans("", ""), string.punctuation).lower()
    return " ".join(text.split())
