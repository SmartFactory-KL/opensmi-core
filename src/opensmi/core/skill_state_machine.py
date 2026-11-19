# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""The skill state machine as specified by ``SkillStateMachineType`` in the MachineSet nodeset.

Finite and continuous skills share one state machine type. Continuous skills never complete, so they use it without
the transitions from or to `SkillState.COMPLETING` and `SkillState.COMPLETED`. Skills that cannot be suspended have no
Suspend method, so they use it without the transitions from or to `SkillState.SUSPENDING` and `SkillState.SUSPENDED`.

A transition without a cause is an *internal* transition: the server takes it on its own and no skill command
triggers it. A transition with a cause may still be taken by the server on its own, e.g. halting on a failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import cache
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


_COMPLETION: Final[frozenset[SkillState]] = frozenset({SkillState.COMPLETING, SkillState.COMPLETED})
_SUSPENSION: Final[frozenset[SkillState]] = frozenset({SkillState.SUSPENDING, SkillState.SUSPENDED})
_TYPE_TRANSITIONS: Final[tuple[SkillTransition, ...]] = tuple(
    SkillTransition(
        name=transition.name,
        source=_STATES_BY_NAME[transition.source],
        target=_STATES_BY_NAME[transition.target],
        cause=SkillCommand(transition.cause) if transition.cause is not None else None,
        node_id=transition.node_id,
    )
    for transition in _TYPE.transitions
)

_STATES_BY_ID: Final[dict[NodeIdDefinition, SkillState]] = {
    node_id: _STATES_BY_NAME[name] for name, node_id in _STATE_IDS.items()
}


@cache
def transitions(*, finite: bool, suspendable: bool) -> tuple[SkillTransition, ...]:
    """Return all transitions of a skill.

    :param finite: whether the skill is finite or continuous.
    :param suspendable: whether the skill can be suspended.
    """
    excluded: set[SkillState] = set()
    if not finite:
        excluded |= _COMPLETION
    if not suspendable:
        excluded |= _SUSPENSION
    return tuple(t for t in _TYPE_TRANSITIONS if not {t.source, t.target} & excluded)


def states(*, finite: bool, suspendable: bool) -> tuple[SkillState, ...]:
    """Return the states a skill can be in, in `SkillState` order, see `transitions()`."""
    present = {s for t in transitions(finite=finite, suspendable=suspendable) for s in (t.source, t.target)}
    return tuple(s for s in SkillState if s in present)


def allowed_commands(state: SkillState, *, finite: bool, suspendable: bool) -> frozenset[SkillCommand]:
    """Return the commands a skill in ``state`` accepts.

    :param finite: whether the skill is finite or continuous.
    :param suspendable: whether the skill can be suspended.
    """
    skill_transitions = transitions(finite=finite, suspendable=suspendable)
    return frozenset(t.cause for t in skill_transitions if t.source == state and t.cause is not None)


def state_node_id(state: SkillState) -> NodeIdDefinition:
    """Return the NodeId of ``state`` in ``SkillStateMachineType``, as in ``CurrentState/Id``."""
    return _STATE_IDS[state.value[1]]


def state_for_node_id(node_id: NodeIdDefinition) -> SkillState:
    """Return the state whose NodeId in ``SkillStateMachineType`` is ``node_id``, e.g. read from ``CurrentState/Id``.

    :raises KeyError: If ``node_id`` is not a state of ``SkillStateMachineType``.
    """
    return _STATES_BY_ID[node_id]
