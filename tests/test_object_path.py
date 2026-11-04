# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Tests for ObjectPath, the naming rules and BaseUaObject.path."""

from __future__ import annotations

import dataclasses
from typing import ClassVar

import pytest

from opensmi.core import ObjectPath
from opensmi.core.base_ua_object import BaseUaObject
from opensmi.core.paths import check_name, check_segment

SKILL = ObjectPath(("M1", "Components", "Gripper", "SkillSet", "Pick"))


# --------------------------------------------------------------------------- construction and text


@pytest.mark.parametrize(
    ("text", "segments"),
    [
        ("/", ()),
        ("/M1", ("M1",)),
        ("/M1/Components/Gripper/SkillSet/Pick", ("M1", "Components", "Gripper", "SkillSet", "Pick")),
        ("/a/./..", ("a", ".", "..")),
        ("/Grip per.ä", ("Grip per.ä",)),
    ],
)
def test_parse_and_str_round_trip(text, segments):
    path = ObjectPath.parse(text)

    assert path.segments == segments
    assert str(path) == text


@pytest.mark.parametrize("text", ["", "M1", "M1/Pick", "//M1", "/M1//Pick", "/M1/"])
def test_parse_rejects_invalid_text(text):
    with pytest.raises(ValueError, match="Path"):
        ObjectPath.parse(text)


@pytest.mark.parametrize("segment", ["", "a/b"])
def test_invalid_segments_are_rejected(segment):
    with pytest.raises(ValueError, match="segment"):
        ObjectPath(("M1", segment))
    with pytest.raises(ValueError, match="segment"):
        ObjectPath.parse("/M1") / segment


def test_segments_must_be_a_tuple_of_str():
    with pytest.raises(TypeError):
        ObjectPath(["M1"])  # pyright: ignore[reportArgumentType]
    with pytest.raises(TypeError):
        ObjectPath(("M1", 1))  # pyright: ignore[reportArgumentType]


def test_of_accepts_path_and_str():
    assert ObjectPath.of(SKILL) is SKILL
    assert ObjectPath.of(str(SKILL)) == SKILL


def test_dot_segments_are_kept():
    assert ObjectPath.parse("/M1") / "." / ".." == ObjectPath(("M1", ".", ".."))


# --------------------------------------------------------------------------- navigation


def test_truediv_name_and_parent():
    path = ObjectPath() / "M1" / "SkillSet"

    assert path == ObjectPath.parse("/M1/SkillSet")
    assert path.name == "SkillSet"
    assert path.parent == ObjectPath.parse("/M1")


def test_root():
    root = ObjectPath()

    assert str(root) == "/"
    assert root.name == ""
    assert ObjectPath.parse("/M1").parent == root
    with pytest.raises(ValueError, match="root"):
        _ = root.parent


@pytest.mark.parametrize(
    ("other", "expected"),
    [
        ("/", True),
        ("/M1/Components", True),
        (SKILL, True),
        ("/M1/Comp", False),
        ("/M1/Components/Gripper/SkillSet/Pick/FeasibilityCheck", False),
        ("/M2", False),
    ],
)
def test_is_relative_to(other, expected):
    assert SKILL.is_relative_to(other) is expected


# --------------------------------------------------------------------------- value semantics


def test_equal_only_to_object_paths():
    assert ObjectPath.parse(str(SKILL)) == SKILL
    assert str(SKILL) != SKILL
    assert hash(SKILL) == hash(ObjectPath.parse(str(SKILL)))


def test_order_is_tree_order():
    paths = [ObjectPath.parse(p) for p in ["/M2", "/M1/B", "/M1", "/M1/A/X", "/M1/A"]]

    assert [str(p) for p in sorted(paths)] == ["/M1", "/M1/A", "/M1/A/X", "/M1/B", "/M2"]


def test_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        SKILL.segments = ()  # pyright: ignore[reportAttributeAccessIssue]


