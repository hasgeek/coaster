"""
Pagination for query/select results.

This module is borrowed from Flask-SQLAlchemy and updated for async and type hinting.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from math import ceil
from typing import TYPE_CHECKING, Any, Final, Generic, Optional, TypeVar, Union
from typing_extensions import Self

import sqlalchemy as sa
import sqlalchemy.orm as sa_orm
from sqlalchemy import func as sa_func, select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from ..compat import abort, request

_O = TypeVar('_O', bound=object)

MAX_PER_PAGE_DEFAULT: Final[int] = 100

__all__ = ['SelectPagination', 'QueryPagination']


class Pagination(Generic[_O]):
    """Paginate a query applying an offset and limit given the page number.

    Don't create pagination objects manually. They are created by
    :meth:`.SQLAlchemy.paginate` and :meth:`.Query.paginate`.

    This is a base class, a subclass must implement :meth:`_query_items` and
    :meth:`_query_count`. Those methods will use arguments passed as ``kwargs`` to
    perform the queries.

    :param page: The current page, used to calculate the offset. Defaults to the
        ``page`` query arg during a request, or 1 otherwise.
    :param per_page: The maximum number of items on a page, used to calculate the
        offset and limit. Defaults to the ``per_page`` query arg during a request,
        or 20 otherwise.
    :param max_per_page: The maximum allowed value for ``per_page``, to limit a
        user-provided value. Use ``None`` for no limit. Defaults to 100.
    :param error_out: Abort with a ``404 Not Found`` error if no items are returned
        and ``page`` is not 1, or if ``page`` or ``per_page`` is less than 1, or if
        either are not ints.
    :param count: Calculate the total number of values by issuing an extra count
        query. For very complex queries this may be inaccurate or slow, so it can be
        disabled and set manually if necessary.
    :param kwargs: Information about the query to paginate. Different subclasses will
        require different arguments.
    """

    #: The current page
    page: int
    #: The maximum number of items on a page
    per_page: int
    #: The maximum allowed value for ``per_page``
    max_per_page: Optional[int]
    #: The items on the current page. Iterating over the pagination object is
    #: equivalent to iterating over the items
    items: Sequence[_O]
    #: The total number of items across all pages
    total: Optional[int]

    def __init__(
        self,
        _total: Optional[int],  # Internal parameter, passed by subclasses
        *,
        page: int,
        per_page: int,
        max_per_page: Optional[int] = MAX_PER_PAGE_DEFAULT,
        error_out: bool = True,
        **kwargs: Any,
    ) -> None:
        # Keep kwargs to subclasses for navigation between pages
        self._subcls_kwargs = kwargs
        self.total = _total
        self.max_per_page = max_per_page
        self.page = page
        self.per_page = per_page
        if not self.items and page != 1 and error_out:
            abort(404)

    @classmethod
    async def anew(cls, *args, **kwargs) -> Self:
        """Async init, to be overridden in subclasses as needed."""
        return cls(*args, **kwargs)

    @staticmethod
    def _prepare_page_args(
        *,
        page: Optional[int] = None,
        per_page: Optional[int] = None,
        max_per_page: Optional[int] = None,
        error_out: bool = True,
    ) -> tuple[int, int]:
        if request:
            if page is None:
                try:
                    page = int(request.args.get('page', 1))
                except (TypeError, ValueError):
                    if error_out:
                        abort(404)

                    page = 1

            if per_page is None:
                try:
                    per_page = int(request.args.get('per_page', 20))
                except (TypeError, ValueError):
                    if error_out:
                        abort(404)

                    per_page = 20
        else:
            if page is None:
                page = 1

            if per_page is None:
                per_page = 20

        if max_per_page is not None:
            per_page = min(per_page, max_per_page)

        if page < 1:
            if error_out:
                abort(404)
            else:
                page = 1

        if per_page < 1:
            if error_out:
                abort(404)
            else:
                per_page = 20

        return page, per_page

    @staticmethod
    def _get_offset(page: int, per_page: int) -> int:
        """Classmethod implementation of :meth:`_offset`."""
        return (page - 1) * per_page

    @property
    def first(self) -> int:
        """The number of the first item on the page (1-based), 0 if no items."""
        if len(self.items) == 0:
            return 0

        return (self.page - 1) * self.per_page + 1

    @property
    def last(self) -> int:
        """The number of the last item on the page (1-based), 0 if no items."""
        first = self.first
        return max(first, first + len(self.items) - 1)

    @property
    def pages(self) -> int:
        """The total number of pages."""
        if self.total == 0 or self.total is None:
            return 0

        return ceil(self.total / self.per_page)

    @property
    def has_prev(self) -> bool:
        """``True`` if this is not the first page."""
        return self.page > 1

    @property
    def prev_num(self) -> Optional[int]:
        """The previous page number, or ``None`` if this is the first page."""
        if not self.has_prev:
            return None

        return self.page - 1

    def prev(self, *, error_out: bool = False) -> Self:
        """Query the :class:`Pagination` object for the previous page.

        :param error_out: Abort with a ``404 Not Found`` error if no items are returned
            and ``page`` is not 1, or if ``page`` or ``per_page`` is less than 1, or if
            either are not ints.
        """
        return self.__class__(
            page=self.page - 1,
            per_page=self.per_page,
            error_out=error_out,
            count=False,
            _total=self.total,
            **self._subcls_kwargs,
        )

    async def aprev(self, *, error_out: bool = False) -> Self:
        """Async implementation of :meth:`prev`."""
        return await self.anew(
            page=self.page - 1,
            per_page=self.per_page,
            error_out=error_out,
            count=False,
            _total=self.total,
            **self._subcls_kwargs,
        )

    @property
    def has_next(self) -> bool:
        """``True`` if this is not the last page."""
        return self.page < self.pages

    @property
    def next_num(self) -> Optional[int]:
        """The next page number, or ``None`` if this is the last page."""
        if not self.has_next:
            return None

        return self.page + 1

    def next(self, *, error_out: bool = False) -> Self:
        """Query the :class:`Pagination` object for the next page.

        :param error_out: Abort with a ``404 Not Found`` error if no items are returned
            and ``page`` is not 1, or if ``page`` or ``per_page`` is less than 1, or if
            either are not ints.
        """
        return self.__class__(
            page=self.page + 1,
            per_page=self.per_page,
            max_per_page=self.max_per_page,
            error_out=error_out,
            count=False,
            _total=self.total,
            **self._subcls_kwargs,
        )

    async def anext(self, *, error_out: bool = False) -> Self:
        """Async implementation of :meth:`next`."""
        return await self.anew(
            page=self.page + 1,
            per_page=self.per_page,
            max_per_page=self.max_per_page,
            error_out=error_out,
            count=False,
            _total=self.total,
            **self._subcls_kwargs,
        )

    def iter_pages(
        self,
        *,
        left_edge: int = 2,
        left_current: int = 2,
        right_current: int = 4,
        right_edge: int = 2,
    ) -> Iterator[Optional[int]]:
        """
        Yield page numbers for a pagination widget.

        Skipped pages between the edges and middle are represented by a ``None``.

        For example, if there are 20 pages and the current page is 7, the following
        values are yielded.

        ::

            1, 2, None, 5, 6, 7, 8, 9, 10, 11, None, 19, 20

        :param left_edge: How many pages to show from the first page
        :param left_current: How many pages to show left of the current page
        :param right_current: How many pages to show right of the current page
        :param right_edge: How many pages to show from the last page
        """
        pages_end = self.pages + 1

        if pages_end == 1:
            return

        left_end = min(1 + left_edge, pages_end)
        yield from range(1, left_end)

        if left_end == pages_end:
            return

        mid_start = max(left_end, self.page - left_current)
        mid_end = min(self.page + right_current + 1, pages_end)

        if mid_start - left_end > 0:
            yield None

        yield from range(mid_start, mid_end)

        if mid_end == pages_end:
            return

        right_start = max(mid_end, pages_end - right_edge)

        if right_start - mid_end > 0:
            yield None

        yield from range(right_start, pages_end)

    def __iter__(self) -> Iterator[Any]:
        yield from self.items


class SelectPagination(Pagination[_O]):
    """Returned by :meth:`.SQLAlchemy.paginate`."""

    def __init__(
        self,
        session: Union[sa_orm.Session, AsyncSession],
        select: sa.Select[tuple[_O]],
        *,
        page: Optional[int] = None,
        per_page: Optional[int] = None,
        max_per_page: Optional[int] = MAX_PER_PAGE_DEFAULT,
        error_out: bool = True,
        count: bool = True,
        _page_items: Sequence[_O] = (),
        _total: Optional[int] = None,
    ) -> None:
        if (not _page_items or (count and _total is None)) and isinstance(
            session, AsyncSession
        ):
            raise TypeError(
                f"Use {self.__class__.__qualname__}.anew() with an async session"
            )
        if TYPE_CHECKING:
            assert isinstance(session, sa_orm.Session)  # nosec B101

        if page is None or per_page is None:
            page, per_page = self._prepare_page_args(
                page=page,
                per_page=per_page,
                max_per_page=max_per_page,
                error_out=error_out,
            )

        if not _page_items:
            item_select = select.limit(per_page).offset(
                self._get_offset(page, per_page)
            )
            _page_items = list(session.execute(item_select).unique().scalars())
        if count and _total is None:
            sub = select.options(sa_orm.lazyload('*')).order_by(None).subquery()
            _total = session.execute(
                sa_select(
                    sa_func.count()  # pylint: disable=not-callable
                ).select_from(sub)
            ).scalar()
        self.items = _page_items
        super().__init__(
            page=page,
            per_page=per_page,
            max_per_page=max_per_page,
            error_out=error_out,
            count=count,
            _total=_total,
            select=select,
            session=session,
        )

    @classmethod
    async def anew(  # pylint: disable=arguments-differ
        cls,
        session: AsyncSession,
        select: sa.Select[tuple[_O]],
        *,
        page: Optional[int] = None,
        per_page: Optional[int] = None,
        max_per_page: Optional[int] = 100,
        error_out: bool = True,
        count: bool = True,
        _total: Optional[int] = None,
    ) -> Self:
        """Async init. Accepts the same parameters as :meth:`__init__`."""
        page, per_page = cls._prepare_page_args(
            page=page,
            per_page=per_page,
            max_per_page=max_per_page,
            error_out=error_out,
        )
        item_select = select.limit(per_page).offset(cls._get_offset(page, per_page))
        items = list((await session.execute(item_select)).unique().scalars())
        if count and _total is None:
            sub = select.options(sa_orm.lazyload('*')).order_by(None).subquery()
            _total = (
                await session.execute(
                    sa_select(
                        sa_func.count()  # pylint: disable=not-callable
                    ).select_from(sub)
                )
            ).scalar()
        return cls(
            select=select,
            session=session,
            page=page,
            per_page=per_page,
            max_per_page=max_per_page,
            error_out=error_out,
            count=count,
            _page_items=items,
            _total=_total,
        )


class QueryPagination(Pagination[_O]):
    """Returned by :meth:`.Query.paginate`."""

    def __init__(
        self,
        query: sa_orm.Query[_O],
        *,
        page: Optional[int] = None,
        per_page: Optional[int] = None,
        max_per_page: Optional[int] = MAX_PER_PAGE_DEFAULT,
        error_out: bool = True,
        count: bool = True,
        _page_items: Sequence[_O] = (),
        _total: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        if page is None or per_page is None:
            page, per_page = self._prepare_page_args(
                page=page,
                per_page=per_page,
                max_per_page=max_per_page,
                error_out=error_out,
            )
        if not _page_items:
            _page_items = (
                query.limit(per_page).offset(self._get_offset(page, per_page)).all()
            )
        if count and _total is None:
            _total = query.order_by(None).count()
        self.items = _page_items
        super().__init__(
            page=page,
            per_page=per_page,
            max_per_page=max_per_page,
            error_out=error_out,
            count=count,
            _page_items=_page_items,
            _total=_total,
            **kwargs,
        )
