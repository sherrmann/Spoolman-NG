"""Unit tests for SubscriptionTree.send dead-socket cleanup (#230).

The old cleanup called self.remove(path, websocket) from inside the subscriber loop, which
(a) on the terminal node mutated the set being iterated - RuntimeError, aborting delivery to
the remaining live subscribers - and (b) on an ancestor node walked *down* the remaining path
and removed at the wrong node (KeyError when the deeper node existed, silent leak otherwise).
Dead sockets must be collected during iteration and discarded from the current node after it.
"""

from starlette.websockets import WebSocketState

from spoolman.ws import WebsocketManager


class _FakeWS:
    """Stand-in websocket with controllable connection state and a send recorder."""

    client = None

    def __init__(self, *, dead: bool = False) -> None:
        state = WebSocketState.DISCONNECTED if dead else WebSocketState.CONNECTED
        self.client_state = state
        self.application_state = state
        self.sent: list[str] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(text)


class _FakeEvent:
    """Duck-typed Event; send() only calls .json()."""

    def json(self, **_kwargs: object) -> str:
        return "{}"


async def test_sole_dead_subscriber_is_removed_without_erroring():
    m = WebsocketManager()
    dead = _FakeWS(dead=True)
    m.connect(("spool", "5"), dead)

    await m.send(("spool", "5"), _FakeEvent())  # old code: RuntimeError (set mutated mid-iteration)

    assert m.has_subscribers(("spool", "5")) is False  # actually cleaned up


async def test_dead_ancestor_subscriber_does_not_break_delivery_to_deeper_node():
    m = WebsocketManager()
    dead_all_spools = _FakeWS(dead=True)
    live_specific = _FakeWS()
    m.connect(("spool",), dead_all_spools)
    m.connect(("spool", "5"), live_specific)

    await m.send(("spool", "5"), _FakeEvent())  # old code: KeyError (removed at the wrong node)

    assert live_specific.sent == ["{}"]
    # The dead ancestor is gone from its own node; the live deeper subscriber remains.
    assert m.has_subscribers(("spool", "9")) is False
    assert m.has_subscribers(("spool", "5")) is True


async def test_live_sibling_still_receives_when_a_dead_socket_shares_the_node():
    m = WebsocketManager()
    dead = _FakeWS(dead=True)
    live = _FakeWS()
    m.connect(("spool", "5"), dead)
    m.connect(("spool", "5"), live)

    await m.send(("spool", "5"), _FakeEvent())

    assert live.sent == ["{}"]
    await m.send(("spool", "5"), _FakeEvent())
    assert live.sent == ["{}", "{}"]


async def test_dead_socket_stops_reappearing_on_subsequent_sends():
    m = WebsocketManager()
    dead = _FakeWS(dead=True)
    m.connect(("spool",), dead)

    await m.send(("spool", "5"), _FakeEvent())
    await m.send(("spool", "5"), _FakeEvent())  # old code: leaked and re-triggered every send

    assert m.has_subscribers(("spool",)) is False
