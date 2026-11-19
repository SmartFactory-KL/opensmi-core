# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Tests of the skill state machine spec generated from the MachineSet nodeset."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from importlib.resources import files

import pytest

from opensmi.core import SkillState
from opensmi.core.nodesets import SmartFactoryMachineSetNodeIds
from opensmi.core.nodesets.skill_state_machine import SKILL_STATE_MACHINE_TYPE
from opensmi.core.skill_state_machine import (
    SkillCommand,
    allowed_commands,
    state_for_node_id,
    state_node_id,
    transitions,
    transitions_from,
)
from opensmi.core.ua import NodeIdDefinition, QualifiedName

_NS = {"ua": "http://opcfoundation.org/UA/2011/03/UANodeSet.xsd"}
_URI = SmartFactoryMachineSetNodeIds.URI
S = SkillState
C = SkillCommand


def _children_in_xml() -> tuple[dict, dict, dict]:
    """Return states, transitions and methods of ``SkillStateMachineType`` read straight from the XML."""
    root = ET.fromstring(
        files("opensmi.core.nodesets").joinpath(SmartFactoryMachineSetNodeIds.FILE_NAME).read_text(encoding="utf-8")
    )
    nodes = {node.attrib["NodeId"]: node for node in root if "NodeId" in node.attrib}

    def name(node_id: str) -> str:
        return nodes[node_id].attrib["BrowseName"].split(":")[-1]

    def ident(node_id: str) -> int:
        return int(node_id.rsplit("i=", 1)[1])

    type_id = next(n for n, node in nodes.items() if name(n) == "SkillStateMachineType")
    states, transitions_, methods = {}, {}, {}
    for node_id, node in nodes.items():
        if node.attrib.get("ParentNodeId") != type_id:
            continue
        refs = {r.attrib["ReferenceType"]: r.text for r in node.find("ua:References", _NS)}
        if node.tag.endswith("UAMethod"):
            methods[name(node_id)] = ident(node_id)
        elif refs.get("HasTypeDefinition") == "i=2307":
            number = next(c for c in nodes.values() if c.attrib.get("ParentNodeId") == node_id)
            states[name(node_id)] = (int("".join(number.find("ua:Value", _NS).itertext())), ident(node_id))
        elif refs.get("HasTypeDefinition") == "i=2310":
            cause = refs.get("HasCause")
            transitions_[name(node_id)] = (
                name(refs["FromState"]),
                name(refs["ToState"]),
                name(cause) if cause else None,
                ident(node_id),
            )
    return states, transitions_, methods


def test_generated_module_matches_xml() -> None:
    states, transitions_, methods = _children_in_xml()

    assert SKILL_STATE_MACHINE_TYPE.type_id == SmartFactoryMachineSetNodeIds.SkillStateMachineType
    assert {s.name: (s.number, s.node_id.identifier) for s in SKILL_STATE_MACHINE_TYPE.states} == states
    assert {
        t.name: (t.source, t.target, t.cause, t.node_id.identifier) for t in SKILL_STATE_MACHINE_TYPE.transitions
    } == transitions_
    assert {m.name: m.node_id.identifier for m in SKILL_STATE_MACHINE_TYPE.methods} == methods

    all_ids = [
        *(s.node_id for s in SKILL_STATE_MACHINE_TYPE.states),
        *(t.node_id for t in SKILL_STATE_MACHINE_TYPE.transitions),
        *(m.node_id for m in SKILL_STATE_MACHINE_TYPE.methods),
    ]
    assert all(node_id.namespace_uri == _URI for node_id in all_ids)


def test_skill_state_matches_generated_states() -> None:
    assert {(s.value[1], s.id) for s in SkillState} == {(s.name, s.number) for s in SKILL_STATE_MACHINE_TYPE.states}


def test_skill_command_matches_generated_methods() -> None:
    assert {c.value for c in SkillCommand} == {m.name for m in SKILL_STATE_MACHINE_TYPE.methods}


def test_skill_command_names() -> None:
    assert C.HALT.browse_name == QualifiedName(namespace_uri=_URI, name="Halt")
    assert C.HALT.declaration_id == NodeIdDefinition(identifier=7014, namespace_uri=_URI)


def test_continuous_drops_only_completion() -> None:
    finite = set(transitions(finite=True))
    continuous = set(transitions(finite=False))
    completion = {S.COMPLETING, S.COMPLETED}

    assert continuous < finite
    assert all({t.source, t.target} & completion for t in finite - continuous)
    assert not any({t.source, t.target} & completion for t in continuous)


def test_transitions_from() -> None:
    assert {(t.target, t.cause) for t in transitions_from(S.RUNNING, finite=True)} == {
        (S.COMPLETING, None),
        (S.HALTING, C.HALT),
        (S.SUSPENDING, C.SUSPEND),
    }
    assert {(t.target, t.cause) for t in transitions_from(S.RUNNING, finite=False)} == {
        (S.HALTING, C.HALT),
        (S.SUSPENDING, C.SUSPEND),
    }


@pytest.mark.parametrize("finite", [True, False], ids=["finite", "continuous"])
def test_suspending_leads_only_to_suspended_or_halting(finite: bool) -> None:
    # as in PackML, a skill completes only from Running, never out of a suspend
    assert {(t.target, t.cause) for t in transitions_from(S.SUSPENDING, finite=finite)} == {
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
    expected = _ALLOWED_FINITE[state] - (set() if suspendable else {C.SUSPEND})
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
