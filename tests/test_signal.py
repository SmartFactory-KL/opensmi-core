# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

import pytest

from opensmi.core import Signal


@pytest.mark.asyncio
async def test_send_calls_connected_callbacks() -> None:
    signal: Signal[[int]] = Signal()
    received: list[int] = []

    async def callback(value: int) -> None:
        received.append(value)

    signal.connect(callback)

    await signal.send(42)

    assert received == [42]


@pytest.mark.asyncio
async def test_multiple_callbacks_are_called() -> None:
    signal: Signal[[int]] = Signal()
    received: list[int] = []

    async def first(value: int) -> None:
        received.append(value)

    async def second(value: int) -> None:
        received.append(value * 2)

    signal.connect(first)
    signal.connect(second)

    await signal.send(3)

    assert sorted(received) == [3, 6]


@pytest.mark.asyncio
async def test_disconnect() -> None:
    signal: Signal[[int]] = Signal()
    received: list[int] = []

    async def callback(value: int) -> None:
        received.append(value)

    signal.connect(callback)
    signal.disconnect(callback)

    await signal.send(42)

    assert received == []


@pytest.mark.asyncio
async def test_disconnect_missing_callback_is_safe() -> None:
    signal: Signal[[int]] = Signal()

    async def callback(value: int) -> None:
        pass

    signal.disconnect(callback)


@pytest.mark.asyncio
async def test_connect_same_callback_twice_only_calls_once() -> None:
    signal: Signal[[int]] = Signal()
    received: list[int] = []

    async def callback(value: int) -> None:
        received.append(value)

    signal.connect(callback)
    signal.connect(callback)

    await signal.send(42)

    assert received == [42]


@pytest.mark.asyncio
async def test_disconnect_during_callback() -> None:
    signal: Signal = Signal()
    received: list[str] = []

    async def first() -> None:
        received.append("first")
        signal.disconnect(second)

    async def second() -> None:
        received.append("second")

    signal.connect(first)
    signal.connect(second)

    await signal.send()

    assert sorted(received) == ["first", "second"]

    await signal.send()

    assert sorted(received) == ["first", "first", "second"]


@pytest.mark.asyncio
async def test_connect_during_callback() -> None:
    signal = Signal()
    received: list[str] = []

    async def first() -> None:
        received.append("first")
        signal.connect(second)

    async def second() -> None:
        received.append("second")

    signal.connect(first)

    await signal.send()
    assert received == ["first"]

    await signal.send()
    assert sorted(received) == ["first", "first", "second"]


@pytest.mark.asyncio
async def test_keyword_arguments() -> None:
    signal = Signal()
    received: tuple[int, str] | None = None

    async def callback(value: int, name: str) -> None:
        nonlocal received
        received = (value, name)

    signal.connect(callback)

    await signal.send(42, name="test")  # works, but not supported for type checks :/

    assert received == (42, "test")
