# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""OPC UA helper stuff."""

import uuid
from dataclasses import dataclass
from typing import Final, Self

from asyncua import ua

OPC_UA_NS: Final[str] = "http://opcfoundation.org/UA/"
_UINT32_MAX: Final[int] = 2**32 - 1


@dataclass(frozen=True, slots=True, kw_only=True)
class NodeIdDefinition:
    """Frozen definition of an unresolved OPC UA node."""

    identifier: int | str | uuid.UUID | bytes
    namespace_uri: str = OPC_UA_NS

    def __post_init__(self) -> None:
        """Check that a numeric identifier fits OPC UA's UInt32.

        :raises ValueError: If ``identifier`` is a ``bool`` or a number outside 0..2**32-1.
        """
        if isinstance(self.identifier, bool):  # bool is an int subclass; True would become i=1
            msg = f"identifier must not be a bool: {self.identifier!r}"
            raise TypeError(msg)
        if isinstance(self.identifier, int) and not 0 <= self.identifier <= _UINT32_MAX:
            msg = f"numeric identifier must be in 0..{_UINT32_MAX}: {self.identifier}"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True, kw_only=True)
class QualifiedName:
    """Frozen OPC UA qualified name, but with namespace URI instead of namespace index."""

    namespace_uri: str
    name: str


@dataclass(frozen=True, slots=True, kw_only=True)
class LocalizedText:
    """Frozen OPC UA localized text."""

    text: str
    locale: str = ""

    @classmethod
    def from_ua(cls, value: ua.LocalizedText) -> Self:
        """Convert from asyncua."""
        return cls(text=value.Text or "", locale=value.Locale or "")

    def to_ua(self) -> ua.LocalizedText:
        """Convert to asyncua."""
        return ua.LocalizedText(Text=self.text, Locale=self.locale or None)
