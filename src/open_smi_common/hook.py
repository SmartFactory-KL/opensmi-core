# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Helper for dealing with async hooks."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable


async def call_hook(
    hook: Callable[[], Awaitable[None]],
) -> None:
    """Call coroutine ``hook``, but provide helpful ``TypeError`` if `hook` is not a coroutine."""
    if not inspect.iscoroutinefunction(hook):
        hook_class = f"{hook.__self__.__class__.__name__}."  # pyright: ignore[reportFunctionMemberAccess]
        msg = f"{hook_class}{hook.__name__}() must be declared with 'async def'."
        raise TypeError(msg)

    await hook()
