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

from copy import deepcopy
from typing import Any, Dict, List, Mapping, Optional, Union, cast

from bleach import linkify as linkify_processor
from markdown import Markdown
from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor
from markupsafe import Markup
from pymdownx.emoji import to_alt as emoji_to_alt

from .text import (
    LINKIFY_CALLBACKS,
    LINKIFY_SKIP_TAGS,
    VALID_TAGS,
    normalize_spaces_multiline,
    sanitize_html,
)

__all__ = [
    'markdown',
    'MARKDOWN_HTML_TAGS',
    'default_markdown_extensions_html',
    'default_markdown_extensions',
    'default_markdown_extension_configs',
]


# --- Constants ------------------------------------------------------------------------

MARKDOWN_HTML_TAGS = deepcopy(VALID_TAGS)
cast(Dict, MARKDOWN_HTML_TAGS).update(
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

# --- Extensions -----------------------------------------------------------------------


class EscapeHtml(Extension):
    """
    Extension to escape HTML tags to use with Markdown().

    This replaces `safe_mode='escape`
    Ref: https://python-markdown.github.io/change_log/release-3.0/
    #safe_mode-and-html_replacement_text-keywords-deprecated
    """

    def extendMarkdown(self, md) -> None:  # NOQA: N802
        md.preprocessors.deregister('html_block')
        md.inlinePatterns.deregister('html')


class JavascriptProtocolProcessor(Treeprocessor):
    """Processor to remove `javascript:` links."""

    def run(self, root):
        for anchor in root.iter('a'):
            href = anchor.attrib.get('href')
            if href and href.lower().startswith('javascript:'):
                del anchor.attrib['href']


class JavascriptProtocolExtension(Extension):
    """Markdown extension for :class:`JavascriptProtocolProcessor`."""

    def extendMarkdown(self, md) -> None:  # NOQA: N802
        # Register with low priority so we run last
        md.treeprocessors.register(
            JavascriptProtocolProcessor(md), 'javascript_protocol', 1
        )
        md.registerExtension(self)


# --- Standard extensions --------------------------------------------------------------

# FIXME: Disable support for custom css classes as described here:
# https://facelessuser.github.io/pymdown-extensions/extensions/superfences/

default_markdown_extensions_html: List[Union[str, Extension]] = [
    'markdown.extensions.abbr',
    'markdown.extensions.footnotes',
    'markdown.extensions.tables',
    'markdown.extensions.nl2br',
    'markdown.extensions.sane_lists',
    'markdown.extensions.smarty',
    'pymdownx.superfences',
    'pymdownx.betterem',
    'pymdownx.caret',  # Support ^^<ins>^^
    'pymdownx.tilde',  # Support ~~<del>~~
    'pymdownx.emoji',  # Support :emoji:
    'pymdownx.mark',  # Support ==<mark>==
    'pymdownx.saneheaders',  # Disable `#header`, only allow `# header`
    'pymdownx.smartsymbols',
    JavascriptProtocolExtension(),
]

default_markdown_extensions = default_markdown_extensions_html + [
    'markdown.extensions.codehilite',
    'pymdownx.tasklist',
    EscapeHtml(),
]


default_markdown_extension_configs: Mapping[str, Mapping[str, Any]] = {
    'markdown.extensions.codehilite': {'css_class': 'highlight', 'guess_lang': False},
    'pymdownx.superfences': {
        'css_class': 'highlight',
        'disable_indented_code_blocks': True,
    },
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
    'pymdownx.mark': {'smart_mark': True},
}


# --- Markdown processor ---------------------------------------------------------------


def markdown(
    text: str,
    html: bool = False,
    linkify: bool = True,
    valid_tags: Optional[Union[List[str], Mapping[str, List]]] = None,
    extensions: Optional[List[Union[str, Extension]]] = None,
    extension_configs: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Markup:
    """
    Markdown parser with a number of sane defaults that resemble GFM.

    :param bool html: Allow known-safe HTML tags in text
        (this disables code syntax highlighting and task lists)
    :param bool linkify: Whether to convert naked URLs into links
    :param dict valid_tags: Valid tags and attributes if HTML is allowed
    :param list extensions: List of Markdown extensions to be enabled
    :param dict extension_configs: Config for Markdown extensions
    """
    if text is None:
        return Markup('')  # type:ignore[unreachable]
    if valid_tags is None:
        valid_tags = MARKDOWN_HTML_TAGS
    if extensions is None:
        if html:
            extensions = default_markdown_extensions_html
        else:
            extensions = default_markdown_extensions
    if extension_configs is None:
        extension_configs = default_markdown_extension_configs

    # Replace invisible characters with spaces
    text = normalize_spaces_multiline(text)

    if html:
        return Markup(
            sanitize_html(
                Markdown(
                    output_format='html',
                    extensions=extensions,
                    extension_configs=extension_configs,
                ).convert(text),
                valid_tags=valid_tags,
                linkify=linkify,
            )
        )
    else:
        output = Markdown(
            output_format='html',
            extensions=extensions,
            extension_configs=extension_configs,
        ).convert(text)
        if linkify:
            output = linkify_processor(
                output, callbacks=LINKIFY_CALLBACKS, skip_tags=LINKIFY_SKIP_TAGS
            )
        return Markup(output)
