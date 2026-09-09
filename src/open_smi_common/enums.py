# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Common enumerations."""

from enum import Enum

from asyncua import ua


class LocalizedTextEnum(Enum):
    """Enum that return their str values in form of an OPC UA LocalizedText."""

    @property
    def localized_text(self) -> ua.LocalizedText:
        """Return the OPC UA localized text of the enum member."""
        return ua.LocalizedText(Text=self.value, Locale="en-US")


class SkillState(Enum):
    """Represents the state of a skill (`BaseSkill`).

    State values according to the skill node-set specification.
    """

    HALTED = (11, "Halted")
    """State indicating that the skill is halted (=stopped). To leave this state, the skill needs to be reset.
    **Note**: Skills can halt for various reasons, e.g. internal failures, external safety trigger, etc."""
    READY = (12, "Ready")
    """State indicating that the skill is ready to be started."""
    RUNNING = (13, "Running")
    """State indicating that the skill is running."""
    SUSPENDED = (14, "Suspended")
    """State indicating that the skill is suspended."""
    COMPLETED = (15, "Completed")
    """State indicating that the skill is completed. 
    Only used for finite skills, because continuous skills do not complete."""

    STARTING = (16, "Starting")
    """Intermediate state leading to `SkillState.RUNNING` on success or `SkillState.HALTING` on failure."""
    HALTING = (17, "Halting")
    """Intermediate state always leading to `SkillState.HALTED`."""
    COMPLETING = (18, "Completing")
    """Intermediate state leading to `SkillState.COMPLETED` on success or `SkillState.HALTING` on failure.
    Only used for finite skills, because continuous skills do not complete."""
    RESETTING = (19, "Resetting")
    """Intermediate state leading to `SkillState.READY` on success or `SkillState.HALTING` on failure."""
    SUSPENDING = (20, "Suspending")
    """Intermediate state leading to `SkillState.SUSPENDING` on success or `SkillState.HALTING` on failure."""

    @property
    def localized_text(self) -> ua.LocalizedText:
        """Return the OPC UA localized text of the enum member."""
        return ua.LocalizedText(Text=self.value[1], Locale="en-US")

    @property
    def id(self) -> int:
        """Return the state ID number of the enum member."""
        return self.value[0]


class MachineryItemState(LocalizedTextEnum):
    """Represents the state of a machinery item (`BaseMachineryItem`).

    Documentation from https://reference.opcfoundation.org/Machinery/v103/docs/12.2
    """

    NOT_AVAILABLE = "NotAvailable"
    """The machine is not available and does not perform any activity (e.g., switched off, in energy saving mode)"""
    OUT_OF_SERVICE = "OutOfService"
    """The machine is not functional and does not perform any activity (e.g., error, blocked)"""
    NOT_EXECUTING = "NotExecuting"
    """The machine is available & functional and does not perform any activity. 
    It waits for an action from outside to start or restart an activity."""
    EXECUTING = "Executing"
    """The machine is available & functional and is actively performing an activity (pursues a purpose)."""


class MachineryOperationMode(LocalizedTextEnum):
    """Represents the operation mode of a machinery item (`BaseMachineryItem`).

    Documentation from https://reference.opcfoundation.org/Machinery/v103/docs/13.2
    """

    NONE = "None"
    """No machinery operation mode available."""
    MAINTENANCE = "Maintenance"
    """Mode with the intention to carry out maintenance or servicing activities."""
    SETUP = "Setup"
    """Mode with the intention to carry out setup, preparation or postprocessing activities of a production process."""
    PROCESSING = "Processing"
    """Mode with the intention to carry out the value adding activities."""
