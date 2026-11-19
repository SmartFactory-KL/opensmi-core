# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""OpenSMI object paths and the rules for building them from OPC UA browse names.

Shared by everything that builds OpenSMI paths (server, client browsing, NodeSet loader, code generation), so the same
address space always yields the same paths.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from fnmatch import fnmatchcase
from functools import cache
from typing import Final

import structlog

from opensmi.core.ua import NodeIdDefinition

_LOGGER = structlog.get_logger("opensmi." + __name__)

_SEPARATOR: Final[str] = "/"
_REPLACEMENT: Final[str] = "_"
_ANY_DEPTH: Final[str] = "**"
_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"[A-Z][A-Za-z0-9]*")
_RESERVED_NAMES: Final[frozenset[str]] = frozenset({"True", "False", "None"})
_GLOB_SPECIAL: Final[re.Pattern[str]] = re.compile(r"([*?[])")


def check_segment(segment: str) -> None:
    """Check that ``segment`` can be a path segment: a non-empty ``str`` without ``/``.

    The hard rule for every name (browse names and usernames); the stricter naming rule is ``check_name()``.

    :raises TypeError: If ``segment`` is no ``str``.
    :raises ValueError: If ``segment`` is empty or contains ``/``.
    """
    if not isinstance(segment, str):
        msg = f"Path segment must be a str, not {type(segment).__name__}: {segment!r}"
        raise TypeError(msg)
    if not segment:
        msg = "Path segment must not be empty"
        raise ValueError(msg)
    if _SEPARATOR in segment:
        msg = f"Path segment must not contain '{_SEPARATOR}': {segment!r}"
        raise ValueError(msg)


def _split(text: str) -> tuple[str, ...]:
    if not text.startswith(_SEPARATOR):
        msg = f"Path must start with '{_SEPARATOR}': {text!r}"
        raise ValueError(msg)
    return () if text == _SEPARATOR else tuple(text[1:].split(_SEPARATOR))


