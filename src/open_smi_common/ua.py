# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""OPC UA helper stuff."""

from dataclasses import dataclass

from asyncua import ua


@dataclass(frozen=True, slots=True, eq=True)
class NodeIdDefinition:
    """Definition of an unresolved OPC UA node."""

    ns_uri: str
    id: ua.Int32
