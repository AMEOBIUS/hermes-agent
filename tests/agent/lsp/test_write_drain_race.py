"""Regression: concurrent stdin writes must not race into a drain AssertionError.

The LSP reader loop dispatches server→client requests as fire-and-forget tasks.
Several of them — plus the request-sender path — can call
``StreamWriter.drain()`` on the *same* writer concurrently. asyncio's
``_drain_helper`` asserts a single drain waiter, so unsynchronized concurrent
drains blow up with ``AssertionError`` (surfaced as ``Task exception was never
retrieved`` log floods). ``LSPClient._write_stdin`` must serialize write+drain
behind ``self._write_lock``.
"""
from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from typing import Any, cast

import pytest

from agent.lsp.client import LSPClient, LSPProtocolError


class _AlwaysAssertStdin:
    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    def is_closing(self) -> bool:
        return False

    async def drain(self) -> None:
        raise AssertionError("synthetic drain assertion")


class _DrainAssertStdin:
    """Fake StreamWriter that replicates asyncio's single-drain-waiter rule.

    If a second ``drain()`` is entered while another is still waiting, it
    raises ``AssertionError`` exactly like ``asyncio.streams._drain_helper``.
    The ``await asyncio.sleep(0)`` makes the window deterministic: a task that
    is *not* holding a serializing lock is guaranteed to observe the in-flight
    waiter.
    """

    def __init__(self) -> None:
        self._waiter = None
        self.writes: list[bytes] = []
        self.max_concurrent_drains = 0
        self._active = 0

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    def is_closing(self) -> bool:
        return False

    async def drain(self) -> None:
        # Mirror asyncio.streams.FlowControlMixin._drain_helper assertion.
        assert self._waiter is None or self._waiter.cancelled(), \
            "concurrent drain() on a single writer (the bug)"
        self._active += 1
        self.max_concurrent_drains = max(self.max_concurrent_drains, self._active)
        loop = asyncio.get_running_loop()
        self._waiter = loop.create_future()
        try:
            await asyncio.sleep(0)  # yield: let other tasks try to race in
        finally:
            self._waiter = None
            self._active -= 1


def _make_client(stdin=None) -> LSPClient:
    """Minimal LSPClient with just the write plumbing wired up."""
    client = LSPClient.__new__(LSPClient)
    client.server_id = "test"
    client._write_lock = asyncio.Lock()
    client._proc = cast(Any, SimpleNamespace(stdin=stdin or _DrainAssertStdin()))
    return client


def test_write_stdin_serializes_concurrent_drains():
    """Many concurrent _write_stdin calls must all succeed without tripping
    the drain assertion, and never overlap inside drain()."""
    async def run():
        client = _make_client()
        results = await asyncio.gather(
            *[
                client._write_stdin(b"msg-%d" % i, label=f"r{i}")
                for i in range(50)
            ]
        )
        return results, client._proc.stdin

    results, stdin = asyncio.run(run())
    assert all(results), "every serialized write should report success"
    assert len(stdin.writes) == 50
    assert stdin.max_concurrent_drains == 1, (
        f"writes must be serialized; saw {stdin.max_concurrent_drains} "
        "concurrent drains (lock missing/broken)"
    )


def test_write_stdin_best_effort_swallows_drain_assertion():
    """Best-effort replies/notifications must not raise raw drain assertions."""
    async def run():
        client = _make_client(_AlwaysAssertStdin())
        return await client._write_stdin(b"msg", label="response 1")

    assert asyncio.run(run()) is False


def test_write_stdin_request_wraps_drain_assertion():
    """Request sends must surface drain assertion as LSPProtocolError."""
    async def run():
        client = _make_client(_AlwaysAssertStdin())
        with pytest.raises(LSPProtocolError):
            await client._write_stdin(b"msg", label="request", raise_on_error=True)

    asyncio.run(run())


def test_write_stdin_uses_write_lock():
    """Contract: _write_stdin must guard write+drain with self._write_lock."""
    source = inspect.getsource(LSPClient._write_stdin)
    lock_marker = "async with self._write_lock"
    drain_marker = "await self._proc.stdin.drain()"
    assert lock_marker in source, \
        "_write_stdin must serialize write+drain via self._write_lock"
    assert drain_marker in source, \
        "_write_stdin must await the StreamWriter drain"
    # drain() must be inside the lock, not after it. Use exact code markers so
    # docstring mentions of StreamWriter.drain() don't create false failures.
    lock_idx = source.index(lock_marker)
    drain_idx = source.index(drain_marker)
    assert lock_idx < drain_idx, \
        "drain() must happen inside the _write_lock block"


def test_reader_consumes_dispatch_task_exceptions():
    """Fire-and-forget dispatch tasks must have a done-callback that consumes
    their exception, so a failed reply never floods logs as 'never retrieved'."""
    reader_src = inspect.getsource(LSPClient._reader_loop)
    assert "add_done_callback" in reader_src, \
        "dispatched request tasks must register a done-callback"
    assert "_dispatch_tasks" in reader_src, \
        "dispatched request tasks must be retained in _dispatch_tasks"
    cb_src = inspect.getsource(LSPClient._on_dispatch_done)
    assert "task.exception()" in cb_src, \
        "_on_dispatch_done must retrieve the task exception"


def test_on_dispatch_done_swallows_exception():
    """Behavioural: a failed dispatch task is consumed (no unretrieved error)."""
    async def run():
        client = LSPClient.__new__(LSPClient)
        client.server_id = "test"
        client._dispatch_tasks = set()

        async def boom():
            raise RuntimeError("reply failed")

        task = asyncio.ensure_future(boom())
        client._dispatch_tasks.add(task)
        task.add_done_callback(client._on_dispatch_done)
        # Let the task run and the callback fire.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        # Exception is retrieved by the callback; set is cleaned up.
        assert task.done()
        assert task.exception() is not None
        assert task not in client._dispatch_tasks

    asyncio.run(run())
