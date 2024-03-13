"""
SQLAlchemy column types
-----------------------
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping
from typing import Any, Optional

import sqlalchemy as sa
from furl import furl
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.mutable import Mutable
from sqlalchemy.types import TypeDecorator
from sqlalchemy_utils.types import URLType as UrlTypeBase

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

    # TypeDecorator replaces the Type with an instance of the type in the instance
    impl: sa.types.JSON = sa.types.JSON  # type: ignore[assignment]
    cache_ok = False

    def load_dialect_impl(self, dialect: sa.Dialect) -> sa.types.TypeEngine:
        """Use JSONB column in PostgreSQL."""
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(postgresql.JSONB)  # type: ignore[arg-type]
        return dialect.type_descriptor(self.impl)

    def coerce_compared_value(self, op: Any, value: Any) -> sa.types.TypeEngine:
        """Coerce an incoming value using the JSON type's default handler."""
        return self.impl.coerce_compared_value(op, value)

    def process_bind_param(self, value: Any, dialect: sa.Dialect) -> Any:
        """Convert a Python value into a JSON string for the database."""
        if value is not None:
            value = json.dumps(value, default=str)  # Callable default
        return value

    def process_result_value(self, value: Any, dialect: sa.Dialect) -> Any:
        """Convert a JSON string from the database into a dict."""
        if value is not None and isinstance(value, str):
            # Psycopg2 >= 2.5 will auto-decode JSON columns, so
            # we only attempt decoding if the value is a string.
            # Since this column stores dicts only, processed values
            # can never be strings.
            value = json.loads(value)
        return value


class MutableDict(Mutable, dict):
    @classmethod
    def coerce(cls, key: Any, value: Any) -> Optional[MutableDict]:
        """Convert plain dictionaries to MutableDict."""
        if value is None:
            return None
        if not isinstance(value, MutableDict):
            if isinstance(value, Mapping):
                return MutableDict(value)
            if isinstance(value, str):
                # Got a string, attempt to parse as JSON
                try:
                    return MutableDict(json.loads(value))
                except ValueError:
                    raise ValueError(f"Invalid JSON string: {value!r}") from None
            raise ValueError(f"Value is not dict-like: {value!r}")
        return value

    def __setitem__(self, key: Any, value: Any) -> None:
        """Detect dictionary set events and emit change events."""
        dict.__setitem__(self, key, value)
        self.changed()

    def __delitem__(self, key: Any) -> None:
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
        schemes: Optional[Collection[str]] = ('http', 'https'),
        optional_scheme: bool = False,
        optional_host: bool = False,
    ) -> None:
        super().__init__()
        self.schemes = schemes
        self.optional_host = optional_host
        self.optional_scheme = optional_scheme

    def process_bind_param(self, value: Any, dialect: sa.Dialect) -> Optional[str]:
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

    def process_result_value(self, value: Any, dialect: sa.Dialect) -> Optional[furl]:
        """Cast URL loaded from database into a furl object."""
        if value is not None:
            return self.url_parser(value)
        return None

    def _coerce(self, value: Any) -> Optional[furl]:
        if value is not None and not isinstance(value, self.url_parser):
            return self.url_parser(value)
        return value
