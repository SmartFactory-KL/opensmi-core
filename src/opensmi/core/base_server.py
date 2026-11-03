# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Base class for both client `RemoteServer` and server `Server`."""

from __future__ import annotations

from typing import Generic, TypeVar
from weakref import WeakValueDictionary

from asyncua import ua

from opensmi.core.base_ua_object import BaseUaObject
from opensmi.core.protocols import NamespaceProvider
from opensmi.core.ua import NodeIdDefinition, QualifiedName

_UaObjectType = TypeVar("_UaObjectType", bound=BaseUaObject)


class BaseServer(Generic[_UaObjectType]):
    """Base class for both client `RemoteServer` and server `Server`."""

    def __init__(self, **kwargs) -> None:
        """*Cooperative* constructor."""
        super().__init__(**kwargs)

        self._ua_objects: WeakValueDictionary[ua.NodeId, _UaObjectType] = WeakValueDictionary()
        """Maps OPC UA nodes to UaObjects with weak references."""
        self._namespace_map: dict[str, int] = {}

    def get_ua_object(self, ua_node_id: ua.NodeId) -> _UaObjectType:
        """Return the ``UaObject`` which corresponds to the given ``ua_node``.

        :raises KeyError: If no ``UaObject`` is found.
        """
        return self._ua_objects[ua_node_id]

    def get_ua_object_optional(self, ua_node_id: ua.NodeId) -> _UaObjectType | None:
        """Return the ``UaObject`` which corresponds to the given ``ua_node`` or ``None``."""
        return self._ua_objects.get(ua_node_id, default=None)

    def register_ua_object(self, ua_object: _UaObjectType) -> None:
        """Register the given ``UaObject`` to the server."""
        assert ua_object is not None
        assert isinstance(ua_object.ua_node.nodeid, ua.NodeId)

        self._ua_objects[ua_object.ua_node.nodeid] = ua_object

    def unregister_ua_object(self, ua_object: _UaObjectType) -> None:
        """Unregister the given ``UaObject`` from the server."""
        assert ua_object is not None
        assert isinstance(ua_object.ua_node.nodeid, ua.NodeId)

        _ = self._ua_objects.pop(ua_object.ua_node.nodeid)

    def ua_get_namespace_index(self, uri: str | type[NamespaceProvider]) -> ua.Int16:
        """Return the namespace index for the given namespace ``uri``.

        :raises KeyError: If the namespace URI is unknown.
        """
        if not isinstance(uri, str):
            uri = uri.URI

        return ua.Int16(self._namespace_map[uri])

    def ua_get_namespace_uri(self, index: int) -> str:
        """Return the namespace URI for the given namespace ``index``.

        :raises KeyError: If the server has no namespace at ``index``.
        """
        for uri, ns_index in self._namespace_map.items():
            if ns_index == index:
                return uri
        raise KeyError(index)

    def ua_get_node_id(self, definition: NodeIdDefinition) -> ua.NodeId:
        """Return the complete OPC UA node ID for the given ``definition``.

        :raises KeyError: If the namespace URI of the definition is unknown.
        """
        return ua.NodeId(
            Identifier=definition.identifier,  # pyright: ignore[reportArgumentType]
            NamespaceIndex=self.ua_get_namespace_index(definition.namespace_uri),
        )

    def ua_to_node_id_definition(self, node_id: ua.NodeId) -> NodeIdDefinition:
        """Convert the given node ID to a node ID definition.

        An ``ua.ExpandedNodeId`` uses its ``NamespaceUri`` if set.

        :raises KeyError: If the namespace index is unknown.
        :raises ValueError: If an ``ua.ExpandedNodeId`` points to another server.
        """
        namespace_uri = None
        if isinstance(node_id, ua.ExpandedNodeId):
            if node_id.ServerIndex:
                msg = f"{node_id.to_string()} is on another server (ServerIndex {node_id.ServerIndex})"
                raise ValueError(msg)
            namespace_uri = node_id.NamespaceUri
        return NodeIdDefinition(
            identifier=node_id.Identifier,
            namespace_uri=namespace_uri or self.ua_get_namespace_uri(node_id.NamespaceIndex),
        )

    def ua_to_qualified_name(self, qualified_name: ua.QualifiedName) -> QualifiedName:
        """Convert `ua.QualifiedName` to our `QualifiedName`."""
        return QualifiedName(
            namespace_uri=self.ua_get_namespace_uri(qualified_name.NamespaceIndex), name=qualified_name.Name
        )

    def ua_from_qualified_name(self, qualified_name: QualifiedName) -> ua.QualifiedName:
        """Convert from our `QualifiedName` to  `ua.QualifiedName`."""
        return ua.QualifiedName(
            Name=qualified_name.name, NamespaceIndex=self.ua_get_namespace_index(qualified_name.namespace_uri)
        )
