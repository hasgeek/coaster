"""Markdown composite columns."""

from __future__ import annotations

from typing import Any, Callable, Optional, Union
from typing_extensions import deprecated

import sqlalchemy as sa
from markupsafe import Markup
from sqlalchemy.ext.mutable import MutableComposite
from sqlalchemy.orm import Composite, composite

from ..utils import markdown as markdown_processor

__all__ = ['MarkdownComposite', 'MarkdownColumn', 'markdown_column']


class MarkdownComposite(MutableComposite):
    """Represents Markdown text and rendered HTML as a composite column."""

    #: Markdown processor. Subclasses can override this. This has to be a staticmethod
    #: or the markdown processor will receive `self` as first parameter
    markdown = staticmethod(markdown_processor)
    #: Markdown options. Subclasses can override this
    options: Union[
        # Options may be a dictionary of string keys,
        dict[str, Any],
        # or a callable that returns such a dictionary
        Callable[[], dict[str, Any]],
    ] = {}

    def __init__(self, text: Optional[str], html: Optional[str] = None) -> None:
        """Create a composite."""
        if html is None:
            self.text = text  # This will regenerate HTML
        else:
            self._text = text
            self._html: Optional[str] = html

    # Return column values for SQLAlchemy to insert into the database
    def __composite_values__(
        self,
    ) -> tuple[Optional[str], Optional[str]]:
        """Return composite values."""
        return (self._text, self._html)

    # Return a string representation of the text (see class decorator)
    def __str__(self) -> str:
        """Return string representation."""
        return self.text or ''

    # Return a HTML representation of the text
    def __html__(self) -> str:
        """Return HTML representation."""
        return self._html or ''

    # Return a Markup string of the HTML
    @property
    def html(self) -> Optional[Markup]:
        """Return HTML as a property."""
        return Markup(self._html) if self._html is not None else None

    @property
    def text(self) -> Optional[str]:
        """Return text as a property."""
        return self._text

    @text.setter
    def text(self, value: Optional[str]) -> None:
        """Set the text value."""
        self._text = None if value is None else str(value)
        # Mypy and Pylance appear to be incorrectly typing self.markdown as taking
        # a parameter text=Literal[None] based on the first overload in the original
        # function declaration
        self._html = self.markdown(
            self._text,  # type: ignore[arg-type]
            **(
                self.options()  # pylint: disable=not-callable
                if callable(self.options)
                else self.options
            ),
        )
        self.changed()

    def __json__(self) -> Any:
        """Return JSON-compatible rendering of composite."""
        return {'text': self._text, 'html': self._html}

    # Compare text value
    def __eq__(self, other: object) -> bool:
        """Compare for equality."""
        if self is other:
            return True
        if isinstance(other, MarkdownComposite):
            return self.__composite_values__() == other.__composite_values__()
        return NotImplemented

    # Pickle support methods implemented as per SQLAlchemy documentation, but not
    # tested here as we don't use them.
    # https://docs.sqlalchemy.org/en/13/orm/extensions/mutable.html#id1

    def __getstate__(  # pragma: no cover
        self,
    ) -> tuple[Optional[str], Optional[str]]:
        """Get state for pickling."""
        # Return state for pickling
        return (self._text, self._html)

    def __setstate__(  # pragma: no cover
        self, state: tuple[Optional[str], Optional[str]]
    ) -> None:
        """Set state from pickle."""
        # Set state from pickle
        self._text, self._html = state
        self.changed()

    def __bool__(self) -> bool:
        """Return boolean value."""
        return bool(self._text)

    @classmethod
    def coerce(cls, _key: str, value: Any) -> MarkdownComposite:
        """Allow a composite column to be assigned a string value."""
        return cls(value)


def markdown_column(
    name: str,
    deferred: bool = False,
    group: Optional[str] = None,
    markdown: Optional[Callable] = None,
    options: Optional[dict] = None,
    **kwargs,
) -> Composite[MarkdownComposite]:
    """
    Create a composite column that autogenerates HTML from Markdown text.

    Creates two db columns named with ``_html`` and ``_text`` suffixes.

    :param str name: Column name base
    :param bool deferred: Whether the columns should be deferred by default
    :param str group: Defer column group
    :param markdown: Markdown processor function (default: Coaster's implementation)
    :param options: Additional options for the Markdown processor
    :param kwargs: Additional column options, passed to SQLAlchemy's column constructor
    """

    # Construct a custom subclass of MarkdownComposite and set the markdown processor
    # and processor options on it. We'll pass this class to SQLAlchemy's composite
    # constructor.
    class CustomMarkdownComposite(MarkdownComposite):
        """Customised markdown composite."""

    CustomMarkdownComposite.options = options if options is not None else {}
    CustomMarkdownComposite.markdown = staticmethod(
        markdown  # type:ignore[arg-type]
        if markdown is not None
        else markdown_processor
    )
    return composite(
        (
            CustomMarkdownComposite
            if (markdown is not None or options is not None)
            else MarkdownComposite
        ),
        sa.Column(name + '_text', sa.UnicodeText, **kwargs),
        sa.Column(name + '_html', sa.UnicodeText, **kwargs),
        deferred=deferred,
        group=group or name,
    )


# Compatibility name
MarkdownColumn = deprecated("MarkdownColumn has been renamed to markdown_column")(
    markdown_column
)
