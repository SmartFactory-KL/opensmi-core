# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

import contextlib
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

import structlog
from asyncua import ua
from asyncua.client.client import Client
from asyncua.common.node import Node
from asyncua.common.subscription import DataChangeNotif, Subscription
from asyncua.ua import NodeId, UaStatusCodeError
from asyncua.ua.uaerrors import BadAttributeIdInvalid

from open_smi_common.protocols import UaEvent


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


class SubscriptionManager:
    """Centrally manages all OPC UA subscription needs.

    It bundles subscriptions using only one subscription to an OPC UA server
    to not stay within max. subscription limits of certain OPC UA servers.
    """

    _ua_client: Client
    _ua_subscription: Subscription

    def __init__(self) -> None:
        """Create a new instance."""
        self._data_subscription_map: dict[NodeId, list[UaDataChangeSubscriber]] = {}
        """ Maps a OPC UA node to a list of handlers for data change notifications. """
        self._event_subscription_map: dict[NodeId, list[UaEventSubscriber]] = {}
        """ Maps a OPC UA node to a list of handlers for event notifications. """

        self.period: float = 100
        """Publishing interval in milliseconds for OPC UA subscription."""

        self.logger = structlog.getLogger("open_smi.SubscriptionManager")

    async def _create_subscription(self, ua_client: Client):
        self._ua_subscription = await ua_client.create_subscription(period=self.period, handler=self)
        self.logger.info("Created subscription!", parameters=self._ua_subscription.parameters)

    async def init(self, ua_client: Client, period: float = 100) -> None:
        self.period = period
        self._ua_client = ua_client
        await self._create_subscription(ua_client)

        # subscribe to a node that always changes reliably, for example the current time of the server
        # this is done to prevent the subscription from timing out
        current_time_node = ua_client.get_node(ua.object_ids.ObjectIds.Server_ServerStatus_CurrentTime)
        await self.subscribe_data_change(self, current_time_node)  # pyright: ignore[reportArgumentType]

    # async def renew_subscriptions(self, ua_client: Client) -> None:
    #     self.logger.info(f"Renewing {self.no_of_monitored_items} subscriptions...")
    #     old_data_subscription_map = self._data_subscription_map.copy()
    #     old_event_subscription_map = self._event_subscription_map.copy()
    #
    #     await self.clear_subscriptions()
    #     await self._create_subscription(ua_client)
    #
    #     # add all old data change subscriptions back
    #     for node_id, handlers in old_data_subscription_map.items():
    #         for handler in handlers:
    #             await self.subscribe_data_change(handler=handler, nodes=[ua_client.get_node(node_id)])
    #
    #     # add all old event subscriptions back
    #     for node_id, handlers in old_event_subscription_map.items():
    #         for handler in handlers:
    #             await self.subscribe_event(handler=handler, source_node=node_id)

    async def clear_subscriptions(self) -> None:
        self.logger.info(f"Clearing {self.no_of_monitored_items} subscriptions...")
        try:
            await self._ua_subscription.delete()
            self.logger.info("Deleted main OPC UA subscription!")
        except ConnectionError:
            pass  # we can safely ignore it since is no longer relevant
        except AttributeError:
            pass  # we can safely ignore it since there is no subscription to delete
        except Exception as err:
            self.logger.exception("Could not delete main OPC UA subscription!", reason=err)

        with contextlib.suppress(NameError, AttributeError):
            del self._ua_subscription

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
                self._data_subscription_map[node.nodeid] = []
                try:
                    await self._ua_subscription.subscribe_data_change(node)
                    self._data_subscription_map[node.nodeid].append(handler)
                    self.logger.debug("Added data change handler", handler=handler, node=node.nodeid.to_string())
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
                self._data_subscription_map[node.nodeid].append(handler)

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

        if source_node not in self._event_subscription_map:
            self._event_subscription_map[node_id] = []

        await self._ua_subscription.subscribe_events(sourcenode=source_node)
        self._event_subscription_map[node_id].append(handler)

    ###########################################
    # asyncua callbacks

    async def datachange_notification(self, node: Node, val: Any, data: DataChangeNotif) -> None:
        """Handle OPC UA data change notifications callback."""
        try:
            for handler in self._data_subscription_map[node.nodeid]:  # list of handlers
                if handler == self:
                    continue  # current time, not required for anything specific
                await handler.ua_on_data_change(node, val, data)
        except KeyError:
            self.logger.warning(
                "Received DataChange Notification with no handlers", key=node.nodeid.to_string(), value=val
            )

    async def status_change_notification(self, status: ua.StatusChangeNotification) -> None:
        """Handle OPC UA status notifications callback."""
        self.logger.info("Received status change notification", status=status)

    async def event_notification(self, ua_event: UaEvent) -> None:
        """Handle OPC UA event notifications callback."""
        # TODO(CaHa): ua_event.emitting_node is always i=2253 (=Server)
        # might be an asyncua problem
        try:
            for handler in self._event_subscription_map[ua_event.SourceNode]:
                await handler.ua_on_event(ua_event)
        except KeyError:
            self.logger.warning("Received Event Notification with no handlers", ua_event=ua_event)
