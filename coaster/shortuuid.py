# -*- coding: utf-8 -*-

"""
ShortUUIDs
==========

Provides a wrapper around the ShortUUID module with a long-term stable
alphabet. This module may be used directly or via :mod:`coaster.utils`::

    import coaster.shortuuid

    # Generate a ShortUUID
    su = coaster.shortuuid.suuid()

    # Decode a ShortUUID into a UUID
    uu = coaster.shortuuid.decode(su)

    # Encode a UUID into a ShortUUID
    su2 = coaster.shortuuid.encode(uu)

    # Or use the same functions via coaster.utils (recommended)
    from coaster.utils import suuid, suuid2uuid, uuid2suuid

.. deprecated:: 0.6.1
    Use of ShortUUID is deprecated as the upstream library made an incompatible bugfix
    release that invalidated all previously generated ids, and no option for backward
    compatibility is available. Use Base58 instead. If your app has generated
    ShortUUIDs, make a static list for setting up redirects. Coaster has a pinned
    dependency on the previous version of the library that will be removed in a future
    release.
"""

from __future__ import absolute_import

from shortuuid import ShortUUID

__all__ = ['suuid', 'encode', 'decode']

# Create an instance of the ShortUUID class.

# This alphabet is the default, but we make a class instance anyway to (a) not
# be affected by global changes (from the module's set_alphabet function), and
# (b) to be isolated from upstream alphabet changes, unlikely as that may be.
# We also refuse to expose a set_alphabet function to the outer world, as that
# invalidates existing ids and so should never be used.
__su = ShortUUID(alphabet="23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")


def suuid():
    """
    Return a ShortUUID using the UUIDv4 version
    """
    return __su.uuid()


def encode(uuid):
    """
    Encode a UUID into a ShortUUID
    """
    return __su.encode(uuid)


def decode(uuid):
    """
    Decode a ShortUUID into a UUID
    """
    return __su.decode(uuid)
