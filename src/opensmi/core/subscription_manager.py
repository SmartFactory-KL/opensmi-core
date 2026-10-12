# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

import asyncio
import contextlib
import time
from abc import ABC, abstractmethod
from asyncio import Task
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Generic, Never, TypeVar

import structlog
from asyncua import ua
from asyncua.client.client import Client
from asyncua.common.node import Node
from asyncua.common.subscription import DataChangeNotif, Subscription
from asyncua.ua import NodeId, UaStatusCodeError
from asyncua.ua.uaerrors import BadAttributeIdInvalid

from opensmi.core.protocols import UaEvent


class UaDataChangeSubscriber(ABC):
    """Interface for OPC UA data change subscribers."""

    @abstractmethod
    async def ua_on_data_change(self, node: Node, val: Any, data: DataChangeNotif) -> None:
        """Handle OPC UA node data change notification."""


class UaEventSubscriber(ABC):
    """Interface for OPC UA event subscribers."""

    @abstractmethod
    async def ua_on_event(self, ua_event: UaEvent) -> None:
        """Handle OPC UA event notification."""


_HandlerType = TypeVar("_HandlerType")


@dataclass
class _MonitoredItem(Generic[_HandlerType]):
    handle: int | None
    """Handle as returned by ``asyncua``. Is ``None`` when renew failed."""
    handlers: list[_HandlerType] = field(default_factory=list)


