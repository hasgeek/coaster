"""
SQLAlchemy column types
-----------------------
"""

from __future__ import annotations

from collections.abc import Mapping
import json
import typing as t

from furl import furl
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.mutable import Mutable
from sqlalchemy.types import TypeDecorator
from sqlalchemy_utils.types import URLType as UrlTypeBase
import sqlalchemy as sa

__all__ = ['JsonDict', 'UrlType']


# Adapted from http://docs.sqlalchemy.org/en/rel_0_8/orm/extensions/mutable.html
# #establishing-mutability-on-scalar-column-values


class JsonDict(TypeDecorator):
    """
    Represents a JSON data structure.

    Usage::

        column = Column(JsonDict)

    The column will be represented to the database as a ``JSONB`` column if
    the server is PostgreSQL 9.4 or later, ``JSON`` if PostgreSQL 9.2 or 9.3,
    and ``TEXT`` for everything else. The column behaves like a JSON store
    regardless of the backing data type.
    """

    impl = sa.types.JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: sa.Dialect) -> sa.types.TypeEngine:
        """Use JSONB column in PostgreSQL."""
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(postgresql.JSONB)  # type: ignore[arg-type]
        return dialect.type_descriptor(self.impl)  # type: ignore[arg-type]

    def process_bind_param(self, value: t.Any, dialect: sa.Dialect) -> t.Any:
        if value is not None:
            value = json.dumps(value, default=str)  # Callable default
        return value

    def process_result_value(self, value: t.Any, dialect: sa.Dialect) -> t.Any:
        if value is not None and isinstance(value, str):
            # Psycopg2 >= 2.5 will auto-decode JSON columns, so
            # we only attempt decoding if the value is a string.
            # Since this column stores dicts only, processed values
            # can never be strings.
            value = json.loads(value)
        return value


class MutableDict(Mutable, dict):
    @classmethod
    def coerce(cls, key: t.Any, value: t.Any) -> t.Optional[MutableDict]:
        """Convert plain dictionaries to MutableDict."""
        if value is None:
            return None
        if not isinstance(value, MutableDict):
            if isinstance(value, Mapping):
                return MutableDict(value)
            raise ValueError(f"Value is not dict-like: {value}")
        return value

    def __setitem__(self, key: t.Any, value: t.Any) -> None:
        """Detect dictionary set events and emit change events."""
        dict.__setitem__(self, key, value)
        self.changed()

    def __delitem__(self, key: t.Any) -> None:
        """Detect dictionary del events and emit change events."""
        dict.__delitem__(self, key)
        self.changed()


MutableDict.associate_with(JsonDict)


class UrlType(UrlTypeBase):
    """
    Extension of URLType_ from SQLAlchemy-Utils that ensures URLs are well formed.

    .. _URLType: https://sqlalchemy-utils.readthedocs.io/en/latest/data_types.html#module-sqlalchemy_utils.types.url

    :param schemes: Valid URL schemes. Use `None` to allow any scheme,
        `()` for no scheme
    :param optional_scheme: Schemes are optional (allows URLs starting with ``//``)
    :param optional_host: Allow URLs without a hostname (required for ``mailto`` and
        ``file`` schemes)
    """

    impl = sa.Unicode
    url_parser = furl
    cache_ok = True

    def __init__(
        self,
        schemes: t.Optional[t.Collection[str]] = ('http', 'https'),
        optional_scheme: bool = False,
        optional_host: bool = False,
    ) -> None:
        super().__init__()
        self.schemes = schemes
        self.optional_host = optional_host
        self.optional_scheme = optional_scheme

    def process_bind_param(self, value: t.Any, dialect: sa.Dialect) -> t.Optional[str]:
        """Validate URL before storing to the database."""
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

    def process_result_value(
        self, value: t.Any, dialect: sa.Dialect
    ) -> t.Optional[furl]:
        """Cast URL loaded from database into a furl object."""
        if value is not None:
            return self.url_parser(value)
        return None

    def _coerce(self, value: t.Any) -> t.Optional[furl]:
        if value is not None and not isinstance(value, self.url_parser):
            return self.url_parser(value)
        return value
