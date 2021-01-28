"""
SQLAlchemy column types
-----------------------
"""

from sqlalchemy import UnicodeText
from sqlalchemy.ext.mutable import Mutable
from sqlalchemy.types import TEXT, TypeDecorator, UserDefinedType
from sqlalchemy_utils.types import URLType as UrlTypeBase
from sqlalchemy_utils.types import UUIDType

from furl import furl
import simplejson

__all__ = ['JsonDict', 'UUIDType', 'UrlType']


class JsonType(UserDefinedType):
    """The PostgreSQL JSON type."""

    def get_col_spec(self):
        return 'JSON'


class JsonbType(UserDefinedType):
    """The PostgreSQL JSONB type."""

    def get_col_spec(self):
        return 'JSONB'


# Adapted from http://docs.sqlalchemy.org/en/rel_0_8/orm/extensions/mutable.html
# #establishing-mutability-on-scalar-column-values


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
            if version >= (9, 4):
                return dialect.type_descriptor(JsonbType)
        return dialect.type_descriptor(self.impl)

    def process_bind_param(self, value, dialect):
        if value is not None:
            value = simplejson.dumps(value, default=str)  # Callable default
        return value

    def process_result_value(self, value, dialect):
        if value is not None and isinstance(value, str):
            # Psycopg2 >= 2.5 will auto-decode JSON columns, so
            # we only attempt decoding if the value is a string.
            # Since this column stores dicts only, processed values
            # can never be strings.
            value = simplejson.loads(value, use_decimal=True)
        return value


class MutableDict(Mutable, dict):
    @classmethod  # NOQA: A003
    def coerce(cls, key, value):  # NOQA: A003
        """Convert plain dictionaries to MutableDict."""
        if not isinstance(value, MutableDict):
            if isinstance(value, dict):
                return MutableDict(value)
            if isinstance(value, str):
                # Assume JSON string
                if value:
                    return MutableDict(simplejson.loads(value, use_decimal=True))
                return MutableDict()  # Empty value is an empty dict

            # this call will raise ValueError
            return Mutable.coerce(key, value)
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


class UrlType(UrlTypeBase):
    """
    Extension of URLType_ from SQLAlchemy-Utils that adds basic validation to
    ensure URLs are well formed. Parses the value into a :class:`furl` object,
    allowing manipulation of

    .. _URLType: https://sqlalchemy-utils.readthedocs.io/en/latest/data_types.html#module-sqlalchemy_utils.types.url

    :param schemes: Valid URL schemes. Use `None` to allow any scheme,
        `()` for no scheme
    :param optional_scheme: Schemes are optional (allows URLs starting with ``//``)
    :param optional_host: Allow URLs without a hostname (required for ``mailto`` and
        ``file`` schemes)
    """

    impl = UnicodeText
    url_parser = furl

    def __init__(
        self, schemes=('http', 'https'), optional_scheme=False, optional_host=False
    ):
        super().__init__()
        self.schemes = schemes
        self.optional_host = optional_host
        self.optional_scheme = optional_scheme

    def process_bind_param(self, value, dialect):
        value = super().process_bind_param(value, dialect)
        if value:
            parsed = self.url_parser(value)
            # If scheme is present, it must be valid
            # If not present, the optional flag must be True
            if parsed.scheme:
                if self.schemes is not None and parsed.scheme not in self.schemes:
                    raise ValueError("Invalid URL scheme")
            elif not self.optional_scheme:
                raise ValueError("Missing URL scheme")

            # Host may be missing only if optional
            if not parsed.host and not self.optional_host:
                raise ValueError("Missing URL host")
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return self.url_parser(value)

    def _coerce(self, value):
        if value is not None and not isinstance(value, self.url_parser):
            return self.url_parser(value)
        return value
