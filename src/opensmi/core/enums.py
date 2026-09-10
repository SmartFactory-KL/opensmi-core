# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

from enum import IntEnum, auto


class LifecycleState(IntEnum):
    """Represents the lifecycle state of an instance of machine, skill, component, etc."""

    NEW = auto()
    """ Instance is created, but not (async) initialized. """
    INITIALIZING = auto()
    """ Instance is currently (async) initializing. """
    INITIALIZED = auto()
    """ Instance is initialized successfully and ready to be used. """
    INITIALIZATION_FAILED = auto()
    """ Instance initialization failed and instance may need to be shut down. """
    SHUTTING_DOWN = auto()
    """ Instance is currently (async) shutting down. """
    SHUTDOWN = auto()
    """ Instance is shut down successfully and cannot be used anymore. Final state."""
    SHUTDOWN_FAILED = auto()
    """ Instance shutdown failed and cannot be used anymore. Final state."""
