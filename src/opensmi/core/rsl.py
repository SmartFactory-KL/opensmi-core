# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Pose types with unit handling for OPC UA, plus light-weight pose math.

Based on the OPC UA Relative Spatial Location (OPC 10000-210), see
https://reference.opcfoundation.org/specs/OPC-10000-210/full

.. warning::

    The math (``@``, ``inverse()``, ``transform()``) is pure Python on Euler angles,
    meant for occasional use only. It is slow in bulk and accumulates rounding error when
    chained. Use a dedicated library (e.g. NumPy, SciPy) for anything heavier.

    Euler angles are not unique, so results may differ from the inputs while describing the
    same rotation. Compare with ``isclose()``, not ``==``.

Rotations are intrinsic z-y'-x'' (yaw, pitch, roll), equivalent to extrinsic x-y-z.
``a @ b`` expresses ``b`` in the frame of ``a`` and uses the left operand's units.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import cache
from typing import Final

from asyncua import ua

from opensmi.core import Unit

_Vec = tuple[float, float, float]
_Mat = tuple[float, float, float, float, float, float, float, float, float]  # row-major

_GIMBAL_EPS: Final = 1e-12


def _matrix_of(o: Orientation) -> _Mat:
    """Rotation matrix R = Rz(c) @ Ry(b) @ Rx(a) (intrinsic z-y'-x'')."""
    k = _angle_factor(o.unit, Unit.RADIAN)
    sa, ca = math.sin(o.a * k), math.cos(o.a * k)
    sb, cb = math.sin(o.b * k), math.cos(o.b * k)
    sc, cc = math.sin(o.c * k), math.cos(o.c * k)
    return (
        cb * cc, sa * sb * cc - ca * sc, ca * sb * cc + sa * sc,
        cb * sc, sa * sb * sc + ca * cc, ca * sb * sc - sa * cc,
        -sb,     sa * cb,                ca * cb,
    )  # fmt: skip


def _orientation_from(m: _Mat, unit: Unit) -> Orientation:
    """Inverse of ``_matrix_of``. At pitch ±90° (gimbal lock) yaw is set to 0."""
    r00, _, _, r10, r11, r12, r20, r21, r22 = m
    b = math.asin(max(-1.0, min(1.0, -r20)))
    if abs(r20) < 1.0 - _GIMBAL_EPS:
        a, c = math.atan2(r21, r22), math.atan2(r10, r00)
    else:
        a, c = math.atan2(-r12, r11), 0.0
    k = _angle_factor(Unit.RADIAN, unit)
    return Orientation(a * k, b * k, c * k, unit)


def _matmul(p: _Mat, q: _Mat) -> _Mat:
    return tuple(  # type: ignore
        sum(p[3 * i + k] * q[3 * k + j] for k in range(3)) for i in range(3) for j in range(3)
    )


def _transpose(m: _Mat) -> _Mat:
    return m[0], m[3], m[6], m[1], m[4], m[7], m[2], m[5], m[8]


def _rotate(m: _Mat, v: _Vec) -> _Vec:
    x, y, z = v
    return (
        m[0] * x + m[1] * y + m[2] * z,
        m[3] * x + m[4] * y + m[5] * z,
        m[6] * x + m[7] * y + m[8] * z,
    )


# TODO(CaHa): Maybe attach conversion factor to Unit. UNECE table has this information
_LENGTH: Final = {
    Unit.MILLIMETRE: 0.001,
    Unit.CENTIMETRE: 0.01,
    Unit.METRE: 1.0,
}
_ANGLE: Final = {
    Unit.DEGREE_UNIT_OF_ANGLE: math.pi / 180,
    Unit.RADIAN: 1.0,
}


def _require_supported(unit: Unit, table: dict[Unit, float]) -> None:
    if unit not in table:
        msg = f"unsupported unit {unit!r}, expected one of {list(table)}"
        raise ValueError(msg)


def _make_factor(table: dict[Unit, float]) -> Callable[[Unit, Unit], float]:
    @cache
    def factor(src: Unit, dst: Unit) -> float:
        _require_supported(src, table)
        _require_supported(dst, table)
        return table[src] / table[dst]

    return factor


_length_factor: Final = _make_factor(_LENGTH)
_angle_factor: Final = _make_factor(_ANGLE)


@dataclass(frozen=True, slots=True)
class Position:
    """Cartesian position defined by X, Y, and Z coordinates.

    see https://reference.opcfoundation.org/specs/OPC-10000-210/b-1
    """

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    unit: Unit = Unit.MILLIMETRE

    def __post_init__(self) -> None:
        """Verify unit post initialization."""
        _require_supported(self.unit, _LENGTH)

    def to(self, unit: Unit) -> Position:
        """Convert this position to one with given ``unit``."""
        if unit == self.unit:
            return self
        f = _length_factor(self.unit, unit)
        return Position(f * self.x, f * self.y, f * self.z, unit)

    def as_tuple(self) -> tuple[float, float, float]:
        """Return ``(x, y, z)`` in this position's unit."""
        return self.x, self.y, self.z

    def is_close(self, other: Position, *, rel_tol: float = 1e-9, abs_tol: float = 1e-9) -> bool:
        """Approximate equality; ``other`` is converted to this position's unit."""
        o = other.to(self.unit)
        return all(
            math.isclose(p, q, rel_tol=rel_tol, abs_tol=abs_tol)
            for p, q in zip(self.as_tuple(), o.as_tuple(), strict=True)
        )


