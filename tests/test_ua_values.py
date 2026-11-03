# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Tests for the server-independent OPC UA value types and their asyncua conversions."""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from asyncua import ua
from asyncua.common.utils import Buffer
from asyncua.ua import ua_binary

from opensmi.core.base_server import BaseServer
from opensmi.core.ua import OPC_UA_NS, LocalizedText, NodeIdDefinition, QualifiedName

DI = "http://opcfoundation.org/UA/DI/"
MACHINE_SET = "http://smartfactory.de/UA/MachineSet"

IDENTIFIERS = [
    pytest.param(5, (ua.NodeIdType.TwoByte, ua.NodeIdType.FourByte, ua.NodeIdType.Numeric), id="numeric-small"),
    pytest.param(70000, (ua.NodeIdType.Numeric,), id="numeric"),
    pytest.param(ua.Int32(1015), (ua.NodeIdType.FourByte, ua.NodeIdType.Numeric), id="generated-int32"),
    pytest.param("Machines.M1", (ua.NodeIdType.String,), id="string"),
    pytest.param(uuid.UUID("09087e75-8e5e-499b-954f-f2a9603db28a"), (ua.NodeIdType.Guid,), id="guid"),
    pytest.param(b"\x01\x02", (ua.NodeIdType.ByteString,), id="opaque"),
]


# --------------------------------------------------------------------------- helpers


def server_with(*uris: str) -> BaseServer:
    """A bare ``BaseServer`` whose namespace array is ``[OPC_UA_NS, *uris]``."""
    server = BaseServer()
    server._namespace_map = {uri: idx for idx, uri in enumerate((OPC_UA_NS, *uris))}
    return server


# --------------------------------------------------------------------------- namespace URI by index


@pytest.mark.parametrize(("index", "uri"), [(0, OPC_UA_NS), (1, DI), (2, MACHINE_SET)])
def test_namespace_uri_by_index(index, uri):
    assert server_with(DI, MACHINE_SET).ua_get_namespace_uri(index) == uri


def test_namespace_uri_accepts_ua_int16():
    assert server_with(DI).ua_get_namespace_uri(ua.Int16(1)) == DI


def test_namespace_uri_and_index_are_inverse():
    server = server_with(DI, MACHINE_SET)

    for index in range(3):
        assert server.ua_get_namespace_index(server.ua_get_namespace_uri(index)) == index


def test_namespace_uri_depends_on_server():
    assert server_with(DI, MACHINE_SET).ua_get_namespace_uri(1) == DI
    assert server_with(MACHINE_SET, DI).ua_get_namespace_uri(1) == MACHINE_SET


@pytest.mark.parametrize("index", [3, -1, 32767])
def test_unknown_namespace_index_raises_key_error_for_uri(index):
    with pytest.raises(KeyError):
        server_with(DI, MACHINE_SET).ua_get_namespace_uri(index)


def test_appended_namespace_is_found_and_existing_indexes_keep_their_uri():
    server = server_with(DI)
    server._namespace_map[MACHINE_SET] = 2

    assert server.ua_get_namespace_uri(2) == MACHINE_SET
    assert server.ua_get_namespace_uri(1) == DI


def test_empty_namespace_map_raises_key_error():
    with pytest.raises(KeyError):
        BaseServer().ua_get_namespace_uri(0)


# --------------------------------------------------------------------------- NodeIdDefinition


@pytest.mark.parametrize(("identifier", "node_id_types"), IDENTIFIERS)
def test_node_id_definition_resolves_each_identifier_type(identifier, node_id_types):
    server = server_with(DI, MACHINE_SET)

    node_id = server.ua_get_node_id(NodeIdDefinition(identifier=identifier, namespace_uri=MACHINE_SET))

    assert node_id.NamespaceIndex == 2
    assert node_id.Identifier == identifier
    assert node_id.NodeIdType in node_id_types


@pytest.mark.parametrize(("identifier", "_"), IDENTIFIERS)
def test_node_id_definition_round_trips(identifier, _):
    server = server_with(DI, MACHINE_SET)
    definition = NodeIdDefinition(identifier=identifier, namespace_uri=MACHINE_SET)

    assert server.ua_to_node_id_definition(server.ua_get_node_id(definition)) == definition


def test_same_definition_from_servers_with_different_namespace_indexes():
    first, second = server_with(MACHINE_SET), server_with(DI, MACHINE_SET)

    from_first = first.ua_to_node_id_definition(ua.NodeId(1015, 1))
    from_second = second.ua_to_node_id_definition(ua.NodeId(1015, 2))

    assert from_first == from_second == NodeIdDefinition(identifier=1015, namespace_uri=MACHINE_SET)


def test_generated_int32_constant_equals_plain_int():
    generated = NodeIdDefinition(identifier=ua.Int32(1015), namespace_uri=MACHINE_SET)
    from_server = server_with(MACHINE_SET).ua_to_node_id_definition(ua.NodeId(1015, 1))

    assert generated == from_server
    assert hash(generated) == hash(from_server)
    assert len({generated, from_server}) == 1


def test_namespace_uri_defaults_to_ns0():
    definition = NodeIdDefinition(identifier=ua.object_ids.ObjectIds.BaseObjectType)

    assert definition.namespace_uri == OPC_UA_NS
    assert server_with().ua_get_node_id(definition) == ua.NodeId(ua.object_ids.ObjectIds.BaseObjectType, 0)