@dataclass(frozen=True, slots=True, order=True)
class ObjectPath:
    """Path of an OpenSMI object, e.g. ``/M1/Components/Gripper/SkillSet/Pick``.

    A tuple of segments, never normalized: a segment is exactly what was put in. ``()`` is the root ``/``. Equal only to
    other ``ObjectPath`` objects, never to a ``str``; ordering follows the segments, which gives tree order.
    """

    segments: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Check the segments.

        :raises TypeError: If ``segments`` is no tuple of ``str``.
        :raises ValueError: If a segment is empty or contains ``/``.
        """
        if not isinstance(self.segments, tuple):
            msg = f"segments must be a tuple, not {type(self.segments).__name__}"
            raise TypeError(msg)
        for segment in self.segments:
            check_segment(segment)

    @classmethod
    def parse(cls, text: str) -> ObjectPath:
        """Parse ``"/M1/Components/Gripper"``; ``"/"`` is the root.

        :raises ValueError: If ``text`` doesn't start with ``/`` or has an empty segment (``//``, trailing ``/``).
        """
        return cls(_split(text))

    @classmethod
    def of(cls, path: ObjectPath | str) -> ObjectPath:
        """Return ``path`` as is, or parsed if it is a ``str``."""
        return path if isinstance(path, ObjectPath) else cls.parse(path)

    def __truediv__(self, segment: str) -> ObjectPath:
        """Return this path extended by ``segment``. The segment is checked, not sanitized."""
        return ObjectPath((*self.segments, segment))

    def __str__(self) -> str:
        """Return the path as text, e.g. ``"/M1/Components/Gripper"``."""
        return _SEPARATOR + _SEPARATOR.join(self.segments)

    @property
    def name(self) -> str:
        """Last segment; ``""`` for the root."""
        return self.segments[-1] if self.segments else ""

    @property
    def parent(self) -> ObjectPath:
        """Path without the last segment.

        :raises ValueError: For the root, which has no parent.
        """
        if not self.segments:
            msg = "The root path has no parent"
            raise ValueError(msg)
        return ObjectPath(self.segments[:-1])

    def is_relative_to(self, other: ObjectPath | str) -> bool:
        """Return whether this path is ``other`` or below it."""
        prefix = ObjectPath.of(other).segments
        return self.segments[: len(prefix)] == prefix

    def match(self, pattern: str) -> bool:
        """Return whether the whole path matches the glob ``pattern``, from the root to the last segment.

        Per segment, ``*``, ``?`` and ``[...]`` work as in ``fnmatch`` (case-sensitive); a ``**`` segment matches any
        number of segments, including none. Use ``escape()`` for segments taken literally.

        :raises ValueError: If ``pattern`` doesn't start with ``/`` or has an empty segment.
        """
        patterns = _split(pattern)
        for segment in patterns:
            check_segment(segment)
        segments = self.segments

        @cache
        def matches(i: int, j: int) -> bool:
            if j == len(patterns):
                return i == len(segments)
            if patterns[j] == _ANY_DEPTH:
                return any(matches(k, j + 1) for k in range(i, len(segments) + 1))
            return i < len(segments) and fnmatchcase(segments[i], patterns[j]) and matches(i + 1, j + 1)

        return matches(0, 0)

    @staticmethod
    def escape(segment: str) -> str:
        """Return ``segment`` as a glob pattern that matches only itself.

        ``*`` becomes ``[*]``, ``?`` becomes ``[?]`` and ``[`` becomes ``[[]``, as ``glob.escape()`` does.
        """
        return _GLOB_SPECIAL.sub(r"[\1]", segment)


def check_name(name: str) -> None:
    """Check ``name`` against the OpenSMI naming rule for browse names.

    Browse names of machines, components, resources, skills, checks, methods and variables match
    ``^[A-Z][A-Za-z0-9]*$`` and aren't ``True``, ``False`` or ``None``, so they are valid identifiers in common
    languages. Not enforced yet: opensmi-server warns and rejects from 1.0 on.

    Two kinds of names are exempt and only need to pass ``check_segment()``: usernames, and instances named from
    runtime data rather than the model (e.g. one object per diagnostic id or TF frame), which code generation never
    sees. DataType browse names are outside the rule. Foreign names such as ROS2's snake_case convert with
    ``to_pascal_case()``.

    :raises ValueError: If ``name`` breaks the rule.
    """
    if not _NAME_PATTERN.fullmatch(name):
        msg = f"Name must match ^[A-Z][A-Za-z0-9]*$: {name!r}"
        raise ValueError(msg)
    if name in _RESERVED_NAMES:
        msg = f"Name must not be one of {sorted(_RESERVED_NAMES)}: {name!r}"
        raise ValueError(msg)


def to_pascal_case(name: str) -> str:
    """Convert a snake_case name to PascalCase: split on ``_``, capitalize each part, join.

    Only the first letter of a part changes, the rest stays as is: ``child_frame_id`` → ``ChildFrameId``,
    ``max_vel_x`` → ``MaxVelX``, ``pose2d`` → ``Pose2d``. Empty parts (``__``, leading or trailing ``_``) vanish. The
    result is not checked, so pass it to ``check_name()``: ``none`` becomes the reserved ``None``, ``2d_pose`` becomes
    ``2dPose``, and two names may convert to the same one (``x_1`` and ``x1``).
    """
    return "".join(part[:1].upper() + part[1:] for part in name.split(_REPLACEMENT))


def sanitize_segment(browse_name: str) -> str:
    """Return the path segment for ``browse_name``: ``/`` replaced by ``_``, an empty name becomes ``_``."""
    return browse_name.replace(_SEPARATOR, _REPLACEMENT) or _REPLACEMENT


def node_id_order(node_id: NodeIdDefinition) -> tuple[str, int, int, str]:
    """Sort key independent of the server's namespace indexes: namespace URI, OPC UA identifier type, identifier."""
    identifier = node_id.identifier
    if isinstance(identifier, int):
        return node_id.namespace_uri, 0, identifier, ""
    if isinstance(identifier, str):
        return node_id.namespace_uri, 1, 0, identifier
    if isinstance(identifier, uuid.UUID):
        return node_id.namespace_uri, 2, 0, str(identifier)
    return node_id.namespace_uri, 3, 0, identifier.hex()


def unique_segments(siblings: Iterable[tuple[NodeIdDefinition, str]]) -> dict[NodeIdDefinition, str]:
    """Return a sanitized, unique path segment for each sibling, given as ``(node id, browse name)``.

    Siblings are processed in NodeId order (namespace URI, then identifier), so the result doesn't depend on browse
    order or namespace indexes. A segment already used gets the first free suffix ``_2``, ``_3``, ...; a suffixed
    segment never takes the unchanged segment of another sibling. Sanitized and suffixed segments are logged as
    warnings.
    """
    ordered = sorted(siblings, key=lambda sibling: node_id_order(sibling[0]))
    sanitized = [(node_id, name, sanitize_segment(name)) for node_id, name in ordered]
    reserved = {segment for _, _, segment in sanitized}

    result: dict[NodeIdDefinition, str] = {}
    used: set[str] = set()
    for node_id, name, segment in sanitized:
        if segment != name:
            _LOGGER.warning("Browse name is no valid path segment", browse_name=name, segment=segment)
        candidate, suffix = segment, 1
        while candidate in used or (candidate != segment and candidate in reserved):
            suffix += 1
            candidate = f"{segment}{_REPLACEMENT}{suffix}"
        if candidate != segment:
            _LOGGER.warning("Duplicate path segment", browse_name=name, segment=candidate, node_id=node_id)
        used.add(candidate)
        result[node_id] = candidate
    return result
