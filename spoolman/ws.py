"""Websocket functionality."""

import logging

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from spoolman.api.v1.models import Event

logger = logging.getLogger(__name__)


class SubscriptionTree:
    """Subscription tree.

    This is a tree structure that allows us to efficiently send messages to
    all websockets that are subscribed to a certain pool of events.

    You can subscribe to different levels of the tree, for example:
    - ("vendor", "1") will subscribe to events for vendor 1
    - ("vendor") will subscribe to events for all vendors
    - () will subscribe to events for all vendors, filaments and spools
    """

    def __init__(self) -> None:
        """Initialize."""
        self.children: dict[str, SubscriptionTree] = {}
        self.subscribers: set[WebSocket] = set()

    def add(self, path: tuple[str, ...], websocket: WebSocket) -> None:
        """Add a websocket to the subscription tree."""
        if len(path) == 0:
            self.subscribers.add(websocket)
        else:
            if path[0] not in self.children:
                self.children[path[0]] = SubscriptionTree()
            self.children[path[0]].add(path[1:], websocket)

    def remove(self, path: tuple[str, ...], websocket: WebSocket) -> None:
        """Remove a websocket from the subscription tree."""
        if len(path) == 0:
            self.subscribers.remove(websocket)
        elif path[0] in self.children:
            self.children[path[0]].remove(path[1:], websocket)

    def has_any_subscriber(self) -> bool:
        """Whether this subtree contains at least one subscriber anywhere within it."""
        if self.subscribers:
            return True
        return any(child.has_any_subscriber() for child in self.children.values())

    async def send(self, path: tuple[str, ...], evt: Event) -> None:
        """Send a message to all websockets in this branch of the tree."""
        # Broadcast to all subscribers on this level. Dead sockets are collected and
        # discarded from THIS node after the loop (#230): removing inside the loop
        # mutated the set being iterated (aborting delivery to the remaining live
        # subscribers), and self.remove(path, ...) walked down the remaining path,
        # targeting the wrong node — the dead socket was never actually cleaned up.
        dead: list[WebSocket] = []
        for websocket in self.subscribers:
            if (
                websocket.client_state == WebSocketState.DISCONNECTED  # noqa: PLR1714
                or websocket.application_state == WebSocketState.DISCONNECTED
            ):
                # A bad disconnection may have occurred
                dead.append(websocket)
            elif (
                websocket.client_state == WebSocketState.CONNECTED
                and websocket.application_state == WebSocketState.CONNECTED
            ):
                # exclude_none mirrors the REST endpoints' response_model_exclude_none=True so that
                # websocket payloads and REST responses have an identical shape. Without this, unset
                # fields arrive as explicit `null` over the websocket but are omitted over REST, which
                # trips up clients that distinguish the two (e.g. the spool list's price fallback).
                await websocket.send_text(evt.json(exclude_none=True))

        for websocket in dead:
            self.subscribers.discard(websocket)
            logger.info(
                "Forcing disconnection of client %s",
                websocket.client.host if websocket.client else "?",
            )

        # Send the message further down the tree
        if len(path) > 0 and path[0] in self.children:
            await self.children[path[0]].send(path[1:], evt)


class WebsocketManager:
    """Websocket manager."""

    def __init__(self) -> None:
        """Initialize."""
        self.tree = SubscriptionTree()

    def connect(self, pool: tuple[str, ...], websocket: WebSocket) -> None:
        """Connect a websocket."""
        self.tree.add(pool, websocket)
        logger.info(
            "Client %s is now listening on pool %s",
            websocket.client.host if websocket.client else "?",
            ",".join(pool),
        )

    def disconnect(self, pool: tuple[str, ...], websocket: WebSocket) -> None:
        """Disconnect a websocket."""
        self.tree.remove(pool, websocket)
        logger.info(
            "Client %s has stopped listening on pool %s",
            websocket.client.host if websocket.client else "?",
            ",".join(pool),
        )

    async def send(self, pool: tuple[str, ...], evt: Event) -> None:
        """Send a message to all websockets in a pool."""
        await self.tree.send(pool, evt)

    def has_subscribers(self, pool: tuple[str, ...]) -> bool:
        """Whether an event published on `pool` would reach any subscriber.

        True if a subscriber sits on an ancestor of `pool` (including the root, which receives every
        event), on `pool` itself, or anywhere in the subtree beneath it. Used to skip the #130
        dependency fan-out entirely when nobody is listening for spool events.
        """
        node = self.tree
        if node.subscribers:  # root subscribers receive everything
            return True
        for part in pool:
            child = node.children.get(part)
            if child is None:
                return False
            node = child
            if node.subscribers:
                return True
        return node.has_any_subscriber()


websocket_manager = WebsocketManager()
