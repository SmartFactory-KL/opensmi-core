# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Sentinel to distinguish unset values from ``None`` values."""

from typing import Final, TypeGuard, TypeVar

_T = TypeVar("_T")


class Unset:
    """Sentinel to distinguish unset values from ``None`` values."""


UNSET: Final = Unset()
"""Singleton instance to signal unset values."""


def is_set(value: _T | Unset) -> TypeGuard[_T]:
    """Return ``True`` if given ``value`` is set."""
    return value is not UNSET
