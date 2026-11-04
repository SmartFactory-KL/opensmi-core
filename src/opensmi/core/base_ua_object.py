# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Base class for all UA objects, both client- and server-side."""

from typing import TYPE_CHECKING, ClassVar, Generic, TypeVar

import structlog
from asyncua.common.node import Node
from structlog.stdlib import BoundLogger
from typing_extensions import deprecated

from opensmi.core.paths import ObjectPath, sanitize_segment

if TYPE_CHECKING:
    from opensmi.core.base_server import BaseServer

_ServerType = TypeVar("_ServerType", bound="BaseServer")


class BaseUaObject(Generic[_ServerType]):
    """Base class for all UA objects, both client- and server-side."""

    _parent: "BaseUaObject[_ServerType] | None" = None

    _folder: ClassVar[str | None] = None
    """OpenSMI folder between the parent and this object in the path, e.g. ``"SkillSet"``; ``None`` for none."""

    def __init__(
        self,
        *,
        name: str | None = None,
        segment: str | None = None,
        server: _ServerType | None = None,
        parent: "BaseUaObject[_ServerType] | None" = None,
        **kwargs,
    ) -> None:
        """*Cooperative* constructor.

        :param name: The name of the UA object, as on the server (may be empty on servers we don't control; the
            segment never is). Defaults to the class name.
        :param segment: The last segment of the object's path. Defaults to the sanitized ``name``; clients pass the
            unique segment from ``opensmi.core.paths.unique_segments()``.
        :param server: The associated server of the UA object. Note that there must be at least one non ``None`` in
            the hierarchy.
        :param parent: The parent of the UA object. Only Machines are allowed to have no parent. Can be set later before
            asynchronous initialization.
        """
        if name is None:
            name = self.__class__.__name__
        elif not isinstance(name, str):
            msg = f"Given name '{name}' is not valid!"
            raise TypeError(msg)

        self._name: str = name
        self._segment: str = sanitize_segment(name) if segment is None else segment
        _ = ObjectPath((self._segment,))  # check the segment early
        self._aliases: set[ObjectPath] = set()
        self._server: _ServerType | None = server
        self._ua_node: Node | None = None
        if parent is not None:
            self.parent = parent  # via setter to allow optional runtime type checking
        self._logger: structlog.BoundLogger = structlog.get_logger(f"opensmi.{self.__class__.__name__}", name=self.name)

        super().__init__(**kwargs)  # cooperative __init__() after we are done

    @property
    def ua_node(self) -> Node:
        """Return the internal OPC UA node."""
        if self._ua_node is not None:
            return self._ua_node

        msg = f"UA node of {self!r} is unknown, something went wrong!"
        raise RuntimeError(msg)

    @ua_node.setter
    def ua_node(self, ua_node: Node) -> None:
        """Set main OPC UA node to an existing node (due to XML import, etc.). Only possible once."""
        if self._ua_node is not None:
            msg = f"Main OPC UA node of {self!r} already exists!"
            raise RuntimeError(msg)

        self._ua_node = ua_node
        self.server.register_ua_object(self)

    @property
    def name(self) -> str:
        """Name of the object."""
        return self._name

    @property
    @deprecated("Use path instead")
    def full_name(self) -> str:
        if self.parent is not None:
            assert isinstance(self.parent, BaseUaObject)
            return f"{self.parent.full_name}/{self.name}"
        return f"/{self.name}"

    @property
    def path(self) -> ObjectPath:
        """Return the full path of the object: the parent's path, the OpenSMI folder (if any) and the segment."""
        base = ObjectPath()
        if self.parent is not None:
            assert isinstance(self.parent, BaseUaObject)
            base = self.parent.path
        if self._folder is not None:
            base /= self._folder
        return base / self._segment

    @property
    def aliases(self) -> frozenset[ObjectPath]:
        """Further paths of this object, e.g. of a variable also listed in other containers; ``path`` is canonical."""
        return frozenset(self._aliases)

    def _add_alias(self, path: ObjectPath) -> None:
        """Add ``path`` as a further path of this object; ``server.resolve()`` finds it once the object has a node."""
        self._aliases.add(path)
        if self._ua_node is not None:
            self.server._register_path(path, self)  # noqa: SLF001

    def resolve(self, relative: str) -> "BaseUaObject[_ServerType]":
        """Return the object at ``relative`` below this one, e.g. ``"Components/Gripper"``.

        :raises KeyError: If no object has this path.
        :raises ValueError: If ``relative`` starts with ``/`` or is no valid relative path.
        """
        return self.server.resolve(self._absolute(relative))

    def resolve_optional(self, relative: str) -> "BaseUaObject[_ServerType] | None":
        """Return the object at ``relative`` below this one, or ``None``.

        :raises ValueError: If ``relative`` starts with ``/`` or is no valid relative path.
        """
        return self.server.resolve_optional(self._absolute(relative))

    def find(self, pattern: str) -> "list[BaseUaObject[_ServerType]]":
        """Return all objects below this one whose path matches the relative glob ``pattern``, e.g. ``"**/SkillSet/*"``.

        :raises ValueError: If ``pattern`` starts with ``/`` or is no valid pattern.
        """
        self._check_relative(pattern)
        prefix = "".join(f"/{ObjectPath.escape(segment)}" for segment in self.path.segments)
        return [found for found in self.server.find(f"{prefix}/{pattern}") if found is not self]

    def _absolute(self, relative: str) -> ObjectPath:
        self._check_relative(relative)
        return ObjectPath((*self.path.segments, *relative.split("/")))

    @staticmethod
    def _check_relative(relative: str) -> None:
        if relative.startswith("/"):
            msg = f"Expected a path relative to this object, got an absolute one: {relative!r}"
            raise ValueError(msg)

    @property
    def logger(self) -> BoundLogger:
        """Logger associated with the `UaObject` instance."""
        return self._logger  # type: ignore

    @property
    def parent(self) -> "BaseUaObject[_ServerType] | None":
        """Return the untyped parent of the UA object."""
        return self._parent

    @parent.setter
    def parent(self, parent: "BaseUaObject[_ServerType]") -> None:
        """Set the parent of the UA object. Given ``parent`` must be an instance of `BaseUaObject`."""
        assert isinstance(parent, BaseUaObject)
        self._set_parent(parent)

    def _set_parent(self, parent: "BaseUaObject[_ServerType]") -> None:
        """Set the parent; subclasses overriding the ``parent`` setter call this instead of setting ``_parent``.

        :raises RuntimeError: If the object already has a node: its path is registered and must not change.
        """
        if self._ua_node is not None:
            msg = f"Cannot change the parent of {self!r}: its path {self.path} is already registered"
            raise RuntimeError(msg)
        self._parent = parent

    # TODO
    # @override
    # def _repr_items(self) -> Iterator[tuple[str, object]]:
    #     yield "name", self._name
    #     yield "ua_node", self._ua_node
    #     yield from super()._repr_items()

    @property
    def server(self) -> _ServerType:
        """Return the associated server."""
        if self._server is not None:
            return self._server

        parent = getattr(self, "parent", None)
        assert parent is not None

        server = getattr(parent, "server", None)
        assert server is not None

        self._server = server
        return server  # type: ignore

    @server.setter
    def server(self, server: _ServerType) -> None:
        self._server = server
