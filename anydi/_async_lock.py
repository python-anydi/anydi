from types import TracebackType
from typing import Any, Self

import anyio


class AsyncRLock:
    def __init__(self) -> None:
        self._lock = anyio.Lock()
        self._owner: anyio.TaskInfo | None = None
        self._count = 0

    async def acquire(self) -> None:
        current_task = anyio.get_current_task()
        if self._owner == current_task:
            self._count += 1
        else:
            await self._lock.acquire()
            self._owner = current_task
            self._count = 1

    def release(self) -> None:
        if self._owner != anyio.get_current_task():
            raise RuntimeError("Lock can only be released by the owner")
        self._count -= 1
        if self._count == 0:
            self._owner = None
            self._lock.release()

    async def __aenter__(self) -> Self:
        await self.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> Any:
        self.release()
