# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Mixin for reliable tracking of fire-and-forget asyncio tasks."""

import asyncio
from collections.abc import Coroutine
from typing import Any


class AsyncTaskMixin:
    """Mixin for reliable tracking of fire-and-forget asyncio tasks.

    Avoids such tasks disappearing while executing when garbage collected
    (https://docs.python.org/3/library/asyncio-task.html#creating-tasks).
    """

    __tasks: set[asyncio.Task[None]] | None = None

    def _create_task(
        self,
        coro: Coroutine[Any, Any, None],  # pyright: ignore[reportExplicitAny]
        *,
        name: str,
    ) -> None:
        """Schedule and track a background coroutine.

        The coroutine must return ``None``.
        """
        if self.__tasks is None:
            self.__tasks = set()

        task = asyncio.create_task(coro, name=name)
        self.__tasks.add(task)
        task.add_done_callback(self.__tasks.discard)

    @property
    def _pending_tasks(self) -> set[asyncio.Task[None]]:
        """Return currently running tracked tasks."""
        if self.__tasks is None:
            return set()
        return self.__tasks.copy()

    async def _cancel_tasks(self) -> None:
        """Cancel and await all tracked tasks."""
        if self.__tasks is None:
            return  # nothing to cancel
        tasks = self.__tasks.copy()

        for task in tasks:
            _ = task.cancel()

        if tasks:
            _ = await asyncio.gather(*tasks, return_exceptions=True)
