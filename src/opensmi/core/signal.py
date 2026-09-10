# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""A mutable async signal for registering and invoking callbacks."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Generic, ParamSpec

_P = ParamSpec("_P")

Callback = Callable[_P, Awaitable[None]]


class Signal(Generic[_P]):
    """A mutable async signal for registering and invoking callbacks."""

    def __init__(self) -> None:
        self._callbacks: set[Callback[_P]] = set()

    def connect(self, callback: Callback[_P]) -> None:
        """Register a callback."""
        self._callbacks.add(callback)

    def disconnect(self, callback: Callback[_P]) -> None:
        """Unregister a callback if present."""
        self._callbacks.discard(callback)

    async def send(self, *args: _P.args, **kwargs: _P.kwargs) -> None:
        """Invoke all registered callbacks concurrently.

        The callback set is snapshot before dispatch, so callbacks may safely connect or disconnect
        callbacks while handling the signal.
        """
        await asyncio.gather(*(callback(*args, **kwargs) for callback in tuple(self._callbacks)))
