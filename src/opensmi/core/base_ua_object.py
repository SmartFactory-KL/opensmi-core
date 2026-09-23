# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Base class for all UA objects, both client- and server-side."""

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Generic, TypeVar

import structlog
from asyncua.common.node import Node
from structlog.stdlib import BoundLogger
from typing_extensions import deprecated

if TYPE_CHECKING:
    from opensmi.core.base_server import BaseServer

_ServerType = TypeVar("_ServerType", bound="BaseServer")


class BaseUaObject(Generic[_ServerType]):
    """Base class for all UA objects, both client- and server-side."""

    _parent: "BaseUaObject[_ServerType] | None" = None

    def __init__(
        self,
        *,
        name: str | None = None,
        server: _ServerType | None = None,
        parent: "BaseUaObject[_ServerType] | None" = None,
        **kwargs,
    ) -> None:
        """*Cooperative* constructor.

        :param name: The name of the UA object. Defaults to the class name.
        :param server: The associated server of the UA object. Note that there must be at least one non ``None`` in
            the hierarchy.
        :param parent: The parent of the UA object. Only Machines are allowed to have no parent. Can be set later before
            asynchronous initialization.
        """
        if name is None:
            name = self.__class__.__name__
        elif not isinstance(name, str) or name == "":
            msg = f"Given name '{name}' is not valid!"
            raise TypeError(msg)

        self._name: str = name
        self._server: _ServerType | None = server
        if parent is not None:
            self.parent = parent  # via setter to allow optional runtime type checking
        self._ua_node: Node | None = None
        self._logger: structlog.BoundLogger = structlog.get_logger(
            f"opensmi.{self.__class__.__name__}", name=self.name
        )

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
    def path(self) -> PurePosixPath:
        """Return the full path of the object."""
        if self.parent is not None:
            assert isinstance(self.parent, BaseUaObject)
            return self.parent.path / self.name
        return PurePosixPath("/") / self.name

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
