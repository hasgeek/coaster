# -*- coding: utf-8 -*-

"""
PostgreSQL query processor
--------------------------
"""

from __future__ import absolute_import
import re

__all__ = ['for_tsquery']


_tsquery_tokens_re = re.compile(r'(:\*|\*|&|!|\||AND|OR|NOT|-|\(|\))', re.U)
_whitespace_re = re.compile(r'\s+', re.U)
_token_map = {'AND': '&', 'OR': '|', 'NOT': '!', '-': '!', '*': ':*'}


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
    >>> for_tsquery("(")
    ''
    >>> for_tsquery("() Python")
    "'Python'"
    >>> for_tsquery("!() Python")
    "'Python'"
    >>> for_tsquery("*")
    ''
    >>> for_tsquery("/etc/passwd\x00")
    '/etc/passwd'
    """
    tokens = [_token_map.get(t, t) for t in _tsquery_tokens_re.split(
            _whitespace_re.sub(' ', text.replace("'", " ").replace('"', ' ').replace('\0', '')))]
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
        while tokens and tokens[-1] in ('&', '|', '!', '('):
            tokens.pop(-1)  # Can't end with a binary or prefix operator
    if not tokens:
        return ''  # Did we just eliminate all tokens?
    missing_brackets = sum([1 if t == '(' else -1 for t in tokens if t in ('(', ')')])
    if missing_brackets > 0:
        tokens.append(')' * missing_brackets)
    elif missing_brackets < 0:
        tokens.insert(0, '(' * -missing_brackets)
    return ''.join(tokens)
