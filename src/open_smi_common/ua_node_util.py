# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Utility functions for ``ua.Node``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import structlog.stdlib
from asyncua import ua
from asyncua.common.node import Node
from asyncua.ua import QualifiedName
from asyncua.ua.uaerrors import BadTypeMismatch

from open_smi_common import Unit

NULL_NODE_ID = ua.NodeId()
""" This node id indicates an invalid Node ID and should be treated as 'None'. """


async def read_value(node: Node) -> Any:
    """Read the value of the given node and transforms the NULL_NODE_ID into None."""
    value = await node.read_value()
    if isinstance(value, ua.NodeId) and value.is_null():
        return None
    return value


# async def read_all_variables(location: Node) -> dict[str, Any]:
#     """Return all variables of the given node in dictionary form."""
#     assert location is not None
#
#     ret = {}
#     for node in await location.get_children():
#         name, value = await asyncio.gather(node.read_browse_name(), node.read_value())
#         ret[str(name.Name)] = value
#     return ret


async def _write_value(node: Node, value: Any, *, variant_type: ua.VariantType) -> None:
    # convert node id string to NodeId, this is not done automatically by asyncua
    if variant_type == ua.VariantType.NodeId and isinstance(value, str):
        if value == "":
            await node.write_value(NULL_NODE_ID)
        else:
            await node.write_value(ua.NodeId.from_string(value))
    elif variant_type == ua.VariantType.NodeId and value is None:
        await node.write_value(NULL_NODE_ID)  # we cannot write None here, it needs to be an (invalid) node id instead!
    elif variant_type == ua.VariantType.LocalizedText and isinstance(value, str):
        # just writing the raw string does not fail immediately in asyncua, but later when a client tries to read it.
        await node.write_value(ua.LocalizedText(value, "en-US"))
    else:
        await node.write_value(value, variant_type)


async def write_value(node: Node, value: Any, *, variant_type: ua.VariantType | None = None) -> None:
    """Write the given value to the given node. Will try to use existing variant type of the node."""
    # Note: asyncua is very strict, e.g. float is not automatically cast to double and trying to write that will fail!
    try:
        if isinstance(value, ua.Variant):
            await _write_value(node, value, variant_type=value.VariantType)
        if variant_type is not None:
            await _write_value(node, value, variant_type=variant_type)
        else:
            # we need to figure out the correct variant type to use ourselves
            data_value_value = (await node.read_data_value()).Value
            if data_value_value is None:
                await node.write_value(value)  # try without variant type, might fail
            else:
                await _write_value(node, value, variant_type=data_value_value.VariantType)
    except BadTypeMismatch as err:  # the exception has 0 useful information on its own
        expected_variant_type = await node.read_data_type_as_variant_type()
        err.add_note(f"{node=}")
        err.add_note(f"Expected variant_type={expected_variant_type!r}")
        err.add_note(f"Given {value=!r} ; {variant_type=!r}")
        raise


# async def get_all_variables_with_browse_name(node: Node) -> dict[str, Node]:
#     """Gather all child variables for given node and store them in a dict."""
#     node_dict = {}
#     for child in await node.get_variables():
#         node_dict[str((await child.read_browse_name()).Name)] = child
#     return node_dict


@dataclass(slots=True)
class PropertiesResult:
    """Results of ``get_unit_and_range()``."""

    unit: ua.EUInformation | None = None
    range: ua.Range | None = None


async def get_properties(node: Node, *, logger: structlog.stdlib.BoundLogger | None = None) -> PropertiesResult:
    """Retrieve the supported OPC UA properties of the given node."""
    assert node is not None, "No node given!"
    result = PropertiesResult()

    for property_node in await node.get_properties():
        property_browse_name_data_value, property_value_data_value = await property_node.read_attributes(
            [ua.attribute_ids.AttributeIds.BrowseName, ua.attribute_ids.AttributeIds.Value]
        )
        property_name: str = property_browse_name_data_value.Value.Value.Name  # type: ignore
        property_value = property_value_data_value.Value.Value  # type: ignore

        if property_name == "EngineeringUnits" and isinstance(property_value, ua.EUInformation):
            if logger is not None:
                logger.debug("Found EngineeringUnits", unit=property_value)
            result.unit = property_value
        elif property_name == "EURange" and isinstance(property_value, ua.Range):
            if logger is not None:
                logger.debug("Found EURange", range=property_value)
            result.range = property_value
        elif logger is not None:
            logger.warning(
                "Found unsupported property, ignoring!",
                ua_property_node_id=property_node.nodeid.to_string(),
                ua_node_id=node.nodeid.to_string(),
            )

    return result


