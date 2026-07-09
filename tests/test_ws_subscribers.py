"""Unit tests for WebsocketManager.has_subscribers, the gate for the #130 dependency fan-out.

A filament/vendor edit only fans out synthetic spool events when a spool event could actually reach
someone, so this predicate must be exact: it is true for a root subscriber (receives everything), an
all-spools subscriber, a specific-spool subscriber, and false when only unrelated pools are watched.
"""

from spoolman.ws import WebsocketManager


class _FakeWS:
    """Stand-in websocket; only needs object identity to live in the subscriber set.

    `client` is read by the manager's connect/disconnect logging (allowed to be None).
    """

    client = None


def test_no_subscribers_at_all():
    assert WebsocketManager().has_subscribers(("spool",)) is False


def test_root_subscriber_receives_every_pool():
    m = WebsocketManager()
    m.connect((), _FakeWS())
    assert m.has_subscribers(("spool",)) is True
    assert m.has_subscribers(("spool", "5")) is True
    assert m.has_subscribers(("filament", "1")) is True


def test_all_spools_subscriber():
    m = WebsocketManager()
    m.connect(("spool",), _FakeWS())
    assert m.has_subscribers(("spool",)) is True


def test_specific_spool_subscriber_counts_for_the_spool_pool():
    m = WebsocketManager()
    m.connect(("spool", "5"), _FakeWS())
    # A fan-out decision on the whole spool pool must see the deeper specific subscriber.
    assert m.has_subscribers(("spool",)) is True


def test_only_unrelated_pool_subscribed():
    m = WebsocketManager()
    m.connect(("filament", "3"), _FakeWS())
    assert m.has_subscribers(("spool",)) is False


def test_becomes_false_again_after_disconnect():
    m = WebsocketManager()
    ws = _FakeWS()
    m.connect(("spool", "5"), ws)
    assert m.has_subscribers(("spool",)) is True
    m.disconnect(("spool", "5"), ws)
    assert m.has_subscribers(("spool",)) is False
