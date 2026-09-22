from data.db.market_store import MarketStore


def test_notification_subscriptions_are_persistent_and_idempotent(tmp_path) -> None:
    store = MarketStore(tmp_path / "market.db")
    store.initialize()

    assert store.subscribe_notifications(123) is True
    assert store.subscribe_notifications(123) is False
    assert store.subscribe_notifications(-456) is True
    assert store.notification_chat_ids() == (123, -456)
    assert store.unsubscribe_notifications(123) is True
    assert store.unsubscribe_notifications(123) is False
    assert store.notification_chat_ids() == (-456,)
