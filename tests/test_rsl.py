# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Tests for Position / Orientation / Pose, including a SciPy cross-check.

SciPy is a *test-only* dependency and the independent reference implementation.
"""

from __future__ import annotations

import dataclasses
import math
from itertools import product

import numpy as np
import pytest
from scipy.spatial.transform import Rotation as R  # noqa: N817

from opensmi.core import Unit
from opensmi.core.rsl import Orientation, Pose, Position, _matmul, _matrix_of, _orientation_from, _rotate, _transpose

MM, CM, M = Unit.MILLIMETRE, Unit.CENTIMETRE, Unit.METRE
DEG, RAD = Unit.DEGREE_UNIT_OF_ANGLE, Unit.RADIAN

LENGTH_UNITS = [MM, CM, M]
ANGLE_UNITS = [DEG, RAD]
SEEDS = list(range(20))
ATOL = 1e-9
IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


# --------------------------------------------------------------------------- helpers


def rand_orientation(g: np.random.Generator, unit: Unit = DEG, max_pitch: float = 85.0) -> Orientation:
    """Random orientation, kept away from gimbal lock unless ``max_pitch`` says otherwise."""
    o = Orientation(
        float(g.uniform(-180, 180)),
        float(g.uniform(-max_pitch, max_pitch)),
        float(g.uniform(-180, 180)),
        DEG,
    )
    return o.to(unit)


def rand_position(g: np.random.Generator, unit: Unit = MM) -> Position:
    return Position(*(float(v) for v in g.uniform(-1000, 1000, size=3)), MM).to(unit)


def rand_pose(g: np.random.Generator, length: Unit = MM, angle: Unit = DEG) -> Pose:
    return Pose(rand_position(g, length), rand_orientation(g, angle))


def sp_rot(o: Orientation) -> R:
    return R.from_euler("xyz", o.as_tuple(), degrees=o.unit == DEG)


def sp_pose(p: Pose) -> tuple[R, np.ndarray]:
    return sp_rot(p.orientation), np.array(p.position.to(M).as_tuple())


def assert_matrix_equals(o: Orientation, rot: R, atol: float = 1e-12) -> None:
    np.testing.assert_allclose(_matrix_of(o), rot.as_matrix().ravel(), atol=atol)


def assert_pose_matches(p: Pose, rot: R, t_metres: np.ndarray, atol: float = ATOL) -> None:
    np.testing.assert_allclose(p.position.to(M).as_tuple(), t_metres, atol=atol)
    assert_matrix_equals(p.orientation, rot, atol=atol)


def angle_diff_deg(x: float, y: float) -> float:
    """Smallest absolute difference between two angles in degrees."""
    return abs((x - y + 180.0) % 360.0 - 180.0)


# --------------------------------------------------------------------------- units


class TestUnits:
    @pytest.mark.parametrize(
        ("src", "dst", "factor"),
        [
            (M, MM, 1000.0),
            (M, CM, 100.0),
            (CM, MM, 10.0),
            (MM, M, 0.001),
            (MM, CM, 0.1),
            (CM, M, 0.01),
        ],
    )
    def test_position_conversion(self, src: Unit, dst: Unit, factor: float) -> None:
        p = Position(1.0, -2.0, 3.0, src).to(dst)
        assert p.unit == dst
        assert p.as_tuple() == pytest.approx((factor, -2 * factor, 3 * factor))

    def test_exact_when_scaling_up(self) -> None:
        # The table is expressed relative to the smallest unit, so these are exact.
        assert Position(1.5, 2.5, 3.5, M).to(MM).as_tuple() == (1500.0, 2500.0, 3500.0)

    def test_orientation_conversion(self) -> None:
        o = Orientation(90.0, -45.0, 180.0, DEG).to(RAD)
        assert o.unit == RAD
        assert o.as_tuple() == pytest.approx((math.pi / 2, -math.pi / 4, math.pi))
        assert o.to(DEG).as_tuple() == pytest.approx((90.0, -45.0, 180.0))

    @pytest.mark.parametrize("seed", SEEDS)
    def test_position_round_trip(self, seed: int) -> None:
        p = rand_position(np.random.default_rng(seed))
        for unit in LENGTH_UNITS:
            assert p.to(unit).to(MM).is_close(p)

    @pytest.mark.parametrize("seed", SEEDS)
    def test_orientation_round_trip(self, seed: int) -> None:
        o = rand_orientation(np.random.default_rng(seed))
        assert o.to(RAD).to(DEG).as_tuple() == pytest.approx(o.as_tuple())

    def test_same_unit_returns_same_object(self) -> None:
        p, o = Position(1, 2, 3, MM), Orientation(1, 2, 3, DEG)
        assert p.to(MM) is p
        assert o.to(DEG) is o

    def test_unsupported_unit_in_constructor(self) -> None:
        with pytest.raises(ValueError, match="unsupported unit"):
            Position(unit=RAD)
        with pytest.raises(ValueError, match="unsupported unit"):
            Orientation(unit=MM)

    def test_unsupported_target_unit_raises_every_time(self) -> None:
        # Guards against exceptions being cached (they aren't) or swallowed.
        p, o = Position(1, 2, 3, MM), Orientation(1, 2, 3, DEG)
        for _ in range(3):
            with pytest.raises(ValueError, match="unsupported unit"):
                p.to(RAD)
            with pytest.raises(ValueError, match="unsupported unit"):
                o.to(MM)
            with pytest.raises(ValueError, match="unsupported unit"):
                p.to(Unit.SECOND_UNIT_OF_TIME)

    def test_defaults(self) -> None:
        assert Position() == Position(0.0, 0.0, 0.0, MM)
        assert Orientation() == Orientation(0.0, 0.0, 0.0, DEG)


# --------------------------------------------------------------------------- matrix


class TestMatrix:
    def test_identity(self) -> None:
        assert _matrix_of(Orientation()) == IDENTITY

    @pytest.mark.parametrize(("seed", "unit"), list(product(SEEDS, ANGLE_UNITS)))
    def test_matches_scipy(self, seed: int, unit: Unit) -> None:
        o = rand_orientation(np.random.default_rng(seed), unit, max_pitch=90.0)
        assert_matrix_equals(o, sp_rot(o))

    @pytest.mark.parametrize("seed", SEEDS)
    def test_is_proper_rotation(self, seed: int) -> None:
        m = _matrix_of(rand_orientation(np.random.default_rng(seed), max_pitch=90.0))
        np.testing.assert_allclose(_matmul(m, _transpose(m)), IDENTITY, atol=1e-12)
        assert np.linalg.det(np.array(m).reshape(3, 3)) == pytest.approx(1.0)

    @pytest.mark.parametrize(
        ("o", "v", "expected"),
        [
            # roll (x): y -> z
            (Orientation(90, 0, 0), (0, 1, 0), (0, 0, 1)),
            # pitch (y): z -> x
            (Orientation(0, 90, 0), (0, 0, 1), (1, 0, 0)),
            # yaw (z): x -> y
            (Orientation(0, 0, 90), (1, 0, 0), (0, 1, 0)),
        ],
    )
    def test_single_axis_rotations(self, o: Orientation, v: tuple[float, ...], expected: tuple[float, ...]) -> None:
        assert _rotate(_matrix_of(o), v) == pytest.approx(expected, abs=1e-12)  # type: ignore[arg-type]

    def test_order_is_yaw_then_pitch_then_roll(self) -> None:
        # R = Rz(c) Ry(b) Rx(a): the roll is applied to the vector first.
        o = Orientation(90, 0, 90)  # roll 90 then yaw 90
        # y --roll--> z --yaw--> z
        assert _rotate(_matrix_of(o), (0, 1, 0)) == pytest.approx((0, 0, 1), abs=1e-12)
        # x --roll--> x --yaw--> y
        assert _rotate(_matrix_of(o), (1, 0, 0)) == pytest.approx((0, 1, 0), abs=1e-12)

    def test_rotate_and_transpose_are_inverse(self) -> None:
        m = _matrix_of(Orientation(10, 20, 30))
        v = (1.0, -2.0, 3.0)
        assert _rotate(_transpose(m), _rotate(m, v)) == pytest.approx(v)


# --------------------------------------------------------------------------- euler round trip


class TestEulerExtraction:
    @pytest.mark.parametrize(("seed", "unit"), list(product(SEEDS, ANGLE_UNITS)))
    def test_round_trip_recovers_angles(self, seed: int, unit: Unit) -> None:
        o = rand_orientation(np.random.default_rng(seed), unit)
        back = _orientation_from(_matrix_of(o), unit)
        assert back.unit == unit
        for x, y in zip(o.to(DEG).as_tuple(), back.to(DEG).as_tuple()):
            assert angle_diff_deg(x, y) == pytest.approx(0.0, abs=1e-9)

    @pytest.mark.parametrize("seed", SEEDS)
    def test_matches_scipy_as_euler(self, seed: int) -> None:
        o = rand_orientation(np.random.default_rng(seed))
        ours = _orientation_from(_matrix_of(o), DEG).as_tuple()
        theirs = sp_rot(o).as_euler("xyz", degrees=True)
        for x, y in zip(ours, theirs):
            assert angle_diff_deg(x, float(y)) == pytest.approx(0.0, abs=1e-9)

    @pytest.mark.parametrize("seed", SEEDS)
    def test_output_unit_is_respected(self, seed: int) -> None:
        o = rand_orientation(np.random.default_rng(seed))
        m = _matrix_of(o)
        assert _orientation_from(m, RAD).to(DEG).is_close(_orientation_from(m, DEG))

    @pytest.mark.parametrize("pitch", [90.0, -90.0])
    @pytest.mark.parametrize(("a", "c"), [(0, 0), (30, 10), (-120, 75), (179, -179)])
    def test_exact_gimbal_lock(self, pitch: float, a: float, c: float) -> None:
        o = Orientation(a, pitch, c)
        back = _orientation_from(_matrix_of(o), DEG)
        # Same rotation, canonical representation: yaw is folded into roll.
        assert back.is_close(o)
        assert back.b == pytest.approx(pitch)
        assert back.c == 0.0
        assert_matrix_equals(back, sp_rot(o))

    @pytest.mark.parametrize(
        ("delta_deg", "tol"),
        [(1e-3, 1e-9), (1e-5, 1e-6), (1e-7, 1e-8), (0.0, 1e-12)],
    )
    @pytest.mark.parametrize("sign", [1, -1])
    def test_near_gimbal_lock(self, delta_deg: float, tol: float, sign: int) -> None:
        # Precision degrades near the singularity; tolerances reflect that.
        o = Orientation(25.0, sign * (90.0 - delta_deg), 40.0)
        back = _orientation_from(_matrix_of(o), DEG)
        assert back.is_close(o, abs_tol=tol)

    def test_pitch_is_clamped_against_rounding(self) -> None:
        # An entry a hair beyond +-1 must not make asin() raise.
        m = (0.0, 0.0, 1.0, 0.0, 1.0, 0.0, -1.0 - 1e-15, 0.0, 0.0)
        assert _orientation_from(m, DEG).b == pytest.approx(90.0)


# --------------------------------------------------------------------------- is_close


class TestIsClose:
    def test_position_reflexive_and_unit_aware(self) -> None:
        p = Position(1, 2, 3, M)
        assert p.is_close(p)
        assert p.is_close(Position(1000, 2000, 3000, MM))
        assert Position(1000, 2000, 3000, MM).is_close(p)

    def test_position_tolerances(self) -> None:
        p = Position(1.0, 1.0, 1.0, MM)
        assert not p.is_close(Position(1.0, 1.0, 1.001, MM))
        assert p.is_close(Position(1.0, 1.0, 1.001, MM), abs_tol=0.01)
        assert p.is_close(Position(1.0, 1.0, 1.001, MM), rel_tol=0.01)

    def test_position_zero_needs_abs_tol(self) -> None:
        assert Position(0, 0, 0).is_close(Position(1e-12, 0, 0))
        assert not Position(0, 0, 0).is_close(Position(1e-6, 0, 0))

    @pytest.mark.parametrize(
        ("x", "y"),
        [
            (Orientation(0, 0, 359), Orientation(0, 0, -1)),  # wrapping on yaw
            (Orientation(360, 0, 0), Orientation(0, 0, 0)),  # full turn on roll
            (Orientation(180, 0, 0), Orientation(-180, 0, 0)),
            (Orientation(30, 90, 10), Orientation(20, 90, 0)),  # gimbal lock, +90
            (Orientation(30, -90, 10), Orientation(40, -90, 0)),  # gimbal lock, -90
            (Orientation(0, 0, 90, DEG), Orientation(0, 0, math.pi / 2, RAD)),  # mixed units
            # the same rotation written two ways: (a, b, c) == (a+180, 180-b, c+180)
            (Orientation(10, 20, 30), Orientation(190, 160, 210)),
        ],
    )
    def test_orientation_equivalent_rotations(self, x: Orientation, y: Orientation) -> None:
        assert x.is_close(y)
        assert y.is_close(x)

    @pytest.mark.parametrize(
        ("x", "y"),
        [
            (Orientation(0, 0, 0), Orientation(0, 0, 1)),
            (Orientation(10, 20, 30), Orientation(30, 20, 10)),
            (Orientation(0, 0, 90), Orientation(0, 0, math.pi / 2, DEG)),  # unit mix-up
        ],
    )
    def test_orientation_different_rotations(self, x: Orientation, y: Orientation) -> None:
        assert not x.is_close(y)

    @pytest.mark.parametrize("seed", SEEDS)
    def test_orientation_matches_scipy_equivalence(self, seed: int) -> None:
        g = np.random.default_rng(seed)
        x, y = rand_orientation(g), rand_orientation(g)
        sp_equal = bool(np.allclose(sp_rot(x).as_matrix(), sp_rot(y).as_matrix(), atol=1e-9))
        assert x.is_close(y) == sp_equal
        assert x.is_close(x)

    def test_pose_is_close(self) -> None:
        p = Pose(Position(1, 2, 3, M), Orientation(10, 20, 30))
        assert p.is_close(p)
        assert p.is_close(Pose(Position(1000, 2000, 3000, MM), Orientation(10, 20, 30 + 360)))
        assert not p.is_close(Pose(Position(1, 2, 3.01, M), p.orientation))
        assert not p.is_close(Pose(p.position, Orientation(10, 20, 31)))


# --------------------------------------------------------------------------- accessors


class TestAccessors:
    def test_as_tuple(self) -> None:
        assert Position(1, 2, 3, CM).as_tuple() == (1, 2, 3)
        assert Orientation(4, 5, 6, RAD).as_tuple() == (4, 5, 6)

    def test_not_iterable(self) -> None:
        with pytest.raises(TypeError):
            iter(Position())  # type: ignore[call-overload]


# --------------------------------------------------------------------------- composition


class TestComposition:
    @pytest.mark.parametrize(
        ("seed", "l1", "a1", "l2", "a2"),
        [(s, *u) for s in range(8) for u in product(LENGTH_UNITS, ANGLE_UNITS, LENGTH_UNITS, ANGLE_UNITS)],
    )
    def test_matches_scipy(self, seed: int, l1: Unit, a1: Unit, l2: Unit, a2: Unit) -> None:
        g = np.random.default_rng(seed)
        a, b = rand_pose(g, l1, a1), rand_pose(g, l2, a2)
        (ra, ta), (rb, tb) = sp_pose(a), sp_pose(b)

        c = a @ b

        assert c.position.unit == l1
        assert c.orientation.unit == a1
        assert_pose_matches(c, ra * rb, ta + ra.apply(tb))

    @pytest.mark.parametrize("seed", SEEDS)
    def test_identity_is_neutral(self, seed: int) -> None:
        p = rand_pose(np.random.default_rng(seed))
        assert (Pose() @ p).is_close(p)
        assert (p @ Pose()).is_close(p)

    @pytest.mark.parametrize("seed", SEEDS)
    def test_associative(self, seed: int) -> None:
        g = np.random.default_rng(seed)
        a, b, c = (rand_pose(g, MM, DEG) for _ in range(3))
        assert ((a @ b) @ c).is_close(a @ (b @ c), abs_tol=1e-8)

    def test_not_commutative(self) -> None:
        a = Pose(Position(1, 0, 0, M), Orientation(0, 0, 90))
        b = Pose(Position(1, 0, 0, M), Orientation(0, 0, 0))
        assert not (a @ b).is_close(b @ a)

    def test_rotations_do_not_commute(self) -> None:
        roll = Pose(orientation=Orientation(90, 0, 0))
        yaw = Pose(orientation=Orientation(0, 0, 90))
        assert not (roll @ yaw).is_close(yaw @ roll)

    def test_known_example_yaw_then_translate(self) -> None:
        # A frame 1 m along x, yawed 90 degrees. A child 1 m along its own x
        # therefore ends up at (1, 1, 0) in the parent frame.
        parent = Pose(Position(1, 0, 0, M), Orientation(0, 0, 90))
        child = Pose(Position(1, 0, 0, M))
        c = parent @ child
        assert c.position.as_tuple() == pytest.approx((1, 1, 0), abs=1e-12)
        assert c.orientation.as_tuple() == pytest.approx((0, 0, 90), abs=1e-9)

    def test_pure_translations_add(self) -> None:
        c = Pose(Position(1, 2, 3, MM)) @ Pose(Position(10, 20, 30, MM))
        assert c.position.as_tuple() == pytest.approx((11, 22, 33))

    def test_same_axis_rotations_add_angles(self) -> None:
        c = Pose(orientation=Orientation(0, 0, 30)) @ Pose(orientation=Orientation(0, 0, 40))
        assert c.orientation.as_tuple() == pytest.approx((0, 0, 70), abs=1e-9)

    def test_composition_into_gimbal_lock(self) -> None:
        a = Pose(orientation=Orientation(0, 45, 0))
        c = a @ a
        assert c.orientation.b == pytest.approx(90.0)
        assert_matrix_equals(c.orientation, sp_rot(a.orientation) * sp_rot(a.orientation), atol=1e-9)

    def test_does_not_mutate_operands(self) -> None:
        a, b = rand_pose(np.random.default_rng(1)), rand_pose(np.random.default_rng(2))
        a0, b0 = dataclasses.replace(a), dataclasses.replace(b)
        _ = a @ b
        assert (a, b) == (a0, b0)

    def test_repeated_small_rotations_return_to_start(self) -> None:
        step = Pose(orientation=Orientation(0, 0, 1))
        acc = Pose()
        for _ in range(360):
            acc = acc @ step
        assert acc.is_close(Pose(), abs_tol=1e-9)

    def test_long_chain_matches_scipy_without_drift(self) -> None:
        g = np.random.default_rng(42)
        acc = Pose()
        rot, t = R.identity(), np.zeros(3)
        for _ in range(500):
            step = rand_pose(g, M, RAD)
            acc = acc @ step
            sr, st = sp_pose(step)
            t, rot = t + rot.apply(st), rot * sr
        assert_pose_matches(acc, rot, t, atol=1e-9)


# --------------------------------------------------------------------------- inverse


class TestInverse:
    @pytest.mark.parametrize(
        ("seed", "length", "angle"),
        [(s, *u) for s in SEEDS for u in product(LENGTH_UNITS, ANGLE_UNITS)],
    )
    def test_inverse_composes_to_identity(self, seed: int, length: Unit, angle: Unit) -> None:
        p = rand_pose(np.random.default_rng(seed), length, angle)
        assert (p @ p.inverse()).is_close(Pose(Position(unit=length), Orientation(unit=angle)))
        assert (p.inverse() @ p).is_close(Pose(Position(unit=length), Orientation(unit=angle)))

    @pytest.mark.parametrize("seed", SEEDS)
    def test_matches_scipy(self, seed: int) -> None:
        p = rand_pose(np.random.default_rng(seed))
        rot, t = sp_pose(p)
        inv = rot.inv()
        assert_pose_matches(p.inverse(), inv, -inv.apply(t))

    @pytest.mark.parametrize("seed", SEEDS)
    def test_involution(self, seed: int) -> None:
        p = rand_pose(np.random.default_rng(seed))
        assert p.inverse().inverse().is_close(p)

    @pytest.mark.parametrize(("length", "angle"), list(product(LENGTH_UNITS, ANGLE_UNITS)))
    def test_units_are_preserved(self, length: Unit, angle: Unit) -> None:
        inv = rand_pose(np.random.default_rng(0), length, angle).inverse()
        assert inv.position.unit == length
        assert inv.orientation.unit == angle

    def test_identity_inverse(self) -> None:
        assert Pose().inverse().is_close(Pose())

    def test_inverse_of_composition(self) -> None:
        g = np.random.default_rng(7)
        a, b = rand_pose(g), rand_pose(g)
        assert (a @ b).inverse().is_close(b.inverse() @ a.inverse(), abs_tol=1e-8)

    def test_gimbal_lock_pose(self) -> None:
        p = Pose(Position(1, 2, 3, M), Orientation(20, 90, 0))
        assert (p @ p.inverse()).is_close(Pose(Position(unit=M)))


# --------------------------------------------------------------------------- transform


class TestTransform:
    @pytest.mark.parametrize(("seed", "length"), list(product(SEEDS, LENGTH_UNITS)))
    def test_matches_scipy(self, seed: int, length: Unit) -> None:
        g = np.random.default_rng(seed)
        pose = rand_pose(g, length, DEG)
        point = rand_position(g, length)
        rot, t = sp_pose(pose)

        out = pose.transform(point)

        assert out.unit == length
        np.testing.assert_allclose(out.to(M).as_tuple(), t + rot.apply(point.to(M).as_tuple()), atol=ATOL)

    def test_point_in_other_unit_is_converted(self) -> None:
        pose = Pose(Position(1, 0, 0, M), Orientation(0, 0, 90))
        out = pose.transform(Position(1000, 0, 0, MM))  # 1 m in mm
        assert out.unit == M
        assert out.as_tuple() == pytest.approx((1, 1, 0), abs=1e-12)

    @pytest.mark.parametrize("seed", SEEDS)
    def test_consistent_with_matmul(self, seed: int) -> None:
        g = np.random.default_rng(seed)
        pose, point = rand_pose(g), rand_position(g)
        assert pose.transform(point).is_close((pose @ Pose(point)).position)

    @pytest.mark.parametrize("seed", SEEDS)
    def test_inverse_undoes_transform(self, seed: int) -> None:
        g = np.random.default_rng(seed)
        pose, point = rand_pose(g), rand_position(g)
        assert pose.inverse().transform(pose.transform(point)).is_close(point, abs_tol=1e-8)

    def test_identity_orientation_is_pure_translation(self) -> None:
        out = Pose(Position(1, 2, 3, MM)).transform(Position(10, 20, 30, MM))
        assert out.as_tuple() == pytest.approx((11, 22, 33))

    def test_origin_maps_to_pose_position(self) -> None:
        pose = rand_pose(np.random.default_rng(3))
        assert pose.transform(Position(unit=MM)).is_close(pose.position)
