"""Thread-safe in-memory Session backend for openai-agents-python.

Implements ``SessionABC`` using an in-memory list protected by an
``asyncio.Lock``.  The key design point is that ``pop_item()`` must **not**
call the public ``get_item()`` while already holding ``self._lock`` — that
would deadlock because ``asyncio.Lock`` is not reentrant.

Fix (mirrors openai/openai-agents-python PR #2525):
  - ``_get_item_unsafe(index)`` — raw list access, NO lock acquired.
  - ``get_item(index)`` — acquires lock, delegates to ``_get_item_unsafe``.
  - ``pop_item()``       — acquires lock, calls ``_get_item_unsafe(-1)``
                            then removes the entry; never calls ``get_item``.
"""

from __future__ import annotations

import asyncio

from agents.items import TResponseInputItem
from agents.memory.session import SessionABC
from agents.memory.session_settings import SessionSettings, resolve_session_limit


class InMemorySession(SessionABC):
    """Thread-safe in-memory implementation of the Session protocol.

    All public methods acquire ``self._lock`` exactly once per call.
    Internal helpers prefixed with ``_`` and suffixed with ``_unsafe``
    operate on ``self._items`` directly and must only be called while the
    caller already holds the lock.
    """

    def __init__(
        self,
        session_id: str,
        *,
        session_settings: SessionSettings | None = None,
    ) -> None:
        self.session_id = session_id
        self.session_settings = session_settings or SessionSettings()
        self._items: list[TResponseInputItem] = []
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Internal unsafe helpers (call only while holding self._lock)
    # ------------------------------------------------------------------

    def _get_item_unsafe(self, index: int) -> TResponseInputItem | None:
        """Return the item at *index* without acquiring the lock.

        Args:
            index: Standard Python list index (0-based or negative).

        Returns:
            The item at *index*, or ``None`` if the list is empty or the
            index is out of range.
        """
        if not self._items:
            return None
        try:
            return self._items[index]
        except IndexError:
            return None

    # ------------------------------------------------------------------
    # Public SessionABC interface
    # ------------------------------------------------------------------

    async def get_items(self, limit: int | None = None) -> list[TResponseInputItem]:
        """Return a copy of the conversation history, newest-last.

        Args:
            limit: Maximum number of items to return.  ``None`` returns all.

        Returns:
            List of input items.
        """
        session_limit = resolve_session_limit(limit, self.session_settings)
        async with self._lock:
            items = list(self._items)
        if session_limit is not None and session_limit > 0:
            items = items[-session_limit:]
        return items

    async def get_item(self, index: int) -> TResponseInputItem | None:
        """Return a single item by index.

        Acquires ``self._lock`` then delegates to ``_get_item_unsafe``.
        **Do not call this from within another method that already holds
        the lock** — use ``_get_item_unsafe`` instead.

        Args:
            index: Standard Python list index.

        Returns:
            The item, or ``None`` if the index is out of range.
        """
        async with self._lock:
            return self._get_item_unsafe(index)

    async def add_items(self, items: list[TResponseInputItem]) -> None:
        """Append *items* to the conversation history.

        Args:
            items: Items to append.
        """
        if not items:
            return
        async with self._lock:
            self._items.extend(items)

    async def pop_item(self) -> TResponseInputItem | None:
        """Remove and return the most recent item.

        Acquires the lock **once** and uses ``_get_item_unsafe(-1)`` to
        read the last item before removing it — never calls the public
        ``get_item()`` which would re-acquire the lock and deadlock.

        Returns:
            The removed item, or ``None`` if the session is empty.
        """
        async with self._lock:
            item = self._get_item_unsafe(-1)  # read without re-acquiring lock
            if item is not None:
                self._items.pop()
            return item

    async def clear_session(self) -> None:
        """Remove all items from the session."""
        async with self._lock:
            self._items.clear()
