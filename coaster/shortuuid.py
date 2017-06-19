# -*- coding: utf-8 -*-

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