@dataclass(frozen=True, slots=True)
class Orientation:
    """Angular orientation defined by A=roll (X), B=pitch (Y), C=yaw (Z).

    The rotations are applied as intrinsic ``z-y'-x''`` (yaw, then pitch, then roll),
    which is equivalent to extrinsic ``x-y-z``.

    see https://reference.opcfoundation.org/specs/OPC-10000-210/b-2
    """

    a: float = 0.0
    """Rotation around x axis (roll)"""
    b: float = 0.0
    """Rotation around y axis (pitch)"""
    c: float = 0.0
    """Rotation around z axis (yaw)"""
    unit: Unit = Unit.DEGREE_UNIT_OF_ANGLE

    def __post_init__(self) -> None:
        """Verify unit post initialization."""
        _require_supported(self.unit, _ANGLE)

    def to(self, unit: Unit) -> Orientation:
        """Convert this orientation to one with given ``unit``."""
        if unit == self.unit:
            return self
        f = _angle_factor(self.unit, unit)
        return Orientation(f * self.a, f * self.b, f * self.c, unit)

    def as_tuple(self) -> tuple[float, float, float]:
        """Return ``(a, b, c)`` in this orientation's unit."""
        return self.a, self.b, self.c

    def is_close(self, other: Orientation, *, abs_tol: float = 1e-9) -> bool:
        """Approximate equality of the *rotation*, regardless of Euler representation."""
        return all(
            math.isclose(p, q, rel_tol=0.0, abs_tol=abs_tol)
            for p, q in zip(_matrix_of(self), _matrix_of(other), strict=True)
        )


@dataclass(frozen=True, slots=True)
class Pose:
    """Pose defined by Cartesian `Position` and angular `Orientation`.

    Corresponds to OPC UA data type ``3DFrameType``.
    """

    position: Position = Position()
    orientation: Orientation = Orientation()

    def with_position(self, position: Position) -> Pose:
        """Return a copy of this Pose with given ``position`` keeping the orientation."""
        return replace(self, position=position)

    def with_orientation(self, orientation: Orientation) -> Pose:
        """Return a copy of this Pose with given ``orientation`` keeping the position."""
        return replace(self, orientation=orientation)

    def __matmul__(self, other: Pose) -> Pose:
        """Compose two poses.

        ``other`` is expressed in this pose's frame; the result is expressed in this
        pose's parent frame, in this pose's units::

            position    = self.position + R_self · other.position
            orientation = R_self · R_other

        The resulting Euler angles describe an equivalent rotation, but not necessarily
        the same triple one would compute by hand (gimbal lock, angle wrapping).
        Use `is_close` to compare poses.
        """
        unit = self.position.unit
        r = _matrix_of(self.orientation)
        dx, dy, dz = _rotate(r, other.position.to(unit).as_tuple())
        x, y, z = self.position.as_tuple()
        return Pose(
            Position(x + dx, y + dy, z + dz, unit),
            _orientation_from(_matmul(r, _matrix_of(other.orientation)), self.orientation.unit),
        )

    def inverse(self) -> Pose:
        """Return the pose that undoes this one, so ``p @ p.inverse()`` is the identity."""
        rt = _transpose(_matrix_of(self.orientation))
        x, y, z = _rotate(rt, self.position.as_tuple())
        return Pose(
            Position(-x, -y, -z, self.position.unit),
            _orientation_from(rt, self.orientation.unit),
        )

    def transform(self, point: Position) -> Position:
        """Express ``point`` (given in this pose's frame) in the parent frame."""
        unit = self.position.unit
        dx, dy, dz = _rotate(_matrix_of(self.orientation), point.to(unit).as_tuple())
        x, y, z = self.position.as_tuple()
        return Position(x + dx, y + dy, z + dz, unit)

    def is_close(self, other: Pose, *, rel_tol: float = 1e-9, abs_tol: float = 1e-9) -> bool:
        """Approximate equality, regardless of Euler representation."""
        return self.position.is_close(other.position, rel_tol=rel_tol, abs_tol=abs_tol) and (
            self.orientation.is_close(other.orientation, abs_tol=abs_tol)
        )

    def to_ua(self, *, length_unit: Unit, angle_unit: Unit) -> ua.ThreeDFrame:
        """Convert to a OPC UA ``3DFrame``, expressed in the given units."""
        p, o = self.position.to(length_unit), self.orientation.to(angle_unit)
        return ua.ThreeDFrame(
            CartesianCoordinates=ua.ThreeDCartesianCoordinates(X=p.x, Y=p.y, Z=p.z),  # type: ignore
            Orientation=ua.ThreeDOrientation(A=o.a, B=o.b, C=o.c),  # type: ignore
        )

    @classmethod
    def from_ua(cls, frame: ua.ThreeDFrame, *, length_unit: Unit, angle_unit: Unit) -> Pose:
        """Convert from ``ThreeDFrame`` whose numbers are in the given units."""
        p, o = frame.CartesianCoordinates, frame.Orientation
        return cls(
            position=Position(float(p.X), float(p.Y), float(p.Z), length_unit),
            orientation=Orientation(float(o.A), float(o.B), float(o.C), angle_unit),
        )
