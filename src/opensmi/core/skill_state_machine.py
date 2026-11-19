# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""The skill state machine as specified by ``SkillStateMachineType`` in the MachineSet nodeset.

Finite and continuous skills share one state machine type. Continuous skills never complete, so they use it without
the transitions from or to `SkillState.COMPLETING` and `SkillState.COMPLETED`.

A transition without a cause is an *internal* transition: the server takes it on its own and no skill command
triggers it. A transition with a cause may still be taken by the server on its own, e.g. halting on a failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from opensmi.core.nodesets.skill_state_machine import SKILL_STATE_MACHINE_TYPE as _TYPE
from opensmi.core.ua import NodeIdDefinition, QualifiedName
from opensmi.core.ua_enums import SkillState

_METHOD_IDS: Final[dict[str, NodeIdDefinition]] = {method.name: method.node_id for method in _TYPE.methods}
_STATE_IDS: Final[dict[str, NodeIdDefinition]] = {state.name: state.node_id for state in _TYPE.states}
_STATES_BY_NAME: Final[dict[str, SkillState]] = {state.value[1]: state for state in SkillState}


class SkillCommand(Enum):
    """A command a client sends to a skill, by calling the method of the same name on the skill's state machine."""

    START = "Start"
    HALT = "Halt"
    RESET = "Reset"
    SUSPEND = "Suspend"

    @property
    def browse_name(self) -> QualifiedName:
        """Browse name of the method, to find it on a skill instance."""
        return QualifiedName(namespace_uri=self.declaration_id.namespace_uri, name=self.value)

    @property
    def declaration_id(self) -> NodeIdDefinition:
        """NodeId of the method declared in ``SkillStateMachineType``.

        For identification only: a command is called on the method of the skill instance, found by `browse_name`.
        """
        return _METHOD_IDS[self.value]


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillTransition:
    """A transition of the skill state machine."""

    name: str
    """Browse name of the transition, e.g. ``ReadyToStarting``."""
    source: SkillState
    target: SkillState
    cause: SkillCommand | None
    """Command that triggers this transition, or ``None`` for an internal transition."""
    node_id: NodeIdDefinition
    """NodeId of the transition in ``SkillStateMachineType``, as in ``LastTransition/Id``."""


_FINITE_ONLY: Final[frozenset[SkillState]] = frozenset({SkillState.COMPLETING, SkillState.COMPLETED})
_FINITE: Final[tuple[SkillTransition, ...]] = tuple(
    SkillTransition(
        name=transition.name,
        source=_STATES_BY_NAME[transition.source],
        target=_STATES_BY_NAME[transition.target],
        cause=SkillCommand(transition.cause) if transition.cause is not None else None,
        node_id=transition.node_id,
    )
    for transition in _TYPE.transitions
)
_CONTINUOUS: Final[tuple[SkillTransition, ...]] = tuple(
    t for t in _FINITE if t.source not in _FINITE_ONLY and t.target not in _FINITE_ONLY
)
_STATES_BY_ID: Final[dict[NodeIdDefinition, SkillState]] = {
    node_id: _STATES_BY_NAME[name] for name, node_id in _STATE_IDS.items()
}


def transitions(*, finite: bool) -> tuple[SkillTransition, ...]:
    """Return all transitions of a finite or a continuous skill."""
    return _FINITE if finite else _CONTINUOUS


def transitions_from(state: SkillState, *, finite: bool) -> tuple[SkillTransition, ...]:
    """Return the transitions leaving ``state`` for a finite or a continuous skill."""
    return tuple(t for t in transitions(finite=finite) if t.source == state)


def allowed_commands(state: SkillState, *, finite: bool, suspendable: bool) -> frozenset[SkillCommand]:
    """Return the commands a skill in ``state`` accepts.

    :param finite: whether the skill is finite or continuous.
    :param suspendable: whether the skill can be suspended; a skill that cannot has no Suspend method.
    """
    commands = {t.cause for t in transitions_from(state, finite=finite) if t.cause is not None}
    if not suspendable:
        commands.discard(SkillCommand.SUSPEND)
    return frozenset(commands)


def state_node_id(state: SkillState) -> NodeIdDefinition:
    """Return the NodeId of ``state`` in ``SkillStateMachineType``, as in ``CurrentState/Id``."""
    return _STATE_IDS[state.value[1]]


def state_for_node_id(node_id: NodeIdDefinition) -> SkillState:
    """Return the state whose NodeId in ``SkillStateMachineType`` is ``node_id``, e.g. read from ``CurrentState/Id``.

    :raises KeyError: If ``node_id`` is not a state of ``SkillStateMachineType``.
    """
    return _STATES_BY_ID[node_id]
