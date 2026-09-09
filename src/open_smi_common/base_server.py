# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Base class for both client `RemoteServer` and server `Server`."""

from __future__ import annotations

from typing import Generic, TypeVar
from weakref import WeakValueDictionary

from asyncua import ua

from open_smi_common.base_ua_object import BaseUaObject
from open_smi_common.protocols import NamespaceProvider
from open_smi_common.ua import NodeIdDefinition

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

    def ua_get_node_id(self, identifier: NodeIdDefinition) -> ua.NodeId:
        """Return the complete OPC UA node ID for the given ``identifier``.

        :raises KeyError: If the namespace URI of the identifier is unknown.
        """
        return ua.NodeId(
            Identifier=identifier.id,
            NamespaceIndex=self.ua_get_namespace_index(identifier.ns_uri),
        )
