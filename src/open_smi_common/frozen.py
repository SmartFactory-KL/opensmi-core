# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Metaclass for frozen classes."""

from typing import Any, Never


class FrozenMeta(type):
    """Metaclass for frozen classes."""

    def __call__(cls, *args, **kwargs) -> Never:
        """Prevent instantiation of frozen classes."""
        msg = f"{cls.__name__} cannot be instantiated"
        raise TypeError(msg)

    def __setattr__(cls, name: str, value: Any) -> Never:
        """Prevent overriding attributes of frozen classes."""
        msg = f"{cls.__name__} is frozen"
        raise TypeError(msg)

    def __delattr__(cls, name: str) -> Never:
        """Prevent deleting attributes of frozen classes.."""
        msg = f"{cls.__name__} is frozen"
        raise TypeError(msg)
