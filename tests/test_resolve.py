# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Tests for resolving and finding objects by path on BaseServer and BaseUaObject."""

from __future__ import annotations

import gc
import itertools
from dataclasses import dataclass, field
from typing import ClassVar

import pytest
from asyncua import ua
from structlog.testing import capture_logs

from opensmi.core import ObjectPath
from opensmi.core.base_server import BaseServer
from opensmi.core.base_ua_object import BaseUaObject

_IDS = itertools.count(1000)


@dataclass
class _FakeNode:
    nodeid: ua.NodeId = field(default_factory=lambda: ua.NodeId(next(_IDS), 1))


class _Machine(BaseUaObject):
    pass


class _Component(BaseUaObject):
    _folder: ClassVar[str | None] = "Components"


class _Skill(BaseUaObject):
    _folder: ClassVar[str | None] = "SkillSet"


class _Container(BaseUaObject):
    pass


class _Variable(BaseUaObject):
    pass


def _add(obj: BaseUaObject) -> BaseUaObject:
    obj.ua_node = _FakeNode()  # pyright: ignore[reportAttributeAccessIssue]  registers the object
    return obj


@pytest.fixture
def tree():
    server = BaseServer()
    m1 = _add(_Machine(name="M1", server=server))
    gripper = _add(_Component(name="Gripper", parent=m1))
    pick = _add(_Skill(name="Pick", parent=gripper))
    place = _add(_Skill(name="Place", parent=gripper))
    params = _add(_Container(name="ParameterSet", parent=pick))
    force = _add(_Variable(name="Force", parent=params))
    m2 = _add(_Machine(name="M2", server=server))
    return {
        "server": server,
        "m1": m1,
        "gripper": gripper,
        "pick": pick,
        "place": place,
        "params": params,
        "force": force,
        "m2": m2,
    }


# --------------------------------------------------------------------------- BaseServer.resolve


def test_resolve_by_object_path_and_str(tree):
    server = tree["server"]

    assert server.resolve(ObjectPath.parse("/M1/Components/Gripper/SkillSet/Pick")) is tree["pick"]
    assert server.resolve("/M1/Components/Gripper/SkillSet/Pick/ParameterSet/Force") is tree["force"]
    assert server.resolve("/M2") is tree["m2"]


def test_resolve_unknown_path(tree):
    with pytest.raises(KeyError):
        tree["server"].resolve("/M1/Components/Gripper/SkillSet/Drop")
    assert tree["server"].resolve_optional("/M1/Components/Gripper/SkillSet/Drop") is None


def test_resolve_invalid_text(tree):
    with pytest.raises(ValueError, match="Path"):
        tree["server"].resolve("M1")


def test_unregister_removes_path(tree):
    server, place = tree["server"], tree["place"]

    server.unregister_ua_object(place)

    assert server.resolve_optional(place.path) is None


def test_dropped_objects_disappear():
    server = BaseServer()
    machine = _add(_Machine(name="M1", server=server))
    _add(_Component(name="Temp", parent=machine))
    gc.collect()

    assert server.resolve_optional("/M1/Components/Temp") is None
    assert server.resolve("/M1") is machine


def test_clear_forgets_nodes_and_paths(tree):
    server = tree["server"]

    server._clear_ua_objects()

    assert server.resolve_optional("/M1") is None
    assert server.get_ua_object_optional(tree["m1"].ua_node.nodeid) is None


def test_duplicate_path_keeps_first_and_logs_error(tree):
    server, gripper = tree["server"], tree["gripper"]

    with capture_logs() as logs:
        duplicate = _add(_Skill(name="Pick", parent=gripper))

    assert server.resolve(duplicate.path) is tree["pick"]
    assert [log["log_level"] for log in logs] == ["error"]


# --------------------------------------------------------------------------- BaseServer.find


def test_find_in_tree_order(tree):
    found = tree["server"].find("/M1/**/SkillSet/*")

    assert found == [tree["pick"], tree["place"]]


def test_find_everything(tree):
    assert tree["server"].find("/**") == [
        tree["m1"],
        tree["gripper"],
        tree["pick"],
        tree["params"],
        tree["force"],
        tree["place"],
        tree["m2"],
    ]


def test_find_nothing(tree):
    assert tree["server"].find("/M3/**") == []


# --------------------------------------------------------------------------- aliases


