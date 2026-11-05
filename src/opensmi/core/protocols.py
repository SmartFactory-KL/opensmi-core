# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Shared Python protocols."""

from datetime import datetime
from typing import ClassVar, Protocol

from asyncua import ua


class UaEvent(Protocol):
    """OPC UA Event."""

    EventType: ua.NodeId
    Message: ua.LocalizedText
    Severity: int
    ErrorCode: str
    SourceName: str
    SourceNode: ua.NodeId
    Time: datetime
    emitting_node: ua.NodeId
    server_handle: int | None
    """Handle of the monitored item that delivered the event (set by asyncua's client subscription)."""


class NamespaceProvider(Protocol):
    """Protocol describing the metadata exposed by generated OPC UA namespace classes."""

    FILE_NAME: ClassVar[str]
    URI: ClassVar[str]
    VERSION: ClassVar[str]
    REQUIRED_URIS: ClassVar[tuple[str, ...]]
