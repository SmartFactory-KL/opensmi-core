# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Functions to load configuration dataclasses from TOML files."""

import tomllib
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from types import UnionType
from typing import Any, TypeVar, Union, get_args, get_origin, get_type_hints

_T = TypeVar("_T")


def load_toml(path: str | Path) -> dict[str, Any]:
    """Load a TOML file into a dictionary."""
    with Path(path).open("rb") as f:
        return tomllib.load(f)


def load_dataclass(data_cls: type[_T], path: str | Path) -> _T:
    """Load a dataclass configuration from a TOML file."""
    return from_dict(data_cls, load_toml(path))


def from_dict(data_cls: type[_T], data: dict[str, Any]) -> _T:
    """Create a dataclass instance from a (TOML) dictionary."""
    if not is_dataclass(data_cls):
        msg = f"{data_cls.__name__} is not a dataclass"
        raise TypeError(msg)

    type_hints = get_type_hints(data_cls)
    known_fields: set[str] = {field_.name for field_ in fields(data_cls)}

    unknown: set[str] = set(data) - known_fields
    if unknown:
        msg = f"Unknown configuration option(s) for {data_cls.__name__}: " + ", ".join(sorted(unknown))
        raise ValueError(msg)

    kwargs = {name: _convert(value, type_hints[name]) for name, value in data.items()}
    # Fields not present in TOML are deliberately omitted.
    # The dataclass default/default_factory will be used.
    return data_cls(**kwargs)


def _convert(value: Any, target_type: Any) -> Any:
    """Convert a (TOML) value to the requested Python type."""
    origin = get_origin(target_type)

    # Optional[T] / T | None
    if origin in (Union, UnionType):
        args = get_args(target_type)

        if value is None and type(None) in args:
            return None

        non_none = [arg for arg in args if arg is not type(None)]
        if len(non_none) == 1:
            return _convert(value, non_none[0])

    # Enum
    if isinstance(target_type, type) and issubclass(target_type, Enum):
        try:
            return target_type(value)
        except ValueError as exc:
            valid = ", ".join(repr(member.value) for member in target_type)
            msg = f"Invalid value {value!r} for {target_type.__name__}; expected one of: {valid}"
            raise ValueError(msg) from exc

    # Nested dataclass
    if isinstance(target_type, type) and is_dataclass(target_type):
        if not isinstance(value, dict):
            msg = f"Expected a TOML table for {target_type.__name__}, got {type(value).__name__}"
            raise TypeError(msg)
        return from_dict(target_type, value)

    # list[T]
    if origin is list:
        assert isinstance(value, list)
        (item_type,) = get_args(target_type)
        return [_convert(item, item_type) for item in value]

    # dict[K, V]
    if origin is dict:
        assert isinstance(value, dict)
        key_type, value_type = get_args(target_type)
        return {_convert(key, key_type): _convert(item, value_type) for key, item in value.items()}

    # Basic types are already returned by tomllib.
    return value