def test_alias_resolves_to_same_object(tree):
    server, force = tree["server"], tree["force"]
    monitoring = _add(_Container(name="Monitoring", parent=tree["pick"]))
    alias = monitoring.path / "Force"

    force._add_alias(alias)

    assert force.aliases == frozenset({alias})
    assert server.resolve(alias) is force
    assert server.resolve(force.path) is force


def test_find_returns_aliased_object_once_under_canonical_path(tree):
    force = tree["force"]
    force._add_alias(ObjectPath.parse("/M1/Components/Gripper/SkillSet/Pick/Monitoring/Force"))

    assert tree["server"].find("/**/Force") == [force]


def test_alias_added_before_node_is_registered_with_it():
    server = BaseServer()
    machine = _add(_Machine(name="M1", server=server))
    variable = _Variable(name="Force", parent=machine)
    variable._add_alias(ObjectPath.parse("/M1/Monitoring/Force"))

    assert server.resolve_optional("/M1/Monitoring/Force") is None
    _add(variable)
    assert server.resolve("/M1/Monitoring/Force") is variable


def test_unregister_removes_aliases(tree):
    server, force = tree["server"], tree["force"]
    alias = ObjectPath.parse("/M1/Monitoring/Force")
    force._add_alias(alias)

    server.unregister_ua_object(force)

    assert server.resolve_optional(alias) is None
    assert server.resolve_optional(force.path) is None


def test_alias_cannot_take_another_objects_path(tree):
    with capture_logs() as logs:
        tree["force"]._add_alias(tree["place"].path)

    assert tree["server"].resolve(tree["place"].path) is tree["place"]
    assert [log["log_level"] for log in logs] == ["error"]


# --------------------------------------------------------------------------- relative lookups on objects


def test_relative_resolve(tree):
    gripper = tree["gripper"]

    assert gripper.resolve("SkillSet/Pick") is tree["pick"]
    assert gripper.resolve("SkillSet/Pick/ParameterSet/Force") is tree["force"]
    assert gripper.resolve_optional("SkillSet/Drop") is None
    with pytest.raises(KeyError):
        gripper.resolve("SkillSet/Drop")


@pytest.mark.parametrize("relative", ["/M1", "SkillSet//Pick", ""])
def test_relative_resolve_rejects_invalid_paths(tree, relative):
    with pytest.raises(ValueError, match=r"path|segment"):
        tree["gripper"].resolve(relative)


def test_relative_find(tree):
    assert tree["gripper"].find("SkillSet/P*") == [tree["pick"], tree["place"]]
    assert tree["gripper"].find("**/Force") == [tree["force"]]


def test_relative_find_rejects_absolute_pattern(tree):
    with pytest.raises(ValueError, match="relative"):
        tree["gripper"].find("/**")


def test_relative_find_escapes_own_path():
    server = BaseServer()
    odd = _add(_Machine(name="M[1]", server=server))
    other = _add(_Machine(name="M1", server=server))
    child = _add(_Component(name="A", parent=odd))
    _add(_Component(name="A", parent=other))

    assert odd.find("**") == [child]


# --------------------------------------------------------------------------- parent guard


def test_parent_can_be_set_before_the_node():
    server = BaseServer()
    machine = _Machine(name="M1", server=server)
    component = _Component(name="Gripper")

    component.parent = machine

    assert component.path == ObjectPath.parse("/M1/Components/Gripper")


def test_parent_cannot_change_after_the_node(tree):
    with pytest.raises(RuntimeError, match="already registered"):
        tree["pick"].parent = tree["m2"]


# --------------------------------------------------------------------------- top-down registration


def test_child_cannot_register_before_its_parent():
    server = BaseServer()
    machine = _Machine(name="M1", server=server)
    component = _Component(name="Gripper", parent=machine)

    with pytest.raises(RuntimeError, match="isn't registered yet"):
        _add(component)
    assert server.resolve_optional("/M1/Components/Gripper") is None


def test_child_cannot_register_under_an_unregistered_parent(tree):
    server, gripper = tree["server"], tree["gripper"]
    server.unregister_ua_object(gripper)

    with pytest.raises(RuntimeError, match="isn't registered yet"):
        _add(_Skill(name="Drop", parent=gripper))


def test_objects_without_parent_register():
    server = BaseServer()

    machine = _add(_Machine(name="M1", server=server))

    assert server.resolve("/M1") is machine
