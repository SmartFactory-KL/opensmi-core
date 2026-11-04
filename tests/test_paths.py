# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Tests for the path segment rules."""

from __future__ import annotations

import uuid

import pytest
from structlog.testing import capture_logs

from opensmi.core.paths import sanitize_segment, unique_segments
from opensmi.core.ua import NodeIdDefinition

NS = "http://example.com/UA/"
OTHER_NS = "http://example.com/UA/Other/"


def nid(identifier: int | str | uuid.UUID | bytes, namespace_uri: str = NS) -> NodeIdDefinition:
    return NodeIdDefinition(identifier=identifier, namespace_uri=namespace_uri)


# --------------------------------------------------------------------------- sanitize_segment


@pytest.mark.parametrize(
    ("browse_name", "segment"),
    [
        ("Pick", "Pick"),
        ("Pick/Place", "Pick_Place"),
        ("/a//b/", "_a__b_"),
        ("Grip per.ä-1 ", "Grip per.ä-1 "),
        ("", "_"),
    ],
)
def test_sanitize_segment_replaces_only_the_separator(browse_name, segment):
    assert sanitize_segment(browse_name) == segment


# --------------------------------------------------------------------------- unique_segments


def test_unique_names_are_kept():
    assert unique_segments([(nid(2), "Place"), (nid(1), "Pick")]) == {nid(1): "Pick", nid(2): "Place"}


def test_empty_input():
    assert unique_segments([]) == {}


def test_duplicates_get_suffixes_in_node_id_order():
    result = unique_segments([(nid(30), "Pick"), (nid(10), "Pick"), (nid(20), "Pick")])

    assert result == {nid(10): "Pick", nid(20): "Pick_2", nid(30): "Pick_3"}


def test_numeric_identifiers_sort_numerically():
    result = unique_segments([(nid(10), "Pick"), (nid(9), "Pick")])

    assert result == {nid(9): "Pick", nid(10): "Pick_2"}


def test_order_does_not_depend_on_input_order():
    siblings = [(nid(1), "A"), (nid("b"), "A"), (nid(2), "A/"), (nid(3), "A_")]

    assert unique_segments(siblings) == unique_segments(list(reversed(siblings)))


def test_sanitized_names_collide_with_existing_ones():
    result = unique_segments([(nid(1), "Pick/Place"), (nid(2), "Pick_Place")])

    assert result == {nid(1): "Pick_Place", nid(2): "Pick_Place_2"}


def test_suffix_never_takes_another_siblings_name():
    result = unique_segments([(nid(1), "A"), (nid(2), "A"), (nid(3), "A_2")])

    assert result == {nid(1): "A", nid(2): "A_3", nid(3): "A_2"}


def test_identifier_types_sort_numeric_string_guid_opaque():
    guid = uuid.UUID("09087e75-8e5e-499b-954f-f2a9603db28a")
    result = unique_segments([(nid(b"\x01"), "X"), (nid(guid), "X"), (nid("s"), "X"), (nid(7), "X")])

    assert result == {nid(7): "X", nid("s"): "X_2", nid(guid): "X_3", nid(b"\x01"): "X_4"}


def test_namespace_uri_sorts_before_identifier():
    result = unique_segments([(nid(1, OTHER_NS), "X"), (nid(2, NS), "X")])

    assert result == {nid(2, NS): "X", nid(1, OTHER_NS): "X_2"}


def test_sanitizing_and_suffixing_are_logged():
    with capture_logs() as logs:
        unique_segments([(nid(1), "Pick"), (nid(2), "Pick"), (nid(3), "A/B")])

    events = [(log["event"], log["browse_name"], log["segment"]) for log in logs]
    assert ("Duplicate path segment", "Pick", "Pick_2") in events
    assert ("Browse name is no valid path segment", "A/B", "A_B") in events
    assert all(log["log_level"] == "warning" for log in logs)


def test_unique_names_log_nothing():
    with capture_logs() as logs:
        unique_segments([(nid(1), "Pick"), (nid(2), "Place")])

    assert logs == []
