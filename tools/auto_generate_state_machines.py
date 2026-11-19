# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Generate Python modules with the states, transitions and methods of OPC UA state machine types.

Reads ``state_machines.toml`` in the nodeset directory, which lists the state machine types to generate::

    [[state_machine]]
    file = "Opc.Ua.SmartFactory.MachineSet.NodeSet2.xml"  # NodeSet2 file in the same directory
    type = "SkillStateMachineType"  # browse name of the type, without namespace
    module = "skill_state_machine"  # module written next to the file
    constant = "SKILL_STATE_MACHINE_TYPE"  # name of the StateMachineTypeDefinition in the module

Only states, transitions and methods declared by the type itself are read. A type whose transitions refer to states
or methods it does not declare (inherited from another state machine type, or in another nodeset) is rejected.
Defaults to core's own nodesets; other packages pass their directory, e.g.
``python tools/auto_generate_state_machines.py ../sfkl/src/opensmi/sfkl/nodesets``.
"""

import argparse
import logging
import sys
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Final

from _nodeset_xml import UA_NS, check, local_name, namespace_uris, node_id_definition_source

TOOLS_PATH: Final[Path] = Path(__file__).resolve().parent
NODESET_PATH: Final[Path] = TOOLS_PATH.parent / "src" / "opensmi" / "core" / "nodesets"
TEMPLATE: Final[Template] = Template((TOOLS_PATH / "state_machine.py.template").read_text(encoding="utf-8"))
MANIFEST_NAME: Final[str] = "state_machines.toml"
STATE_TYPE: Final[str] = "i=2307"
TRANSITION_TYPE: Final[str] = "i=2310"

logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger(__name__)


class GenerationError(Exception):
    """The state machine type cannot be generated from the NodeSet2 file."""


@dataclass(frozen=True)
class _Entry:
    file: str
    type: str
    module: str
    constant: str


def _read_manifest(path: Path) -> list[_Entry]:
    with path.open("rb") as file:
        manifest = tomllib.load(file)
    return [_Entry(**entry) for entry in manifest.get("state_machine", [])]


def _browse_name(node: ET.Element) -> str:
    return node.attrib["BrowseName"].split(":")[-1]


def _forward_references(node: ET.Element) -> dict[str, str]:
    refs = node.find(f"{UA_NS}References")
    if refs is None:
        return {}
    return {
        ref.attrib["ReferenceType"]: (ref.text or "").strip()
        for ref in refs
        if ref.attrib.get("IsForward", "true") == "true"
    }


def _state_number(nodes: dict[str, ET.Element], state: ET.Element) -> int:
    raw = state.attrib["NodeId"]
    number = next(
        (n for n in nodes.values() if n.attrib.get("ParentNodeId") == raw and _browse_name(n) == "StateNumber"), None
    )
    value = number.find(f"{UA_NS}Value") if number is not None else None
    if value is None:
        msg = f"state {_browse_name(state)!r} has no StateNumber value"
        raise GenerationError(msg)
    return int("".join(value.itertext()).strip())


def _render(entry: _Entry, xml_path: Path) -> str:
    root = ET.parse(xml_path).getroot()
    uris = namespace_uris(root)
    model = root.find(f"{UA_NS}Models/{UA_NS}Model")
    if model is None:
        msg = f"{xml_path.name} has no model"
        raise GenerationError(msg)
    model_uri = model.attrib["ModelUri"]
    nodes = {node.attrib["NodeId"]: node for node in root if "NodeId" in node.attrib}

    def node_id(raw: str) -> str:
        return node_id_definition_source(raw, uris, {model_uri: "URI"})

    type_node = next(
        (n for n in nodes.values() if local_name(n) == "UAObjectType" and _browse_name(n) == entry.type), None
    )
    if type_node is None:
        msg = f"{xml_path.name} has no object type {entry.type!r}"
        raise GenerationError(msg)
    type_id = type_node.attrib["NodeId"]
    children = {raw: node for raw, node in nodes.items() if node.attrib.get("ParentNodeId") == type_id}

    states: list[tuple[int, str, str]] = []
    transitions: list[tuple[str, str, str, str | None, str]] = []
    methods: list[tuple[str, str]] = []

    def declared(raw: str, kind: str, transition: str) -> str:
        if raw not in children:
            msg = f"{kind} {raw} of transition {transition!r} is not declared by the type"
            raise GenerationError(msg)
        return _browse_name(children[raw])

    for raw, node in children.items():
        refs = _forward_references(node)
        if local_name(node) == "UAMethod":
            methods.append((_browse_name(node), raw))
        elif refs.get("HasTypeDefinition") == STATE_TYPE:
            states.append((_state_number(nodes, node), _browse_name(node), raw))
        elif refs.get("HasTypeDefinition") == TRANSITION_TYPE:
            name = _browse_name(node)
            cause = refs.get("HasCause")
            transitions.append(
                (
                    name,
                    declared(refs["FromState"], "FromState", name),
                    declared(refs["ToState"], "ToState", name),
                    declared(cause, "HasCause", name) if cause else None,
                    raw,
                )
            )

    # trailing commas keep one argument per line after formatting
    return TEMPLATE.substitute(
        type_name=entry.type,
        file_name=entry.file,
        uri=model_uri,
        constant=entry.constant,
        type_id=node_id(type_id),
        states="\n".join(
            f"StateDefinition(name={name!r}, number={number}, node_id={node_id(raw)},),"
            for number, name, raw in sorted(states)
        ),
        transitions="\n".join(
            f"TransitionDefinition(name={name!r}, source={source!r}, target={target!r}, cause={cause!r}, "
            f"node_id={node_id(raw)},),"
            for name, source, target, cause, raw in sorted(transitions)
        ),
        methods="\n".join(
            f"MethodDefinition(name={name!r}, node_id={node_id(raw)},)," for name, raw in sorted(methods)
        ),
    )


def main() -> None:  # noqa: D103
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=NODESET_PATH,
        help=f"directory with the *.NodeSet2.xml files and {MANIFEST_NAME}",
    )
    out_path: Path = parser.parse_args().path.resolve()

    manifest = out_path / MANIFEST_NAME
    if not manifest.is_file():
        _LOGGER.error("No %s in '%s', nothing to generate!", MANIFEST_NAME, out_path)
        sys.exit(1)

    for entry in _read_manifest(manifest):
        _LOGGER.info("Processing state machine '%s' in '%s'...", entry.type, entry.file)
        try:
            source = _render(entry, out_path / entry.file)
        except GenerationError as error:
            _LOGGER.error("%s: %s", entry.type, error)  # noqa: TRY400 - the message says it all, no traceback
            sys.exit(1)
        path = out_path / f"{entry.module}.py"
        path.write_text(source, encoding="utf-8")
        check(path)


if __name__ == "__main__":
    main()
