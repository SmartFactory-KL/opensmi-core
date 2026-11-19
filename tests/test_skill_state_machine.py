# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Tests of the skill state machine spec generated from the MachineSet nodeset."""

from __future__ import annotations

import pytest

from opensmi.core import SkillState
from opensmi.core.nodesets import SmartFactoryMachineSetNodeIds
from opensmi.core.nodesets.skill_state_machine import SKILL_STATE_MACHINE_TYPE
from opensmi.core.skill_state_machine import (
    SkillCommand,
    allowed_commands,
    state_for_node_id,
    state_node_id,
    states,
    transitions,
)
from opensmi.core.ua import NodeIdDefinition, QualifiedName

_URI = SmartFactoryMachineSetNodeIds.URI
S = SkillState
C = SkillCommand


def test_skill_state_matches_generated_states() -> None:
    assert {(s.value[1], s.id) for s in SkillState} == {(s.name, s.number) for s in SKILL_STATE_MACHINE_TYPE.states}


def test_skill_command_matches_generated_methods() -> None:
    assert {c.value for c in SkillCommand} == {m.name for m in SKILL_STATE_MACHINE_TYPE.methods}


def test_skill_command_names() -> None:
    assert C.HALT.browse_name == QualifiedName(namespace_uri=_URI, name="Halt")
    assert C.HALT.declaration_id == NodeIdDefinition(identifier=7014, namespace_uri=_URI)


def test_continuous_drops_only_completion() -> None:
    finite = set(transitions(finite=True, suspendable=True))
    continuous = set(transitions(finite=False, suspendable=True))
    completion = {S.COMPLETING, S.COMPLETED}

    assert continuous < finite
    assert all({t.source, t.target} & completion for t in finite - continuous)
    assert not any({t.source, t.target} & completion for t in continuous)


def test_not_suspendable_drops_only_suspension() -> None:
    suspendable = set(transitions(finite=True, suspendable=True))
    not_suspendable = set(transitions(finite=True, suspendable=False))
    suspension = {S.SUSPENDING, S.SUSPENDED}

    assert not_suspendable < suspendable
    assert all({t.source, t.target} & suspension for t in suspendable - not_suspendable)
    assert not any({t.source, t.target} & suspension for t in not_suspendable)


def test_states() -> None:
    assert states(finite=True, suspendable=True) == tuple(SkillState)
    assert set(states(finite=False, suspendable=False)) == set(SkillState) - {
        S.COMPLETING,
        S.COMPLETED,
        S.SUSPENDING,
        S.SUSPENDED,
    }


def _leaving(state: SkillState, *, finite: bool) -> set[tuple[SkillState, SkillCommand | None]]:
    return {(t.target, t.cause) for t in transitions(finite=finite, suspendable=True) if t.source == state}


def test_transitions_leaving_running() -> None:
    assert _leaving(S.RUNNING, finite=True) == {
        (S.COMPLETING, None),
        (S.HALTING, C.HALT),
        (S.SUSPENDING, C.SUSPEND),
    }
    assert _leaving(S.RUNNING, finite=False) == {
        (S.HALTING, C.HALT),
        (S.SUSPENDING, C.SUSPEND),
    }


@pytest.mark.parametrize("finite", [True, False], ids=["finite", "continuous"])
def test_suspending_leads_only_to_suspended_or_halting(finite: bool) -> None:
    # as in PackML, a skill completes only from Running, never out of a suspend
    assert _leaving(S.SUSPENDING, finite=finite) == {
        (S.SUSPENDED, None),
        (S.HALTING, C.HALT),
    }


_ALLOWED_FINITE: dict[SkillState, set[SkillCommand]] = {
    S.HALTED: {C.RESET},
    S.RESETTING: {C.HALT},
    S.READY: {C.START, C.HALT},
    S.STARTING: {C.HALT},
    S.RUNNING: {C.HALT, C.SUSPEND},
    S.SUSPENDING: {C.HALT},
    S.SUSPENDED: {C.START, C.HALT},
    S.COMPLETING: {C.HALT},
    S.COMPLETED: {C.RESET, C.HALT},
    S.HALTING: set(),
}


@pytest.mark.parametrize("state", list(SkillState), ids=lambda s: s.name)
@pytest.mark.parametrize("suspendable", [True, False], ids=["suspendable", "not suspendable"])
def test_allowed_commands_finite(state: SkillState, suspendable: bool) -> None:
    if suspendable:
        expected = _ALLOWED_FINITE[state]
    else:
        expected = set() if state in (S.SUSPENDING, S.SUSPENDED) else _ALLOWED_FINITE[state] - {C.SUSPEND}
    assert allowed_commands(state, finite=True, suspendable=suspendable) == expected


@pytest.mark.parametrize("state", list(SkillState), ids=lambda s: s.name)
def test_allowed_commands_continuous(state: SkillState) -> None:
    expected = set() if state in (S.COMPLETING, S.COMPLETED) else _ALLOWED_FINITE[state]
    assert allowed_commands(state, finite=False, suspendable=True) == expected


@pytest.mark.parametrize("state", list(SkillState), ids=lambda s: s.name)
def test_state_node_id_round_trip(state: SkillState) -> None:
    node_id = state_node_id(state)
    assert node_id.namespace_uri == _URI
    assert state_for_node_id(node_id) == state


def test_state_for_unknown_node_id() -> None:
    with pytest.raises(KeyError):
        state_for_node_id(NodeIdDefinition(identifier=1, namespace_uri=_URI))
