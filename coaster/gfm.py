# -*- coding: utf-8 -*-

"""
GitHub Flavoured Markdown
=========================

While not strictly a Flask-dependent module, Coaster offers an implementation
of GitHub-flavoured Markdown (GFM) as a convenience feature.

GFM exists because normal markdown has some vicious gotchas. Further reading:
http://blog.stackoverflow.com/2009/10/markdown-one-year-later/

This is a Python port of GitHub code, taken from
https://gist.github.com/Wilfred/901706
"""

from markupsafe import Markup
from markdown import Markdown
from markdown.extensions import Extension
import re
from .utils import sanitize_html, VALID_TAGS

__all__ = ['gfm', 'markdown']

GFM_TAGS = dict(VALID_TAGS)
# For syntax highlighting:
GFM_TAGS['pre'] = ['class']
GFM_TAGS['span'] = ['class']
# For tables:
GFM_TAGS['table'] = ['class', 'align', 'bgcolor', 'border', 'cellpadding', 'cellspacing', 'width']
GFM_TAGS['caption'] = []
GFM_TAGS['col'] = ['align', 'char', 'charoff']
GFM_TAGS['colgroup'] = ['align', 'span', 'cols', 'char', 'charoff', 'width']
GFM_TAGS['tbody'] = ['align', 'char', 'charoff', 'valign']
GFM_TAGS['td'] = ['align', 'char', 'charoff', 'colspan', 'rowspan', 'valign']
GFM_TAGS['tfoot'] = ['align', 'char', 'charoff', 'valign']
GFM_TAGS['th'] = ['align', 'char', 'charoff', 'colspan', 'rowspan', 'valign']
GFM_TAGS['thead'] = ['align', 'char', 'charoff', 'valign']
GFM_TAGS['tr'] = ['align', 'char', 'charoff', 'valign']


class EscapeHtml(Extension):
    """
    Extension to escape HTML tags to use with Markdown()
    This replaces `safe_mode='escape`
    Ref: https://python-markdown.github.io/change_log/release-3.0/#safe_mode-and-html_replacement_text-keywords-deprecated
    """
    def extendMarkdown(self, md):
        md.preprocessors.deregister('html_block')
        md.inlinePatterns.deregister('html')


markdown_convert_text = Markdown(output_format='html',
    extensions=['markdown.extensions.codehilite', 'markdown.extensions.smarty', EscapeHtml()],
    extension_configs={'codehilite': {'css_class': 'syntax'}}
    ).convert


markdown_convert_html = Markdown(output_format='html',
    extensions=['markdown.extensions.codehilite', 'markdown.extensions.smarty'],
    extension_configs={'codehilite': {'css_class': 'syntax'}}
    ).convert


def remove_pre_blocks(markdown_source):
    # replace <pre> blocks with placeholders, so we don't accidentally
    # muck up stuff inside the block with our other transformations
    original_blocks = []

    pattern = re.compile(r'<pre>.*?</pre>', re.MULTILINE | re.DOTALL)

    while re.search(pattern, markdown_source):
        # save the original block
        original_block = re.search(pattern, markdown_source).group(0)
        original_blocks.append(original_block)

        # put in a placeholder
        markdown_source = re.sub(pattern, '{placeholder}', markdown_source,
                                 count=1)

    return (markdown_source, original_blocks)


def remove_inline_code_blocks(markdown_source):
    original_blocks = []

    pattern = re.compile(r'`.*?`', re.DOTALL)

    while re.search(pattern, markdown_source):
        # save the original block
        original_block = re.search(pattern, markdown_source).group(0)
        original_blocks.append(original_block)

        # put in a placeholder
        markdown_source = re.sub(pattern, '{placeholder}', markdown_source,
                                 count=1)

    return (markdown_source, original_blocks)


CODEPATTERN_RE = re.compile('^```(.*?)\n(.*?)^```$', re.MULTILINE | re.UNICODE | re.DOTALL)
ITALICSPATTERN_RE = re.compile(r'^(?! {4}|\t).*\w+(?<!_)_\w+_\w[\w_]*', re.MULTILINE | re.UNICODE)
NAKEDURL_RE = re.compile(r"""
(^|\s) # start of string or has whitespace before it
(https?://[:/.?=&;a-zA-Z0-9_-]+) # the URL itself, http or https only
(\s|$) # trailing whitespace or end of string
""", re.VERBOSE | re.MULTILINE | re.UNICODE)
NEWLINE_RE = re.compile(r'^[\w\<][^\n]*(\n+)', re.MULTILINE | re.UNICODE)


def gfm(text):
    """
    Prepare text for rendering by a regular Markdown processor.
    """
    def indent_code(matchobj):
        syntax = matchobj.group(1)
        code = matchobj.group(2)
        if syntax:
            result = '    :::' + syntax + '\n'
        else:
            result = ''
        # The last line will be blank since it had the closing "```". Discard it
        # when indenting the lines.
        return result + '\n'.join(['    ' + line for line in code.split('\n')[:-1]])

    use_crlf = text.find('\r') != -1
    if use_crlf:
        text = text.replace('\r\n', '\n')

    # Render GitHub-style ```code blocks``` into Markdown-style 4-space indented blocks
    text = CODEPATTERN_RE.sub(indent_code, text)

    text, code_blocks = remove_pre_blocks(text)
    text, inline_blocks = remove_inline_code_blocks(text)

    # Prevent foo_bar_baz from ending up with an italic word in the middle.
    def italic_callback(matchobj):
        s = matchobj.group(0)
        # don't mess with URLs:
        if 'http:' in s or 'https:' in s:
            return s

        return s.replace('_', r'\_')

    # fix italics for code blocks
    text = ITALICSPATTERN_RE.sub(italic_callback, text)

    # linkify naked URLs
    # wrap the URL in brackets: http://foo -> [http://foo](http://foo)
    text = NAKEDURL_RE.sub(r'\1[\2](\2)\3', text)

    # In very clear cases, let newlines become <br /> tags.
    def newline_callback(matchobj):
        if len(matchobj.group(1)) == 1:
            return matchobj.group(0).rstrip() + '  \n'
        else:
            return matchobj.group(0)

    text = NEWLINE_RE.sub(newline_callback, text)

    # now restore removed code blocks
    removed_blocks = code_blocks + inline_blocks
    for removed_block in removed_blocks:
        text = text.replace('{placeholder}', removed_block, 1)

    if use_crlf:
        text = text.replace('\n', '\r\n')

    return text


def markdown(text, html=False, valid_tags=GFM_TAGS):
    """
    Return Markdown rendered text using GitHub Flavoured Markdown,
    with HTML escaped and syntax-highlighting enabled.
    """
    if text is None:
        return None
    if html:
        return Markup(sanitize_html(markdown_convert_html(gfm(text)), valid_tags=valid_tags))
    else:
        return Markup(markdown_convert_text(gfm(text)))
