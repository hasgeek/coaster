"""
Text processing utilities
-------------------------
"""

from __future__ import annotations

from functools import partial
from html import unescape
import re
import string
import typing as t

from bleach.linkifier import DEFAULT_CALLBACKS, LinkifyFilter
from bleach.sanitizer import Cleaner
from markupsafe import Markup
import html5lib

__all__ = [
    'VALID_TAGS',
    'LINKIFY_SKIP_TAGS',
    'LINKIFY_CALLBACKS',
    'compress_whitespace',
    'deobfuscate_email',
    'normalize_spaces',
    'normalize_spaces_multiline',
    'sanitize_html',
    'simplify_text',
    'text_blocks',
    'ulstrip',
    'unicode_extended_whitespace',
    'urstrip',
    'ustrip',
]


#: Unicode's list of whitespace characters is missing some that were previously
#: classified as whitespace but are now considered format characters. These are
#: invisible and usually arrive via copy-paste, so we include them here as characters to
#: be replaced with spaces and stripped from the ends of text.
unicode_format_whitespace = (
    '\x85'  # NEXT LINE (NEL)
    '\xa0'  # NO-BREAK SPACE (NBSP)
    '\u1680'  # OGHAM SPACE MARK
    '\u180e'  # MONGOLIAN VOWEL SEPARATOR
    '\u2000'  # EN QUAD
    '\u2001'  # EM QUAD
    '\u2002'  # EN SPACE
    '\u2003'  # EM SPACE
    '\u2004'  # THREE-PER-EM SPACE
    '\u2005'  # FOUR-PER-EM SPACE
    '\u2006'  # SIX-PER-EM SPACE
    '\u2007'  # FIGURE SPACE
    '\u2008'  # PUNCTUATION SPACE
    '\u2009'  # THIN SPACE
    '\u200a'  # HAIR SPACE
    '\u200b'  # ZERO WIDTH SPACE (format)
    '\u200c'  # ZERO WIDTH NON-JOINER (format)
    '\u200d'  # ZERO WIDTH JOINER (format)
    '\u2028'  # LINE SEPARATOR
    '\u2029'  # PARAGRAPH SEPARATOR
    '\u202f'  # NARROW NO-BREAK SPACE (NNBSP)
    '\u205f'  # MEDIUM MATHEMATICAL SPACE (MMSP)
    '\u2060'  # WORD JOINER (format)
    '\u3000'  # IDEOGRAPHIC SPACE
    '\ufeff'  # ZERO WIDTH NO-BREAK SPACE (format)
)

unicode_extended_whitespace = (
    '\t\n\x0b\x0c\r\x1c\x1d\x1e\x1f '  # ASCII whitespace
) + unicode_format_whitespace

re_singleline_spaces = re.compile(
    '[' + unicode_extended_whitespace + ']', re.UNICODE | re.MULTILINE
)
re_multiline_spaces = re.compile(
    '[' + unicode_format_whitespace + ']', re.UNICODE | re.MULTILINE
)
re_compress_spaces = re.compile(
    r'[\s' + unicode_format_whitespace + ']+', re.UNICODE | re.MULTILINE
)

