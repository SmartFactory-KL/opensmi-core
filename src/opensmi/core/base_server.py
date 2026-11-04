# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Base class for both client `RemoteServer` and server `Server`."""

from __future__ import annotations

from typing import Generic, TypeVar
from weakref import WeakValueDictionary

import structlog
from asyncua import ua

from opensmi.core.base_ua_object import BaseUaObject
from opensmi.core.paths import ObjectPath
from opensmi.core.protocols import NamespaceProvider
from opensmi.core.ua import NodeIdDefinition, QualifiedName

_LOGGER = structlog.get_logger("opensmi." + __name__)

_UaObjectType = TypeVar("_UaObjectType", bound=BaseUaObject)


class BaseServer(Generic[_UaObjectType]):
    """Base class for both client `RemoteServer` and server `Server`."""

    def __init__(self, **kwargs) -> None:
        """*Cooperative* constructor."""
        super().__init__(**kwargs)

        self._ua_objects: WeakValueDictionary[ua.NodeId, _UaObjectType] = WeakValueDictionary()
        """Maps OPC UA nodes to UaObjects with weak references."""
        self._ua_objects_by_path: WeakValueDictionary[ObjectPath, _UaObjectType] = WeakValueDictionary()
        """Maps canonical paths and aliases to UaObjects with weak references."""
        self._namespace_map: dict[str, int] = {}

    def resolve(self, path: ObjectPath | str) -> _UaObjectType:
        """Return the object at ``path``, its canonical path or one of its aliases.

        :raises KeyError: If no object has this path.
        :raises ValueError: If ``path`` is a ``str`` that is no valid path.
        """
        return self._ua_objects_by_path[ObjectPath.of(path)]

    def resolve_optional(self, path: ObjectPath | str) -> _UaObjectType | None:
        """Return the object at ``path``, its canonical path or one of its aliases, or ``None``.

        :raises ValueError: If ``path`` is a ``str`` that is no valid path.
        """
        return self._ua_objects_by_path.get(ObjectPath.of(path))

    def find(self, pattern: str) -> list[_UaObjectType]:
        """Return all objects whose canonical path matches the glob ``pattern`` (see `ObjectPath.match`), in tree order.

        :raises ValueError: If ``pattern`` is no valid pattern.
        """
        found = [
            (path, ua_object)
            for path, ua_object in list(self._ua_objects_by_path.items())
            if path == ua_object.path and path.match(pattern)
        ]
        return [ua_object for _, ua_object in sorted(found, key=lambda item: item[0])]

    def get_ua_object(self, ua_node_id: ua.NodeId) -> _UaObjectType:
        """Return the ``UaObject`` which corresponds to the given ``ua_node``.

        :raises KeyError: If no ``UaObject`` is found.
        """
        return self._ua_objects[ua_node_id]

    def get_ua_object_optional(self, ua_node_id: ua.NodeId) -> _UaObjectType | None:
        """Return the ``UaObject`` which corresponds to the given ``ua_node`` or ``None``."""
        return self._ua_objects.get(ua_node_id, default=None)

    def register_ua_object(self, ua_object: _UaObjectType) -> None:
        """Register the given ``UaObject`` to the server, by node and by its canonical path and aliases.

        Objects register top-down: the path is taken now, so the parent must already be registered and can't change
        anymore (`BaseUaObject._set_parent`).

        :raises RuntimeError: If the object has a parent that isn't registered.
        """
        assert ua_object is not None
        assert isinstance(ua_object.ua_node.nodeid, ua.NodeId)

        parent = ua_object._parent  # noqa: SLF001  the public getter may refuse an unset parent
        if parent is not None and (
            parent._ua_node is None  # noqa: SLF001
            or self._ua_objects.get(parent._ua_node.nodeid) is not parent  # noqa: SLF001
        ):
            msg = f"Cannot register {ua_object!r} at {ua_object.path}: its parent {parent!r} isn't registered yet"
            raise RuntimeError(msg)

        self._ua_objects[ua_object.ua_node.nodeid] = ua_object
        for path in (ua_object.path, *ua_object.aliases):
            self._register_path(path, ua_object)

    def unregister_ua_object(self, ua_object: _UaObjectType) -> None:
        """Unregister the given ``UaObject`` from the server, by node and by its canonical path and aliases."""
        assert ua_object is not None
        assert isinstance(ua_object.ua_node.nodeid, ua.NodeId)

        _ = self._ua_objects.pop(ua_object.ua_node.nodeid)
        for path in (ua_object.path, *ua_object.aliases):
            if self._ua_objects_by_path.get(path) is ua_object:
                del self._ua_objects_by_path[path]

    def _register_path(self, path: ObjectPath, ua_object: _UaObjectType) -> None:
        """Map ``path`` to ``ua_object``; a path already taken by another object keeps that object."""
        existing = self._ua_objects_by_path.get(path)
        if existing is not None and existing is not ua_object:
            _LOGGER.error("Path already registered, keeping the first object", path=str(path), existing=repr(existing))
            return
        self._ua_objects_by_path[path] = ua_object

    def _clear_ua_objects(self) -> None:
        """Forget all registered objects, by node and by path (e.g. before a client browses again)."""
        self._ua_objects.clear()
        self._ua_objects_by_path.clear()

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
