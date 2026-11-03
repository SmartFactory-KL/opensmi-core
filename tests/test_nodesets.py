# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Tests that the generated nodeset modules match the shipped NodeSet2 XML files."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from importlib.resources import files

import pytest
from asyncua.ua import NodeId

from opensmi.core.nodesets import NODE_SETS
from opensmi.core.ua import NodeIdDefinition

_NS = {"ua": "http://opcfoundation.org/UA/2011/03/UANodeSet.xsd"}
_TYPE_TAGS = ("UAObjectType", "UADataType", "UAVariableType")


def _types_in_xml(file_name: str) -> tuple[str, dict[str, int | str]]:
    """Return the model URI and ``{browse name: identifier}`` of all types in the XML."""
    root = ET.fromstring(files("opensmi.core.nodesets").joinpath(file_name).read_text(encoding="utf-8"))
    model = root.find("ua:Models/ua:Model", _NS)
    assert model is not None
    types: dict[str, int | str] = {}
    for tag in _TYPE_TAGS:
        for node in root.iterfind(f"ua:{tag}", _NS):
            name = node.attrib["BrowseName"].split(":")[-1]
            types.setdefault(name, NodeId.from_string(node.attrib["NodeId"]).Identifier)
    return model.attrib["ModelUri"], types


@pytest.mark.parametrize("namespace", NODE_SETS.values(), ids=lambda ns: ns.__name__)
def test_xml_is_package_data(namespace):
    assert files("opensmi.core.nodesets").joinpath(namespace.FILE_NAME).is_file()


@pytest.mark.parametrize(("uri", "namespace"), NODE_SETS.items(), ids=lambda v: getattr(v, "__name__", ""))
def test_constants_match_xml(uri, namespace):
    model_uri, types = _types_in_xml(namespace.FILE_NAME)
    constants = {name: value for name, value in vars(namespace).items() if isinstance(value, NodeIdDefinition)}

    assert namespace.URI == uri == model_uri
    assert constants
    assert {name: c.identifier for name, c in constants.items()} == types
    assert all(c.namespace_uri == uri for c in constants.values())
