# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Mixin providing default ``__repr__`` and ``__str__`` implementations."""

from collections.abc import Iterator

from typing_extensions import override


class ReprStrMixin:
    """Mixin providing default `__repr__` and `__str__` implementations.

    Classes contribute representation items by overriding `_repr_items()`.
    Subclasses should call ``super()._repr_items()`` and yield additional
    ``(name, value)`` pairs.
    """

    def _repr_items(self) -> Iterator[tuple[str, object]]:
        """Yield ``(name, value)`` pairs for the string/repr representation."""
        yield from ()

    @override
    def __repr__(self) -> str:
        """Return an unambiguous representation of the instance."""
        args = ", ".join(f"{name}={value!r}" for name, value in self._repr_items())
        return f"{type(self).__name__}({args})"

    @override
    def __str__(self) -> str:
        """Return a human-readable representation of the instance."""
        return ", ".join(f"{name}={value}" for name, value in self._repr_items())