class SubscriptionManager:
    """Centrally manages all OPC UA subscription needs.

    It bundles subscriptions using only one subscription to an OPC UA server
    to stay within max. subscription limits of certain OPC UA servers.
    """

    _ua_client: Client
    _ua_subscription: Subscription

    def __init__(
        self,
        *,
        ua_client: Client,
        publishing_interval_ms: float = 100,
        heartbeat_stale_after: float = 10.0,
    ) -> None:
        """Create a new instance.

        :param ua_client: OPC UA client to use.
        :param publishing_interval_ms: Publishing interval in milliseconds for OPC UA subscription
        :param heartbeat_stale_after: Time in seconds until any subscription should be received.
        """
        self._publishing_interval_ms = publishing_interval_ms
        self._ua_client = ua_client

        self._data_subscription_map: dict[NodeId, _MonitoredItem[UaDataChangeSubscriber]] = {}
        """ Maps a OPC UA node to a handle and a list of handlers for data change notifications. """
        self._event_subscription_map: dict[NodeId, _MonitoredItem[UaEventSubscriber]] = {}
        """ Maps a OPC UA node to a handle and a list of handlers for event notifications. """

        self._heartbeat_task: Task[Never] | None = None
        self._last_heartbeat = time.monotonic()
        self._heartbeat_stale_after = heartbeat_stale_after

        self.logger = structlog.getLogger("opensmi.SubscriptionManager")

    async def _create_subscription(self) -> None:
        self._ua_subscription = await self._ua_client.create_subscription(
            period=self._publishing_interval_ms, handler=self
        )
        self.logger.info("Created subscription!", parameters=self._ua_subscription.parameters)

    async def init(self) -> None:
        """Create the subscription and start heartbeat monitoring.

        Must be called once before any ``subscribe_*`` method.
        """
        if self._heartbeat_task is not None:
            return

        await self._create_subscription()

        # subscribe to a node that always changes reliably, for example the current time of the server
        # this is done to prevent the subscription from timing out
        current_time_node = self._ua_client.get_node(ua.object_ids.ObjectIds.Server_ServerStatus_CurrentTime)
        await self.subscribe_data_change(self, current_time_node)  # pyright: ignore[reportArgumentType]

        self._last_heartbeat = time.monotonic()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(), name="heartbeat_task")
        self.logger.info("Subscription manager initialized")

    async def shutdown(self) -> None:
        """Stop heartbeat monitoring and delete the OPC UA subscription."""
        # Stop the heartbeat first, so it can't start renewing subscriptions while shutting down
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None

        await self.clear_subscriptions()
        self.logger.info("Subscription manager shut down")

    # TODO(CaHa): What about the subscriptions that could not be renewed?

    async def _renew_data_change_subscriptions(self) -> None:
        for node_id, monitored_item in list(self._data_subscription_map.items()):
            try:
                handle = await self._ua_subscription.subscribe_data_change(self._ua_client.get_node(node_id))
                monitored_item.handle = handle
            except UaStatusCodeError as err:
                monitored_item.handle = None
                self.logger.warning("Could not renew data change subscription", node=node_id.to_string(), reason=err)

    async def _renew_event_subscriptions(self) -> None:
        for node_id, monitored_item in list(self._event_subscription_map.items()):
            try:
                handle = await self._ua_subscription.subscribe_events(node_id)
                monitored_item.handle = handle
            except UaStatusCodeError as err:
                monitored_item.handle = None
                self.logger.warning("Could not renew event subscription", node=node_id.to_string(), reason=err)

    async def _renew_subscriptions(self) -> None:
        self.logger.info("Trying to renew subscriptions...", count=self.no_of_monitored_items)
        await self._delete_subscription()

        while True:
            try:
                await self._create_subscription()
                await self._renew_data_change_subscriptions()
                await self._renew_event_subscriptions()
                self._last_heartbeat = time.monotonic()
                self.logger.info("Successfully renewed subscriptions")
                break
            except Exception as err:
                self.logger.warning("Could not renew subscriptions!", reason=err)
                await self._delete_subscription()
                await asyncio.sleep(1)

    def _invalidate_subscription_handles(self) -> None:
        for item in self._data_subscription_map.values():
            item.handle = None
        for item in self._event_subscription_map.values():
            item.handle = None

    async def _delete_subscription(self) -> None:
        """Best-effort deletion of the server-side subscription; the maps are left untouched."""
        self._invalidate_subscription_handles()
        try:
            await self._ua_subscription.delete()
            self.logger.info("Deleted main OPC UA subscription!")
        except (ConnectionError, AttributeError):
            pass  # connection is gone or there is no subscription to delete
        except Exception as err:
            self.logger.exception("Could not delete main OPC UA subscription!", reason=err)
        with contextlib.suppress(NameError, AttributeError):
            del self._ua_subscription

    async def clear_subscriptions(self) -> None:
        """Delete the OPC UA subscription and forget all registered handlers."""
        self.logger.info("Clearing subscriptions...", count=self.no_of_monitored_items)
        await self._delete_subscription()
        self._data_subscription_map.clear()
        self._event_subscription_map.clear()

    @property
    def no_of_monitored_items(self) -> int:
        """Return the number of monitored nodes."""
        return len(self._data_subscription_map) + len(self._event_subscription_map)

    async def subscribe_data_change(
        self, handler: UaDataChangeSubscriber, nodes: Node | NodeId | Iterable[Node | NodeId]
    ) -> None:
        """Add given handler to receive data change notifications for given nodes."""
        if not isinstance(nodes, Iterable):
            nodes = [nodes]  # create a list out of the given single node or node id

        for node in nodes:
            if isinstance(node, NodeId):
                node = self._ua_client.get_node(node)

            if node.nodeid not in self._data_subscription_map:
                try:
                    handle = await self._ua_subscription.subscribe_data_change(node)
                    self._data_subscription_map[node.nodeid] = _MonitoredItem(handle=handle, handlers=[handler])
                    self.logger.debug(
                        "Added data change handler", handler=handler, node=node.nodeid.to_string(), handle=handle
                    )
                except BadAttributeIdInvalid:
                    self.logger.warning("Node does not support subscription!", node=node.nodeid.to_string())
                except UaStatusCodeError as err:
                    self.logger.exception("Unexpected UA error!", err=err)
            else:
                # We only need 1 subscription for n handlers.
                self.logger.debug(
                    "Added data change handler, reusing existing subscription.",
                    handler=handler,
                    node=node.nodeid.to_string(),
                )
                self._data_subscription_map[node.nodeid].handlers.append(handler)

    async def subscribe_event(self, handler: UaEventSubscriber, source_node: Node | NodeId) -> None:
        """Add given handler to receive event notifications for given node."""
        # we only get the node ID in the notification
        if isinstance(source_node, Node):
            node_id: NodeId = source_node.nodeid
        elif isinstance(source_node, NodeId):
            node_id = source_node
        else:
            msg = f"Given source_node {source_node} is not supported!"
            raise TypeError(msg)

        if node_id not in self._event_subscription_map:
            handle = await self._ua_subscription.subscribe_events(sourcenode=source_node)
            self._event_subscription_map[node_id] = _MonitoredItem(handle=handle, handlers=[handler])
            self.logger.debug("Added event handler", handler=handler, node=node_id.to_string(), handle=handle)
        else:
            # We only need 1 subscription for n handlers.
            self.logger.debug(
                "Added event handler, reusing existing subscription.", handler=handler, node=node_id.to_string()
            )
            self._event_subscription_map[node_id].handlers.append(handler)

    async def unsubscribe_data_change(
        self, handler: UaDataChangeSubscriber, nodes: Node | NodeId | Iterable[Node | NodeId]
    ) -> None:
        """Remove handler for given nodes; removes server subscription once it has no handlers left."""
        if not isinstance(nodes, Iterable):
            nodes = [nodes]

        for node in nodes:
            node_id = node.nodeid if isinstance(node, Node) else node
            await self._unsubscribe(handler=handler, node_id=node_id, subscription_map=self._data_subscription_map)

    async def unsubscribe_event(self, handler: UaEventSubscriber, source_node: Node | NodeId) -> None:
        """Remove handler for events of given node; removes server subscription once it has no handlers left."""
        node_id = source_node.nodeid if isinstance(source_node, Node) else source_node
        await self._unsubscribe(handler=handler, node_id=node_id, subscription_map=self._event_subscription_map)

    async def _unsubscribe(
        self,
        *,
        handler: _HandlerType,
        node_id: NodeId,
        subscription_map: dict[NodeId, _MonitoredItem[_HandlerType]],
    ) -> None:
        item = subscription_map.get(node_id)
        if item is None or handler not in item.handlers:
            return  # nothing to do

        item.handlers.remove(handler)

        if len(item.handlers) > 0:
            return  # other handlers still need the monitored item

        del subscription_map[node_id]
        if item.handle is None:
            return  # nothing to unsubscribe

        try:
            await self._ua_subscription.unsubscribe(item.handle)
        except (UaStatusCodeError, ConnectionError) as err:
            self.logger.warning("Could not delete monitored item", node=node_id.to_string(), reason=err)

    async def _heartbeat_loop(self) -> Never:
        while True:
            await asyncio.sleep(self._heartbeat_stale_after / 4)
            try:
                stale_for = time.monotonic() - self._last_heartbeat
                if stale_for > self._heartbeat_stale_after:
                    self.logger.warning("Heartbeat stale, subscriptions presumed dead", stale_for=stale_for)
                    await self._renew_subscriptions()
            except Exception as err:
                self.logger.warning("Heartbeat check failed", reason=err)

    ###########################################
    # asyncua callbacks

    async def datachange_notification(self, node: Node, val: Any, data: DataChangeNotif) -> None:
        """Handle OPC UA data change notifications callback."""
        self._last_heartbeat = time.monotonic()

        item = self._data_subscription_map.get(node.nodeid)
        if item is None:
            self.logger.warning(
                "Received DataChange Notification with no handlers", key=node.nodeid.to_string(), value=val
            )
            return

        for handler in list(item.handlers):  # copy, to guard against unsubscription during iteration
            if handler is self:
                continue  # current time, not required for anything specific
            try:
                await handler.ua_on_data_change(node, val, data)
            except Exception as err:
                self.logger.warning("Data change handler failed", handler=handler, reason=err)

    async def status_change_notification(self, status: ua.StatusChangeNotification) -> None:
        """Handle OPC UA status notifications callback."""
        self.logger.info("Received status change notification", status=status)

    async def event_notification(self, ua_event: UaEvent) -> None:
        """Handle OPC UA event notifications callback."""
        self._last_heartbeat = time.monotonic()

        # TODO(CaHa): ua_event.emitting_node is always i=2253 (=Server)
        # might be an asyncua problem
        item = self._event_subscription_map.get(ua_event.SourceNode)
        if item is None:
            self.logger.warning("Received Event Notification with no handlers", ua_event=ua_event)
            return

        for handler in list(item.handlers):  # copy, to guard against unsubscription during iteration
            try:
                await handler.ua_on_event(ua_event)
            except Exception as err:
                self.logger.warning("Event handler failed", handler=handler, reason=err)
