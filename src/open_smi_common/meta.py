# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Contains helper functions used for Python Metaprogramming magic."""

from typing import Any, TypeVar, get_args, get_origin


def resolve_generic_arguments(
    cls: type,
    target: type,
) -> tuple[type, ...] | None:
    """Find ``target[...]`` generic typing arguments through an inheritance tree.

    :param cls: concrete class to resolve generic arguments from.
    :param target: subclass of ``cls`` to resolve generic arguments for.
    :returns: tuple containing all resolved arguments.
    """

    def walk(current: type, substitutions: dict[TypeVar, Any]) -> tuple[Any, ...] | None:
        for base in getattr(current, "__orig_bases__", ()):
            origin = get_origin(base)
            args = get_args(base)

            if origin is None:
                continue

            # Replace already-known TypeVars
            resolved_args = tuple(substitutions.get(arg, arg) for arg in args)

            # Found the target
            if origin is target:
                return resolved_args

            # Build substitutions for this base
            parameters = getattr(origin, "__parameters__", ())

            child_substitutions = substitutions.copy()

            for parameter, value in zip(parameters, resolved_args, strict=False):
                child_substitutions[parameter] = value

            result = walk(origin, child_substitutions)

            if result is not None:
                return result

        return None

    return walk(cls, {})
