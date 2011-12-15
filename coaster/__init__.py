# -*- coding: utf-8 -*-

from __future__ import absolute_import
from os import environ
from random import randint
import uuid
from base64 import urlsafe_b64encode
import re

# --- Version -----------------------------------------------------------------

__version__ = '0.1'


# --- Common delimiters and punctuation ---------------------------------------

_strip_re = re.compile(ur'[\'"`‘’“”′″‴]+')
_punctuation_re = re.compile(ur'[\t +!#$%&()*\-/<=>?@\[\\\]^_{|}:;,.…‒–—―«»]+')


# --- Utilities ---------------------------------------------------------------

def newid():
    """
    Return a new random id that is exactly 22 characters long. See
    http://en.wikipedia.org/wiki/Base64#Variants_summary_table
    for URL-safe Base64
    """
    return urlsafe_b64encode(uuid.uuid4().bytes).rstrip('=')


def newpin(digits=4):
    """
    Return a random numeric string with the specified number of digits,
    default 4.
    """
    return (u'%%0%dd' % digits) % randint(0, 10**digits)


def makename(text, delim=u'-', maxlength=50, filter=None):
    u"""
    Generate a Unicode name slug.

    >>> makename('This is a title')
    u'this-is-a-title'
    >>> makename('Invalid URL/slug here')
    u'invalid-url-slug-here'
    >>> makename('this.that')
    u'this-that'
    >>> makename("How 'bout this?")
    u'how-bout-this'
    >>> makename(u"How’s that?")
    u'hows-that'
    >>> makename(u'K & D')
    u'k-d'
    >>> makename('billion+ pageviews')
    u'billion-pageviews'
    """
    return unicode(delim.join([_strip_re.sub('', x) for x in _punctuation_re.split(text.lower()) if x != '']))

def configureapp(app)
    """
    Configure an app depending on the situation
    """
    app.config.from_pyfile('settings.py')
    if environ.get('HGTV_ENV') == 'test':
        app.config.from_pyfile('testing.py')
    if environ.get('HGTV_ENV') == 'prod':
        app.config.from_pyfile('production.py')