def test_ns0_node_id_converts_to_default_namespace():
    definition = server_with(DI).ua_to_node_id_definition(ua.NodeId(ua.object_ids.ObjectIds.BaseObjectType, 0))

    assert definition == NodeIdDefinition(identifier=ua.object_ids.ObjectIds.BaseObjectType)


@pytest.mark.parametrize("identifier", [-1, 2**32])
def test_numeric_identifier_must_fit_uint32(identifier):
    with pytest.raises(ValueError, match="identifier"):
        NodeIdDefinition(identifier=identifier, namespace_uri=MACHINE_SET)


def test_bool_identifier_must_raise_type_error():
    with pytest.raises(TypeError, match="identifier"):
        NodeIdDefinition(identifier=True, namespace_uri=MACHINE_SET)


def test_numeric_identifier_bounds_are_valid():
    NodeIdDefinition(identifier=0, namespace_uri=MACHINE_SET)
    NodeIdDefinition(identifier=2**32 - 1, namespace_uri=MACHINE_SET)


def test_unknown_namespace_uri_raises_key_error():
    with pytest.raises(KeyError):
        server_with(DI).ua_get_node_id(NodeIdDefinition(identifier=1015, namespace_uri=MACHINE_SET))


def test_unknown_namespace_index_raises_key_error():
    with pytest.raises(KeyError):
        server_with(DI).ua_to_node_id_definition(ua.NodeId(1015, 7))


def test_expanded_node_id_uses_its_namespace_uri():
    server = server_with(DI, MACHINE_SET)
    expanded = ua.ExpandedNodeId(Identifier=1015, NamespaceIndex=0, NamespaceUri=MACHINE_SET)

    assert server.ua_to_node_id_definition(expanded) == NodeIdDefinition(identifier=1015, namespace_uri=MACHINE_SET)


def test_expanded_node_id_on_other_server_raises():
    expanded = ua.ExpandedNodeId(Identifier=1015, NamespaceIndex=1, ServerIndex=1)

    with pytest.raises(ValueError, match="server"):
        server_with(MACHINE_SET).ua_to_node_id_definition(expanded)


# --------------------------------------------------------------------------- QualifiedName


def test_qualified_name_round_trips():
    server = server_with(DI, MACHINE_SET)
    name = QualifiedName(namespace_uri=MACHINE_SET, name="FeasibilityCheck")

    ua_name = server.ua_from_qualified_name(name)

    assert ua_name == ua.QualifiedName("FeasibilityCheck", 2)
    assert server.ua_to_qualified_name(ua_name) == name


def test_same_qualified_name_from_servers_with_different_namespace_indexes():
    first, second = server_with(MACHINE_SET), server_with(DI, MACHINE_SET)

    assert first.ua_to_qualified_name(ua.QualifiedName("Pick", 1)) == second.ua_to_qualified_name(
        ua.QualifiedName("Pick", 2)
    )


def test_qualified_name_unknown_namespace_uri_raises_key_error():
    with pytest.raises(KeyError):
        server_with().ua_from_qualified_name(QualifiedName(namespace_uri=MACHINE_SET, name="Pick"))


def test_qualified_name_unknown_namespace_index_raises_key_error():
    with pytest.raises(KeyError):
        server_with().ua_to_qualified_name(ua.QualifiedName("Pick", 4))


# --------------------------------------------------------------------------- LocalizedText


def test_localized_text_round_trips():
    text = LocalizedText(text="Greifer", locale="de-DE")

    ua_text = text.to_ua()

    assert ua_text == ua.LocalizedText(Text="Greifer", Locale="de-DE")
    assert LocalizedText.from_ua(ua_text) == text


@pytest.mark.parametrize(
    ("ua_text", "expected"),
    [
        (ua.LocalizedText(Text=None, Locale=None), LocalizedText(text="")),
        (ua.LocalizedText(Text="Gripper", Locale=None), LocalizedText(text="Gripper")),
        (ua.LocalizedText(Text=None, Locale="en"), LocalizedText(text="", locale="en")),
    ],
)
def test_localized_text_from_ua_maps_none_to_empty(ua_text, expected):
    assert LocalizedText.from_ua(ua_text) == expected


def test_localized_text_locale_defaults_to_unspecified():
    assert LocalizedText(text="Gripper").locale == ""
    assert LocalizedText(text="Gripper").to_ua().Locale is None


def test_localized_text_to_ua_is_encodable_by_asyncua():
    ua_text = LocalizedText(text="Greifer", locale="de").to_ua()

    assert ua.Variant(ua_text).VariantType == ua.VariantType.LocalizedText
    decoded = ua_binary.struct_from_binary(ua.LocalizedText, Buffer(ua_binary.struct_to_binary(ua_text)))
    assert decoded == ua_text


# --------------------------------------------------------------------------- shared properties


@pytest.mark.parametrize(
    "value",
    [
        NodeIdDefinition(identifier=1015, namespace_uri=MACHINE_SET),
        QualifiedName(namespace_uri=MACHINE_SET, name="Pick"),
        LocalizedText(text="Pick"),
    ],
)
def test_values_are_frozen_and_hashable(value):
    field = dataclasses.fields(value)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(value, field, "changed")
    assert value == value


@pytest.mark.parametrize("cls", [NodeIdDefinition, QualifiedName, LocalizedText])
def test_value_types_are_keyword_only(cls):
    with pytest.raises(TypeError):
        cls(MACHINE_SET, "Pick")