# --------------------------------------------------------------------------- glob


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("/M1/Components/Gripper/SkillSet/Pick", True),
        ("/M1/Components/*/SkillSet/Pick", True),
        ("/M1/Components/Grip*/SkillSet/P?ck", True),
        ("/M1/Components/Gripper/SkillSet/[PQ]ick", True),
        ("/**/Pick", True),
        ("/M1/**/SkillSet/Pick", True),
        ("/M1/**/Components/Gripper/SkillSet/Pick", True),  # ** matches zero segments
        ("/**", True),
        ("/M1/**", True),
        ("/**/SkillSet/**", True),
        ("/M1/*/Pick", False),  # * is one segment
        ("/Pick", False),  # whole path, not from the end
        ("/M1/Components/Gripper/SkillSet/pick", False),  # case-sensitive
        ("/M1/Components/Gripper/SkillSet", False),
        ("/M1/Components/Gripper/SkillSet/Pick/**/X", False),
    ],
)
def test_match(pattern, expected):
    assert SKILL.match(pattern) is expected


def test_root_matches():
    assert ObjectPath().match("/")
    assert ObjectPath().match("/**")
    assert not ObjectPath().match("/*")


@pytest.mark.parametrize("pattern", ["", "M1/*", "/M1//*", "/M1/"])
def test_match_rejects_invalid_patterns(pattern):
    with pytest.raises(ValueError, match="Path"):
        SKILL.match(pattern)


@pytest.mark.parametrize("segment", ["Slot[1]", "a*b", "what?", "**", "plain"])
def test_escape_matches_only_itself(segment):
    path = ObjectPath(("Users", segment))
    pattern = f"/Users/{ObjectPath.escape(segment)}"

    assert path.match(pattern)
    assert not ObjectPath(("Users", segment + "x")).match(pattern)


def test_unescaped_brackets_are_a_character_class():
    assert not ObjectPath(("Slot[1]",)).match("/Slot[1]")
    assert ObjectPath(("Slot1",)).match("/Slot[1]")


def test_many_any_depth_segments_stay_fast():
    deep = ObjectPath(tuple("a" * 40))

    assert not deep.match("/" + "/".join(["**"] * 20) + "/b")


# --------------------------------------------------------------------------- naming rules


@pytest.mark.parametrize("name", ["Pick", "M1", "FeasibilityCheck", "X", "ABC123"])
def test_valid_names(name):
    check_name(name)


@pytest.mark.parametrize(
    "name",
    ["", "pick", "1Pick", "Pick_Place", "Pick/Place", "Pick Place", "Greifer-1", "Äpfel", "True", "False", "None"],
)
def test_invalid_names(name):
    with pytest.raises(ValueError, match="Name"):
        check_name(name)


@pytest.mark.parametrize("name", ["operator", "j.doe", "Max Mustermann", "user@example.com", "True", "*"])
def test_valid_segments(name):
    check_segment(name)


@pytest.mark.parametrize("name", ["", "a/b"])
def test_invalid_segments(name):
    with pytest.raises(ValueError, match="segment"):
        check_segment(name)


# --------------------------------------------------------------------------- BaseUaObject.path


class _Machine(BaseUaObject):
    pass


class _Component(BaseUaObject):
    _folder: ClassVar[str | None] = "Components"


class _Skill(BaseUaObject):
    _folder: ClassVar[str | None] = "SkillSet"


class _Check(BaseUaObject):
    pass


def test_path_includes_folders():
    machine = _Machine(name="M1")
    gripper = _Component(name="Gripper", parent=machine)
    pick = _Skill(name="Pick", parent=gripper)
    check = _Check(name="FeasibilityCheck", parent=pick)

    assert machine.path == ObjectPath.parse("/M1")
    assert gripper.path == ObjectPath.parse("/M1/Components/Gripper")
    assert pick.path == ObjectPath.parse("/M1/Components/Gripper/SkillSet/Pick")
    assert check.path == ObjectPath.parse("/M1/Components/Gripper/SkillSet/Pick/FeasibilityCheck")


def test_segment_defaults_to_sanitized_name():
    obj = _Component(name="Pick/Place", parent=_Machine(name="M1"))

    assert obj.name == "Pick/Place"
    assert obj.path == ObjectPath.parse("/M1/Components/Pick_Place")


def test_explicit_segment():
    obj = _Component(name="Pick", segment="Pick_2", parent=_Machine(name="M1"))

    assert obj.name == "Pick"
    assert obj.path.name == "Pick_2"


def test_invalid_explicit_segment_is_rejected():
    with pytest.raises(ValueError, match="segment"):
        _Component(name="Pick", segment="a/b")


def test_empty_name_gets_placeholder_segment():
    obj = _Component(name="", parent=_Machine(name="M1"))

    assert obj.name == ""
    assert obj.path == ObjectPath.parse("/M1/Components/_")
