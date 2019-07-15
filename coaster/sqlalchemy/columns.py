# -*- coding: utf-8 -*-

"""
SQLAlchemy column types
-----------------------
"""

from __future__ import absolute_import
import six

from sqlalchemy import Column, UnicodeText
from sqlalchemy.ext.mutable import Mutable, MutableComposite
from sqlalchemy.orm import composite
from sqlalchemy.types import TEXT, TypeDecorator, UserDefinedType
from sqlalchemy_utils.types import URLType as UrlTypeBase
from sqlalchemy_utils.types import UUIDType

from flask import Markup

from furl import furl
import simplejson

from ..utils import markdown

__all__ = ['JsonDict', 'MarkdownComposite', 'MarkdownColumn', 'UUIDType', 'UrlType',
    'markdown_column']


class JsonType(UserDefinedType):
    """The PostgreSQL JSON type."""

    def get_col_spec(self):
        return 'JSON'


class JsonbType(UserDefinedType):
    """The PostgreSQL JSONB type."""

    def get_col_spec(self):
        return 'JSONB'


# Adapted from http://docs.sqlalchemy.org/en/rel_0_8/orm/extensions/mutable.html#establishing-mutability-on-scalar-column-values

class JsonDict(TypeDecorator):
    """
    Represents a JSON data structure. Usage::

        column = Column(JsonDict)

    The column will be represented to the database as a ``JSONB`` column if
    the server is PostgreSQL 9.4 or later, ``JSON`` if PostgreSQL 9.2 or 9.3,
    and ``TEXT`` for everything else. The column behaves like a JSON store
    regardless of the backing data type.
    """

    impl = TEXT

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            version = tuple(dialect.server_version_info[:2])
            if version in [(9, 2), (9, 3)]:
                return dialect.type_descriptor(JsonType)
            elif version >= (9, 4):
                return dialect.type_descriptor(JsonbType)
        return dialect.type_descriptor(self.impl)

    def process_bind_param(self, value, dialect):
        if value is not None:
            value = simplejson.dumps(value, default=lambda o: six.text_type(o))
        return value

    def process_result_value(self, value, dialect):
        if value is not None and isinstance(value, six.string_types):
            # Psycopg2 >= 2.5 will auto-decode JSON columns, so
            # we only attempt decoding if the value is a string.
            # Since this column stores dicts only, processed values
            # can never be strings.
            value = simplejson.loads(value, use_decimal=True)
        return value


class MutableDict(Mutable, dict):
    @classmethod  # NOQA: A003
    def coerce(cls, key, value):
        """Convert plain dictionaries to MutableDict."""

        if not isinstance(value, MutableDict):
            if isinstance(value, dict):
                return MutableDict(value)
            elif isinstance(value, six.string_types):
                # Assume JSON string
                if value:
                    return MutableDict(simplejson.loads(value, use_decimal=True))
                else:
                    return MutableDict()  # Empty value is an empty dict

            # this call will raise ValueError
            return Mutable.coerce(key, value)
        else:
            return value

    def __setitem__(self, key, value):
        """Detect dictionary set events and emit change events."""

        dict.__setitem__(self, key, value)
        self.changed()

    def __delitem__(self, key):
        """Detect dictionary del events and emit change events."""

        dict.__delitem__(self, key)
        self.changed()


MutableDict.associate_with(JsonDict)


@six.python_2_unicode_compatible
class MarkdownComposite(MutableComposite):
    """
    Represents GitHub-flavoured Markdown text and rendered HTML as a composite column.
    """
    def __init__(self, text, html=None):
        if html is None:
            self.text = text  # This will regenerate HTML
        else:
            object.__setattr__(self, 'text', text)
            object.__setattr__(self, '_html', html)

    # If the text value is set, regenerate HTML, then notify parents of the change
    def __setattr__(self, key, value):
        if key == 'text':
            object.__setattr__(self, '_html', markdown(value))
        object.__setattr__(self, key, value)
        self.changed()

    # Return column values for SQLAlchemy to insert into the database
    def __composite_values__(self):
        return (self.text, self._html)

    # Return a string representation of the text (see class decorator)
    def __str__(self):
        return six.text_type(self.text)

    # Return a HTML representation of the text
    def __html__(self):
        return self._html or u''

    # Return a Markup string of the HTML
    @property
    def html(self):
        return Markup(self._html or u'')

    # Compare text value
    def __eq__(self, other):
        return (self.text == other.text) if isinstance(other, MarkdownComposite) else (self.text == other)

    def __ne__(self, other):
        return not self.__eq__(other)

    # Return state for pickling
    def __getstate__(self):
        return (self.text, self._html)

    # Set state from pickle
    def __setstate__(self, state):
        object.__setattr__(self, 'text', state[0])
        object.__setattr__(self, '_html', state[1])
        self.changed()

    def __bool__(self):
        return bool(self.text)

    __nonzero__ = __bool__

    # Allow a composite column to be assigned a string value
    @classmethod  # NOQA: A003
    def coerce(cls, key, value):
        return cls(value)


def markdown_column(name, deferred=False, group=None, **kwargs):
    """
    Create a composite column that autogenerates HTML from Markdown text,
    storing data in db columns named with ``_html`` and ``_text`` prefixes.
    """
    return composite(MarkdownComposite,
        Column(name + '_text', UnicodeText, **kwargs),
        Column(name + '_html', UnicodeText, **kwargs),
        deferred=deferred, group=group or name
        )


# Compatibility name
MarkdownColumn = markdown_column


class UrlType(UrlTypeBase):
    """
    Extension of URLType_ from SQLAlchemy-Utils that adds basic validation to
    ensure URLs are well formed. Parses the value into a :class:`furl` object,
    allowing manipulation of

    .. _URLType: https://sqlalchemy-utils.readthedocs.io/en/latest/data_types.html#module-sqlalchemy_utils.types.url

    :param schemes: Valid URL schemes. Use `None` to allow any scheme, `()` for no scheme
    :param optional_scheme: Schemes are optional (allows URLs starting with ``//``)
    :param optional_host: Allow URLs without a hostname (required for ``mailto`` and ``file`` schemes)
    """
    impl = UnicodeText

    def __init__(self, schemes=('http', 'https'), optional_scheme=False, optional_host=False):
        super(UrlType, self).__init__()
        self.schemes = schemes
        self.optional_host = optional_host
        self.optional_scheme = optional_scheme

    def process_bind_param(self, value, dialect):
        value = super(UrlType, self).process_bind_param(value, dialect)
        if value:
            parsed = furl(value)
            # If scheme is present, it must be valid
            # If not present, the optional flag must be True
            if parsed.scheme:
                if self.schemes is not None and parsed.scheme not in self.schemes:
                    raise ValueError("Invalid URL scheme")
            elif not self.optional_scheme:
                raise ValueError("Missing URL scheme")

            # Host may be missing only if optional
            if not parsed.host and not self.optional_host:
                raise ValueError(u"Missing URL host".format(value))
        return value
