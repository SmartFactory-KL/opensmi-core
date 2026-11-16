# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Event routing of the SubscriptionManager across an asyncua auto-reconnect.

On reconnect asyncua recreates the subscription and the server assigns new monitored item ids.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from asyncua import Client, Server, ua
from asyncua.common.node import Node
from asyncua.common.subscription import DataChangeNotif
from structlog.testing import capture_logs

from opensmi.core.protocols import UaEvent
from opensmi.core.subscription_manager import SubscriptionManager, UaDataChangeSubscriber, UaEventSubscriber

_NS_URI = "urn:opensmi:test:reconnect"
_MACHINE_ID = "Machine"
_VALUE_ID = "Machine.Value"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _TestServer:
    def __init__(self, port: int) -> None:
        self.url = f"opc.tcp://127.0.0.1:{port}/"
        self._server: Server | None = None
        self._machine: Node | None = None

    async def start(self) -> None:
        server = Server()
        await server.init()
        server.set_endpoint(self.url)
        idx = await server.register_namespace(_NS_URI)
        machine = await server.nodes.objects.add_object(ua.NodeId(_MACHINE_ID, idx), "Machine")
        await machine.write_attribute(ua.AttributeIds.EventNotifier, ua.DataValue(ua.Variant(1, ua.VariantType.Byte)))
        await machine.add_variable(ua.NodeId(_VALUE_ID, idx), "Value", 0)
        await server.start()
        self._server, self._machine = server, machine

    async def stop(self) -> None:
        if self._server is not None:
            await self._server.stop()
            self._server = None

    async def fire_event(self, message: str) -> None:
        assert self._server is not None
        assert self._machine is not None
        generator = await self._server.get_event_generator(emitting_node=self._machine)
        generator.event.Message = ua.LocalizedText(message)
        await generator.trigger()


class _EventRecorder(UaEventSubscriber):
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def ua_on_event(self, ua_event: UaEvent) -> None:
        self.messages.append(ua_event.Message.Text)  # pyright: ignore[reportAttributeAccessIssue]


class _NoopDataSubscriber(UaDataChangeSubscriber):
    async def ua_on_data_change(self, node: Node, val: Any, data: DataChangeNotif) -> None:
        pass


async def _wait_for_message(recorder: _EventRecorder, server: _TestServer, message: str, seconds: float) -> bool:
    """Fire ``message`` repeatedly until it arrives; the client may still be reconnecting."""
    try:
        async with asyncio.timeout(seconds):
            while message not in recorder.messages:
                with contextlib.suppress(Exception):
                    await server.fire_event(message)
                await asyncio.sleep(0.5)
    except TimeoutError:
        return False
    return True


@pytest_asyncio.fixture
async def server() -> AsyncIterator[_TestServer]:
    test_server = _TestServer(_free_port())
    await test_server.start()
    yield test_server
    await test_server.stop()


@pytest.mark.asyncio
@pytest.mark.timeout(90)
async def test_events_are_routed_after_reconnect(server: _TestServer) -> None:
    client = Client(server.url, watchdog_intervall=0.5, reconnect_max_delay=1.0)
    await client.connect(auto_reconnect=True)
    manager = SubscriptionManager(ua_client=client)
    try:
        await manager.init()
        idx = await client.get_namespace_index(_NS_URI)

        # Leave a gap in the server's monitored item ids, so the recreated event item gets a different id.
        data_subscriber = _NoopDataSubscriber()
        value_node = client.get_node(ua.NodeId(_VALUE_ID, idx))
        await manager.subscribe_data_change(data_subscriber, value_node)
        recorder = _EventRecorder()
        await manager.subscribe_event(recorder, ua.NodeId(_MACHINE_ID, idx))
        await manager.unsubscribe_data_change(data_subscriber, value_node)

        assert await _wait_for_message(recorder, server, "before", seconds=10)

        # Server restart: the session is gone, so asyncua has to recreate the subscription.
        await server.stop()
        await server.start()

        assert await _wait_for_message(recorder, server, "after", seconds=30), "no events after reconnect"

        with capture_logs() as logs:
            await manager.unsubscribe_event(recorder, ua.NodeId(_MACHINE_ID, idx))
        assert not [log for log in logs if log["log_level"] == "warning"], "deleted a stale monitored item ID"
    finally:
        await manager.shutdown()
        await client.disconnect()