VALID_TAGS: t.Mapping[str, t.List[str]] = {
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

LINKIFY_SKIP_TAGS: t.List = ['pre', 'code', 'kbd', 'samp', 'var']


# Adapted from https://bleach.readthedocs.io/en/latest/linkify.html#preventing-links
def dont_linkify_filenames(attrs, new=False):
    # This is an existing link, so leave it be
    if not new:
        return attrs
    # If the TLD is '.py', make sure it starts with http: or https:.
    # Use _text because that's the original text
    link_text = attrs['_text']
    if link_text.endswith('.py') and not link_text.startswith(('http:', 'https:')):
        # This looks like a Python file, not a URL. Don't make a link.
        return None
    # Everything checks out, keep going to the next callback.
    return attrs


LINKIFY_CALLBACKS = list(DEFAULT_CALLBACKS) + [dont_linkify_filenames]


def sanitize_html(value, valid_tags=None, strip=True, linkify=False):
    """Strip unwanted markup out of HTML."""
    if valid_tags is None:
        valid_tags = VALID_TAGS
    if linkify:
        filters = [
            partial(
                LinkifyFilter, callbacks=LINKIFY_CALLBACKS, skip_tags=LINKIFY_SKIP_TAGS
            )
        ]
    else:
        filters = []
    cleaner = Cleaner(
        tags=list(valid_tags.keys()),
        attributes=valid_tags,
        filters=filters,
        strip=strip,
    )
    return Markup(cleaner.clean(value))


blockish_tags: t.Set[str] = {
    'address',
    'article',
    'aside',
    'audio',
    'blockquote',
    'canvas',
    'dd',
    'div',
    'dl',
    'dt',
    'fieldset',
    'figcaption',
    'figure',
    'footer',
    'form',
    'h1',
    'h2',
    'h3',
    'h4',
    'h5',
    'h6',
    'header',
    'hgroup',
    'hr',
    'li',
    'noscript',
    'ol',
    'output',
    'p',
    'pre',
    'section',
    'table',
    'td',
    'tfoot',
    'th',
    'tr',
    'ul',
    'video',
}


def text_blocks(html_text, skip_pre=True):
    """Extract a list of paragraphs from a given HTML string."""
    doc = html5lib.parseFragment(html_text)
    blocks = []

    def subloop(parent_tag, element, lastchild=False):
        if callable(
            element.tag
        ):  # Comments have a callable tag. TODO: Find out, anything else?
            tag = '<!-->'
            text = ''
            tail = element.tail or ''
        else:
            tag = element.tag.split('}')[
                -1
            ]  # Extract tag from namespace: {http://www.w3.org/1999/xhtml}html
            text = element.text or ''
            tail = element.tail or ''

        if tag == 'pre' and skip_pre:
            text = ''

        if tag in blockish_tags or tag == 'DOCUMENT_FRAGMENT':
            text = text.lstrip()  # Leading whitespace is insignificant in a block tag
            if not len(element):
                text = (
                    text.rstrip()
                )  # No children? Then trailing whitespace is insignificant
            # If there's text, add it.
            # If there's no text but the next element is not a block tag, add a blank
            # anyway (unless it's a pre tag and we want to skip_pre, in which case
            # ignore it again).
            if text:
                blocks.append(text)
            elif (
                len(element)
                and isinstance(element[0].tag, str)
                and element[0].tag.split('}')[-1] not in blockish_tags
                and not (skip_pre and tag == 'pre')
            ):
                blocks.append('')
        else:
            if not blocks:
                if text:
                    blocks.append(text)
            else:
                blocks[-1] += text

        if len(element) > 0 and not (skip_pre and tag == 'pre'):
            for child in element[:-1]:
                subloop(tag, child)
            subloop(tag, element[-1], lastchild=True)

        if tag in blockish_tags:
            tail = (
                tail.lstrip()
            )  # Leading whitespace is insignificant after a block tag
            if tail:
                blocks.append(tail)
        else:
            if parent_tag in blockish_tags and lastchild:
                tail = (
                    tail.rstrip()
                )  # Trailing whitespace is insignificant before a block tag end
            if not blocks:
                if tail:
                    blocks.append(tail)
            else:
                if tag == 'br' and tail:
                    blocks[-1] += '\n' + tail
                else:
                    blocks[-1] += tail

    subloop(None, doc)
    # Replace &nbsp; with ' '
    blocks = [t.replace('\xa0', ' ') for t in blocks]
    return blocks


def normalize_spaces(text):
    """Replace whitespace characters with regular spaces."""
    return re_singleline_spaces.sub(' ', text)


def normalize_spaces_multiline(text):
    """
    Replace whitespace characters with regular spaces, in multiline text.

    Line break characters like newlines are not considered whitespace.
    """
    return re_multiline_spaces.sub(' ', text)


def ulstrip(text):
    """Strip Unicode extended whitespace from the left side of a string."""
    return text.lstrip(unicode_extended_whitespace)


def urstrip(text):
    """Strip Unicode extended whitespace from the right side of a string."""
    return text.rstrip(unicode_extended_whitespace)


def ustrip(text):
    """Strip Unicode extended whitespace from a string."""
    return text.strip(unicode_extended_whitespace)


def compress_whitespace(text):
    """Reduce all space-like characters into single spaces and strip from ends."""
    return ustrip(re_compress_spaces.sub(' ', text))


# Based on http://jasonpriem.org/obfuscation-decoder/
_deobfuscate_dot1_re = re.compile(r'\W+\.\W+|\W+dot\W+|\W+d0t\W+', re.U | re.I)
_deobfuscate_dot2_re = re.compile(r'([a-z0-9])DOT([a-z0-9])')
_deobfuscate_dot3_re = re.compile(r'([A-Z0-9])dot([A-Z0-9])')
_deobfuscate_at1_re = re.compile(r'\W*@\W*|\W+at\W+', re.U | re.I)
_deobfuscate_at2_re = re.compile(r'([a-z0-9])AT([a-z0-9])')
_deobfuscate_at3_re = re.compile(r'([A-Z0-9])at([A-Z0-9])')


def deobfuscate_email(text):
    """Deobfuscate email addresses in provided text."""
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
    >>> simplify_text("Awesome Coder, wanted  at Awesome Company! ") == (
    ...   'awesome coder wanted at awesome company')
    True
    """
    text = text.translate(text.maketrans('', '', string.punctuation)).lower()
    return ' '.join(text.split())
