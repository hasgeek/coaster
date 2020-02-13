# -*- coding: utf-8 -*-

"""
Markdown processor
==================

Markdown parser with a number of sane defaults that resembles
GitHub-Flavoured Markdown (GFM).

GFM exists because normal markdown has some vicious gotchas. Further reading:
http://blog.stackoverflow.com/2009/10/markdown-one-year-later/

This Markdown processor is used by :func:`~coaster.sqlalchemy.columns.MarkdownColumn`
to auto-render HTML from Markdown text.
"""

from __future__ import absolute_import

from bleach import linkify
from markdown import Markdown
from markdown.extensions import Extension
from markupsafe import Markup
from pymdownx.emoji import to_alt as emoji_to_alt

from .text import VALID_TAGS, sanitize_html

__all__ = ['markdown', 'MARKDOWN_HTML_TAGS']


MARKDOWN_HTML_TAGS = dict(VALID_TAGS)
MARKDOWN_HTML_TAGS.update(
    {
        # For tables:
        'table': ['align', 'bgcolor', 'border', 'cellpadding', 'cellspacing', 'width'],
        'caption': [],
        'col': ['align', 'char', 'charoff'],
        'colgroup': ['align', 'span', 'cols', 'char', 'charoff', 'width'],
        'tbody': ['align', 'char', 'charoff', 'valign'],
        'td': ['align', 'char', 'charoff', 'colspan', 'rowspan', 'valign'],
        'tfoot': ['align', 'char', 'charoff', 'valign'],
        'th': ['align', 'char', 'charoff', 'colspan', 'rowspan', 'valign'],
        'thead': ['align', 'char', 'charoff', 'valign'],
        'tr': ['align', 'char', 'charoff', 'valign'],
    }
)


class EscapeHtml(Extension):
    """
    Extension to escape HTML tags to use with Markdown()
    This replaces `safe_mode='escape`
    Ref: https://python-markdown.github.io/change_log/release-3.0/
    #safe_mode-and-html_replacement_text-keywords-deprecated
    """

    def extendMarkdown(self, md):  # NOQA: N802
        md.preprocessors.deregister('html_block')
        md.inlinePatterns.deregister('html')


extensions = [
    'markdown.extensions.abbr',
    'markdown.extensions.footnotes',
    'markdown.extensions.tables',
    'markdown.extensions.nl2br',
    'markdown.extensions.sane_lists',
    'markdown.extensions.smarty',
    'pymdownx.superfences',
    'pymdownx.betterem',
    'pymdownx.caret',
    'pymdownx.tilde',
    'pymdownx.emoji',
    'pymdownx.mark',
    'pymdownx.smartsymbols',
]

extensions_text = extensions + [
    'markdown.extensions.codehilite',
    'pymdownx.tasklist',
    EscapeHtml(),
]

extensions_html = extensions

extension_configs = {
    'pymdownx.smartsymbols': {
        'trademark': False,
        'copyright': False,
        'registered': False,
        'care_of': False,
        'plusminus': True,
        'arrows': True,
        'notequal': True,
        'fractions': True,
        'ordinal_numbers': True,
    },
    'pymdownx.emoji': {'emoji_generator': emoji_to_alt},
}


def markdown(text, html=False, valid_tags=None):
    """
    Markdown parser with a number of sane defaults that resembles
    GitHub-Flavoured Markdown.

    :param bool html: Allow known-safe HTML tags in text
        (this disables code syntax highlighting)
    """
    if text is None:
        return None
    if valid_tags is None:
        valid_tags = MARKDOWN_HTML_TAGS
    if html:
        return Markup(
            sanitize_html(
                Markdown(
                    output_format='html',
                    extensions=extensions_html,
                    extension_configs=extension_configs,
                ).convert(text),
                valid_tags=valid_tags,
                linkify=True,
            )
        )
    else:
        return Markup(
            linkify(
                Markdown(
                    output_format='html',
                    extensions=extensions_text,
                    extension_configs=extension_configs,
                ).convert(text),
                skip_tags=['pre'],
            )
        )
