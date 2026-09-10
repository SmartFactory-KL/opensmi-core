# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

from collections.abc import Hashable


class OpenSmiError(Exception):
    """Base for all OpenSMI related errors."""


class SkillNotSuspendableError(OpenSmiError):
    """Is raised when failing to suspend a skill that is not suspendable."""


class OpenSmiRuntimeError(OpenSmiError):
    """Is raised by user code when something goes wrong.

    Use this exception instead of the build-in ``RuntimeError``.
    """

    def __init__(self, msg: str, error_code: str = "") -> None:
        """Construct a new PyUaAdapterError with the given error message and error code."""
        self.msg = msg
        self.error_code = error_code


class NoValidValueReadError(OpenSmiError):
    """Is raised when trying to read a `UaVariable` whose value is ``None``."""


class SkillHaltedError(OpenSmiRuntimeError):
    """Is raised when a skill other than the own skill is halted.

    (i.e. when calling other skills)
    """


class OutOfRangeError(OpenSmiRuntimeError):
    """Is raised when failing to write a value to a variable that is out of range."""


class NamespaceUninitializedError(OpenSmiError):
    """Is raised when trying to get node ids from a namespace before it was initialized."""


class RequiredVariableMissingError(OpenSmiError):
    """Is raised when a required variable is missing."""


class ValidationError(ValueError):
    """Is raised when trying to validate an object that doesn't pass validation.

    Will only be raised during initialization.
    """


class CycleError(Exception):
    """Raised when a dependency graph of ``@lifecycle`` decorated methods contains a cycle.

    See `LifecycleMixin` for more details.
    """

    def __init__(self, path: list[Hashable]) -> None:
        """Construct a new CycleError with the given path containing the cycle."""
        node: Hashable = path[-1]
        super().__init__(f"cycle detected at {node!r} (path: {path!r})")
