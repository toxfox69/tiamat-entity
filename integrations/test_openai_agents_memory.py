"""Tests for InMemorySession — validates the pop_item() deadlock fix.

The critical property under test:
  pop_item() must acquire self._lock exactly once.  Calling the public
  get_item() from inside pop_item() while already holding an asyncio.Lock
  would deadlock (asyncio.Lock is *not* reentrant).  The fix introduces
  _get_item_unsafe() which reads self._items directly, with no lock
  acquisition.

These tests run without the real ``openai-agents-python`` package by
stubbing all cross-package imports with lightweight fakes.
"""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
from typing import Any
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Stub out the agents.* imports so the module loads without the SDK.
# ---------------------------------------------------------------------------

def _install_stubs() -> None:
    """Inject minimal fake modules into sys.modules before importing."""

    # TResponseInputItem — just a type alias; any value works.
    TResponseInputItem = Any  # noqa: N806

    # SessionABC — abstract base; we just need a plain base class.
    class SessionABC:  # noqa: D101
        pass

    class SessionSettings:  # noqa: D101
        pass

    def resolve_session_limit(limit, settings):  # noqa: ANN001, ANN201
        return limit

    # Build the fake package hierarchy.
    agents_pkg = types.ModuleType("agents")
    agents_items = types.ModuleType("agents.items")
    agents_items.TResponseInputItem = TResponseInputItem
    agents_memory = types.ModuleType("agents.memory")
    agents_session = types.ModuleType("agents.memory.session")
    agents_session.SessionABC = SessionABC
    agents_session_settings = types.ModuleType("agents.memory.session_settings")
    agents_session_settings.SessionSettings = SessionSettings
    agents_session_settings.resolve_session_limit = resolve_session_limit

    # Wire up sub-module references so ``from agents.X import Y`` works.
    agents_pkg.items = agents_items
    agents_pkg.memory = agents_memory
    agents_memory.session = agents_session
    agents_memory.session_settings = agents_session_settings

    for name, mod in [
        ("agents", agents_pkg),
        ("agents.items", agents_items),
        ("agents.memory", agents_memory),
        ("agents.memory.session", agents_session),
        ("agents.memory.session_settings", agents_session_settings),
    ]:
        sys.modules.setdefault(name, mod)


_install_stubs()

# Now the real import can succeed.
from integrations.openai_agents_memory import InMemorySession  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):  # noqa: ANN001, ANN201
    """Run a coroutine in a fresh event loop."""
    return asyncio.run(coro)


def _make_item(value: str) -> dict:
    """Return a minimal fake TResponseInputItem."""
    return {"role": "user", "content": value}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPopItemDeadlockFix(unittest.TestCase):
    """pop_item() must not re-acquire self._lock while already holding it."""

    def test_pop_item_on_empty_returns_none(self):
        """pop_item() on an empty session must return None, not raise."""
        session = InMemorySession(session_id="test-empty")
        result = run(session.pop_item())
        self.assertIsNone(result)

    def test_pop_item_returns_last_item(self):
        """pop_item() returns the most recently added item."""
        session = InMemorySession(session_id="test-last")
        a, b = _make_item("a"), _make_item("b")
        run(session.add_items([a, b]))
        result = run(session.pop_item())
        self.assertEqual(result, b)

    def test_pop_item_removes_item_from_session(self):
        """After pop_item(), the session should have one fewer item."""
        session = InMemorySession(session_id="test-remove")
        items = [_make_item("x"), _make_item("y"), _make_item("z")]
        run(session.add_items(items))
        run(session.pop_item())
        remaining = run(session.get_items())
        self.assertEqual(len(remaining), 2)
        self.assertEqual(remaining[-1], _make_item("y"))

    def test_pop_item_does_not_deadlock(self):
        """The critical regression test: pop_item() must complete without hang.

        Before the fix, pop_item() called get_item(-1) which re-acquired
        self._lock.  asyncio.Lock is not reentrant, so the second acquire
        would wait forever — deadlocking the event loop.

        We enforce a tight timeout so the test fails fast if the bug regresses.
        """
        session = InMemorySession(session_id="test-deadlock")
        run(session.add_items([_make_item("only")]))

        async def _with_timeout():
            return await asyncio.wait_for(session.pop_item(), timeout=1.0)

        # Must complete without asyncio.TimeoutError.
        result = run(_with_timeout())
        self.assertEqual(result, _make_item("only"))

    def test_pop_item_uses_unsafe_helper_not_public_get_item(self):
        """pop_item() must call _get_item_unsafe, never get_item().

        Patch get_item() to raise; if pop_item() calls it, the test fails.
        This directly asserts the structural invariant of the fix.
        """
        session = InMemorySession(session_id="test-no-get-item")
        run(session.add_items([_make_item("item")]))

        async def _boom(*_, **__):
            raise AssertionError("pop_item() must NOT call get_item()")

        with patch.object(session, "get_item", side_effect=_boom):
            result = run(session.pop_item())

        self.assertEqual(result, _make_item("item"))

    def test_pop_item_atomic_under_concurrent_access(self):
        """Two concurrent pop_item() calls must each return a distinct item.

        If the lock were not held across both read and remove, two coroutines
        could both read the same last item before either removes it, returning
        duplicates.
        """
        session = InMemorySession(session_id="test-concurrent")
        items = [_make_item("alpha"), _make_item("beta")]
        run(session.add_items(items))

        async def _two_pops():
            return await asyncio.gather(
                asyncio.create_task(session.pop_item()),
                asyncio.create_task(session.pop_item()),
            )

        results = run(_two_pops())
        # Both items must be returned, no duplicates, no None surprises.
        self.assertTrue(all(r is not None for r in results))
        self.assertEqual(sorted(r["content"] for r in results if r), ["alpha", "beta"])

    def test_sequential_pops_drain_session(self):
        """Repeated pop_item() calls drain items in LIFO order."""
        session = InMemorySession(session_id="test-drain")
        items = [_make_item(str(i)) for i in range(5)]
        run(session.add_items(items))

        popped = [run(session.pop_item()) for _ in range(5)]
        contents = [p["content"] for p in popped if p is not None]  # type: ignore[index]
        self.assertEqual(contents, ["4", "3", "2", "1", "0"])  # LIFO

        # Session is now empty.
        self.assertIsNone(run(session.pop_item()))

    def test_get_item_unsafe_never_acquires_lock(self):
        """_get_item_unsafe() is a plain sync method — it must not touch self._lock.

        If it were async or acquired the lock, calling it while holding the
        lock in pop_item() would either type-error or deadlock.
        """
        session = InMemorySession(session_id="test-unsafe")
        run(session.add_items([_make_item("z")]))

        # Must be a plain (non-async) callable.
        import inspect
        self.assertFalse(
            inspect.iscoroutinefunction(session._get_item_unsafe),
            "_get_item_unsafe must be sync, not async",
        )

        # Must return the last item without acquiring the lock.
        result = session._get_item_unsafe(-1)
        self.assertEqual(result, _make_item("z"))

    def test_clear_session_after_pops(self):
        """clear_session() works correctly after some items have been popped."""
        session = InMemorySession(session_id="test-clear")
        run(session.add_items([_make_item("a"), _make_item("b"), _make_item("c")]))
        run(session.pop_item())  # removes "c"
        run(session.clear_session())
        self.assertEqual(run(session.get_items()), [])


if __name__ == "__main__":
    unittest.main()