async def get_type_definition(ua_node: Node) -> str:
    """Return the browse name of the OPC UA type definition of the given node."""
    try:
        type_definition_list = await ua_node.get_references(
            ua.object_ids.ObjectIds.HasTypeDefinition,
            ua.BrowseDirection.Forward,
        )
        return type_definition_list[0].BrowseName.Name
    except Exception as ex:
        msg = f"Could not find type definition for node {ua_node.nodeid.to_string()}!"
        raise RuntimeError(msg) from ex


def get_node_id(
    ua_location: Node | ua.NodeId,
    *,
    name: QualifiedName | str,
    ns_idx: int | None = 1,
) -> ua.NodeId:
    """Return a (new) Node ID in the standard hierarchical format based on given parameters.

    :param ua_location: OPC UA parent node in the hierarchy
    :param name: (Browse)Name of the new Node ID.
    :param ns_idx: (optional) OPC UA namespace index, if ``None``, the namespace index of the location node
        id will be used.
    """
    assert ua_location is not None, "No location node given!"
    if isinstance(ua_location, Node):
        ua_location = ua_location.nodeid
    assert isinstance(ua_location, ua.NodeId)

    if ns_idx is None:
        ns_idx = ua_location.NamespaceIndex

    if isinstance(name, QualifiedName):
        name = name.Name

    if isinstance(ua_location.Identifier, str):
        identifier = ua.String(f"{ua_location.Identifier!s}.{name}")
    else:
        identifier = ua.String(name)

    return ua.NodeId(Identifier=identifier, NamespaceIndex=ua.Int16(ns_idx))


async def get_child_without_ns(parent: Node, *, display_name: str) -> Node:
    """Return the first child node with given display name while ignoring the namespace index.

    :raises BadNoMatch: If no child with given display name exists.
    """
    for child in await parent.get_children():
        child_display_name = (await child.read_display_name()).Text
        # print(parent.nodeid.to_string(), display_name, child_display_name)
        if child_display_name == display_name:
            return child
    raise ua.uaerrors.BadNoMatch


async def write_range(node: Node, range_: tuple[float, float] | ua.Range) -> None:
    """Write given ``range`` to given ``node``."""
    assert node is not None, "No node given!"
    assert range_ is not None, "No range given!"

    if not isinstance(range_, ua.Range):
        range_ = ua.Range(*range_)

    ua_range_node = await node.get_child("0:EURange")
    await ua_range_node.write_value(range_)


async def write_unit(
    ua_node: Node, unit: Unit | str | int | ua.EUInformation, *, engineering_unit: str = "EngineeringUnits"
) -> None:
    """Write given ``unit`` to given ``node``."""
    assert ua_node is not None, "No node given!"
    assert unit is not None, "No unit given!"

    if isinstance(unit, Unit):
        unit = unit.ua_eu_information
    elif isinstance(unit, str):
        if unit == "%":  # backwards compatibility
            unit = "pct"
        unit = Unit.from_symbol(unit).ua_eu_information
    elif isinstance(unit, int):
        unit = Unit.from_ua_unit_id(unit).ua_eu_information

    assert isinstance(unit, ua.EUInformation)
    ua_engineering_unit_node = await ua_node.get_child(f"0:{engineering_unit}")
    await ua_engineering_unit_node.write_value(unit)


async def read_unit(ua_node: Node, *, engineering_unit: str = "EngineeringUnits") -> ua.EUInformation:
    """Read the engineering unit from the given node."""
    assert ua_node is not None, "No node given!"

    ua_engineering_unit_node = await ua_node.get_child(f"0:{engineering_unit}")
    unit = await ua_engineering_unit_node.read_value()

    assert isinstance(unit, ua.EUInformation), f"Expected EUInformation, got {type(unit).__name__}"

    return unit


async def get_children_browse_names(ua_node: Node) -> Mapping[Node, ua.QualifiedName]:
    """Return a mapping from child nodes to qualified names."""
    result = {}
    for ref in await ua_node.get_children_descriptions():
        node = Node(session=ua_node.session, nodeid=ref.NodeId)
        result[node] = ref.BrowseName

    return result
