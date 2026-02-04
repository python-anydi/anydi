from __future__ import annotations

import contextlib
import threading
from types import TracebackType
from typing import Any

import anyio.to_thread
from typing_extensions import Self

from ._async_lock import AsyncRLock
from ._types import NOT_SET


class InstanceContext:
    """A context to store instances."""

    __slots__ = ("_async_lock", "_async_stack", "_items", "_lock", "_stack")

    def __init__(self) -> None:
        self._items: dict[Any, Any] = {}
        self._stack: contextlib.ExitStack | None = None
        self._async_stack: contextlib.AsyncExitStack | None = None
        self._lock: threading.RLock | None = None
        self._async_lock: AsyncRLock | None = None

    def get(self, key: Any, default: Any = NOT_SET) -> Any:
        """Get an instance from the context."""
        return self._items.get(key, default)

    def set(self, key: Any, value: Any) -> None:
        """Set an instance in the context."""
        self._items[key] = value

    def enter(self, cm: contextlib.AbstractContextManager[Any]) -> Any:
        """Enter the context."""
        if self._stack is None:
            self._stack = contextlib.ExitStack()
        return self._stack.enter_context(cm)

    async def aenter(self, cm: contextlib.AbstractAsyncContextManager[Any]) -> Any:
        """Enter the context asynchronously."""
        if self._async_stack is None:
            self._async_stack = contextlib.AsyncExitStack()
        return await self._async_stack.enter_async_context(cm)

    def __setitem__(self, key: Any, value: Any) -> None:
        self._items[key] = value

    def __getitem__(self, key: Any) -> Any:
        return self._items[key]

    def __contains__(self, key: Any) -> bool:
        return key in self._items

    def __delitem__(self, key: Any) -> None:
        self._items.pop(key, None)

    def __enter__(self) -> Self:
        """Enter the context."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> Any:
        """Exit the context."""
        if self._stack is None:
            return False
        return self._stack.__exit__(exc_type, exc_val, exc_tb)

    def close(self) -> None:
        """Close the scoped context."""
        if self._stack is not None:
            self._stack.__exit__(None, None, None)

    async def __aenter__(self) -> Self:
        """Enter the context asynchronously."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        """Exit the context asynchronously."""
        sync_exit = False
        async_exit = False
        if self._stack is not None:
            sync_exit = await anyio.to_thread.run_sync(
                self.__exit__, exc_type, exc_val, exc_tb
            )
        if self._async_stack is not None:
            async_exit = await self._async_stack.__aexit__(exc_type, exc_val, exc_tb)
        return bool(sync_exit) or bool(async_exit)

    async def aclose(self) -> None:
        """Close the scoped context asynchronously."""
        await self.__aexit__(None, None, None)

    def lock(self) -> threading.RLock:
        """Acquire the context lock."""
        if self._lock is None:
            self._lock = threading.RLock()
        return self._lock

    def alock(self) -> AsyncRLock:
        """Acquire the context lock asynchronously."""
        if self._async_lock is None:
            self._async_lock = AsyncRLock()
        return self._async_lock
