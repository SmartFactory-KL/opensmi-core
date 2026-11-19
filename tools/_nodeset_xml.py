# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Helpers shared by the generators that read OPC UA NodeSet2 XML files."""

import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Final

from asyncua.ua import NodeId

OPC_UA_URI: Final[str] = "http://opcfoundation.org/UA/"
UA_NS: Final[str] = "{http://opcfoundation.org/UA/2011/03/UANodeSet.xsd}"
"""XML namespace of NodeSet2 elements, as an ``ElementTree`` tag prefix."""


def local_name(node: ET.Element) -> str:
    """Return the tag of ``node`` without its XML namespace."""
    return node.tag.rsplit("}", 1)[-1]


def namespace_uris(root: ET.Element) -> list[str]:
    """Return the namespace URIs of a NodeSet2 file, indexed like the namespace indexes in its NodeIds."""
    return [OPC_UA_URI] + [(uri.text or "").strip() for uri in root.iterfind(f"{UA_NS}NamespaceUris/{UA_NS}Uri")]


def node_id_definition_source(raw_node_id: str, uris: list[str], uri_constants: dict[str, str]) -> str:
    """Return Python source creating the ``NodeIdDefinition`` of a NodeId string from a NodeSet2 file.

    :param uris: the file's namespace URIs, see `namespace_uris`.
    :param uri_constants: names of constants to use in place of a literal namespace URI.
    """
    node_id = NodeId.from_string(raw_node_id)
    uri = uris[node_id.NamespaceIndex]
    return f"NodeIdDefinition(identifier={node_id.Identifier!r}, namespace_uri={uri_constants.get(uri, repr(uri))})"


def check(path: Path) -> None:
    """Format and lint a generated module, and make sure it is valid Python."""
    subprocess.run([sys.executable, "-m", "ruff", "format", str(path)], check=True)
    subprocess.run([sys.executable, "-m", "ruff", "check", "--fix", str(path)], check=True)
    subprocess.run([sys.executable, "-m", "ruff", "format", str(path)], check=True)

    compile(path.read_text(encoding="utf-8"), path, "exec")
