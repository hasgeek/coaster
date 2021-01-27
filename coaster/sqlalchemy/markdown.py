from typing import Any, Callable, Dict, Union

from sqlalchemy import Column, UnicodeText
from sqlalchemy.ext.mutable import MutableComposite
from sqlalchemy.orm import composite

from flask import Markup

from ..utils import markdown as markdown_processor

__all__ = ['MarkdownComposite', 'MarkdownColumn', 'markdown_column']


class MarkdownComposite(MutableComposite):
    """
    Represents GitHub-flavoured Markdown text and rendered HTML as a composite column.
    """

    #: Markdown processor. Subclasses can override this. This has to be a staticmethod
    #: or the markdown processor will receive `self` as first parameter
    markdown = staticmethod(markdown_processor)
    #: Markdown options. Subclasses can override this
    options: Union[
        Dict[str, Any],  # Options may be a dictionary of string keys,
        Callable[[], Dict[str, Any]],  # or a callable that returns such a dictionary
    ] = {}

    def __init__(self, text, html=None):
        if html is None:
            self.text = text  # This will regenerate HTML
        else:
            self._text = text
            self._html = html

    # Return column values for SQLAlchemy to insert into the database
    def __composite_values__(self):
        return (self._text, self._html)

    # Return a string representation of the text (see class decorator)
    def __str__(self):
        return self.text

    # Return a HTML representation of the text
    def __html__(self):
        return self._html or ''

    # Return a Markup string of the HTML
    @property
    def html(self):
        return Markup(self._html or '')

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        self._text = value
        self._html = self.markdown(
            value, **(self.options() if callable(self.options) else self.options)
        )
        self.changed()

    # Compare text value
    def __eq__(self, other):
        return isinstance(other, MarkdownComposite) and (
            self.__composite_values__() == other.__composite_values__()
        )

    def __ne__(self, other):
        return not self.__eq__(other)

    # Pickle support methods implemented as per SQLAlchemy documentation, but not
    # tested here as we don't use them.
    # https://docs.sqlalchemy.org/en/13/orm/extensions/mutable.html#id1

    def __getstate__(self):  # pragma: no cover
        # Return state for pickling
        return (self._text, self._html)

    def __setstate__(self, state):  # pragma: no cover
        # Set state from pickle
        self._text, self._html = state
        self.changed()

    def __bool__(self):
        return bool(self._text)

    __nonzero__ = __bool__

    # Allow a composite column to be assigned a string value
    @classmethod  # NOQA: A003
    def coerce(cls, key, value):  # NOQA: A003
        return cls(value)


def markdown_column(
    name, deferred=False, group=None, markdown=None, options=None, **kwargs
):
    """
    Create a composite column that autogenerates HTML from Markdown text,
    storing data in db columns named with ``_html`` and ``_text`` prefixes.

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
        pass

    CustomMarkdownComposite.options = options if options is not None else {}
    if markdown is not None:
        CustomMarkdownComposite.markdown = staticmethod(markdown)

    return composite(
        CustomMarkdownComposite
        if (markdown is not None or options is not None)
        else MarkdownComposite,
        Column(name + '_text', UnicodeText, **kwargs),
        Column(name + '_html', UnicodeText, **kwargs),
        deferred=deferred,
        group=group or name,
    )


# Compatibility name
MarkdownColumn = markdown_column
