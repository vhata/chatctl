"""Fetch a complete read-only conversation listing before selecting anything."""

import time
from collections.abc import Callable
from typing import Protocol

from chatctl.transport import (
    UNKNOWN_OUTCOME_GRACE_SECONDS,
    ClientError,
    decode_json,
)

PAGE_LIMIT = 100
PAGE_DELAY_SECONDS = 0.5
MAX_ATTEMPTS = 4
BACKOFF_SECONDS = (2.0, 4.0, 8.0)
MAX_PAGES = 200


class ListingTransport(Protocol):
    """Return raw listing JSON or raise ClientError; never mutate an account."""

    def get_page(self, offset: int, limit: int) -> str: ...


class ConversationClient:
    """Sequential pagination with bounded retries and no partial results.

    Items retain their raw fields, missing keys and duplicate ids so selection
    can apply its fail-closed checks. The listing is metadata, not a consistent
    snapshot: the server can move items between pages during a walk.
    """

    def __init__(
        self,
        transport: ListingTransport,
        *,
        sleep: Callable[[float], None] = time.sleep,
        max_pages: int = MAX_PAGES,
    ) -> None:
        if type(max_pages) is not int or max_pages < 1:
            raise ValueError("max_pages must be a positive integer")
        self._transport = transport
        self._sleep = sleep
        self._max_pages = max_pages

    def list_conversations(self) -> tuple[object, ...]:
        """Return the transport's configured listing, or fail in full.

        Each page's total means 'at least one more' until the final page;
        never use the first page's total as the history size. No account data
        is logged or written. This client exposes no per-id or mutation calls.
        """
        items: list[object] = []
        offset = 0
        for page_number in range(self._max_pages):
            if page_number:
                self._sleep(PAGE_DELAY_SECONDS)
            page = self._get_page(offset)
            if not isinstance(page, dict):
                raise ClientError("listing_shape")
            batch = page.get("items")
            total = page.get("total")
            if (
                not isinstance(batch, list)
                or len(batch) > PAGE_LIMIT
                or type(total) is not int
                or total < 0
                or type(page.get("offset")) is not int
                or page["offset"] != offset
                or type(page.get("limit")) is not int
                or page["limit"] != PAGE_LIMIT
            ):
                raise ClientError("listing_shape")
            items.extend(batch)
            offset += len(batch)
            if not batch or offset >= total:
                return tuple(items)
        raise ClientError("page_limit")

    def _get_page(self, offset: int) -> object:
        for attempt in range(MAX_ATTEMPTS):
            try:
                return decode_json(self._transport.get_page(offset, PAGE_LIMIT))
            except ClientError as error:
                if not error.retryable or attempt == MAX_ATTEMPTS - 1:
                    raise
                delay = BACKOFF_SECONDS[attempt]
                if error.uncertain:
                    delay = max(delay, UNKNOWN_OUTCOME_GRACE_SECONDS)
                if error.retry_after is not None:
                    delay = max(delay, min(60.0, error.retry_after))
                self._sleep(delay)
        raise AssertionError("unreachable")
