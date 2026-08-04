from typing import cast

import pytest
from fastapi.testclient import TestClient

from tests.conftest import EVENT_ID, webhook_body
from tgtn.__main__ import create_app
from tgtn.core.config import Settings
from tgtn.core.outbox import Outbox
from tgtn.core.store import Incoming, Store
from tgtn.handlers.notification import router as notification_router


class FakeStore:
    def __init__(self, *, accepts: bool = True) -> None:
        self.accepts = accepts
        self.queued: list[Incoming] = []

    async def enqueue(self, message: Incoming) -> bool:
        self.queued.append(message)
        return self.accepts


class FakeOutbox:
    def __init__(self) -> None:
        self.wakeups = 0

    def notify(self) -> None:
        self.wakeups += 1


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def outbox() -> FakeOutbox:
    return FakeOutbox()


@pytest.fixture
def client(settings: Settings, store: FakeStore, outbox: FakeOutbox) -> TestClient:
    app = create_app(settings, routers=(notification_router,))
    app.state.store = cast(Store, store)
    app.state.outbox = cast(Outbox, outbox)
    return TestClient(app)


def test_inbound_message_is_queued_and_wakes_the_worker(
    client: TestClient, store: FakeStore, outbox: FakeOutbox
) -> None:
    # Act
    response = client.post("/notification", json=webhook_body())

    # Assert
    assert response.status_code == 202
    assert response.json() == {"status": "queued"}
    assert outbox.wakeups == 1
    queued = store.queued[0]
    assert queued.event_id == EVENT_ID
    assert queued.sender == "+15551110000"
    assert queued.recipient == "+15552220000"
    assert queued.body == "код 1234"


def test_repeated_delivery_is_reported_as_duplicate_without_waking_the_worker(
    settings: Settings, outbox: FakeOutbox
) -> None:
    # Arrange: хранилище отвечает, что такой event_id уже принят.
    app = create_app(settings, routers=(notification_router,))
    app.state.store = cast(Store, FakeStore(accepts=False))
    app.state.outbox = cast(Outbox, outbox)

    # Act
    response = TestClient(app).post("/notification", json=webhook_body())

    # Assert
    assert response.status_code == 202
    assert response.json() == {"status": "duplicate"}
    assert outbox.wakeups == 0


def test_outbound_event_on_the_same_url_is_ignored(client: TestClient, store: FakeStore) -> None:
    # Arrange
    body = webhook_body()
    body["data"]["event_type"] = "message.sent"

    # Act
    response = client.post("/notification", json=body)

    # Assert
    assert response.json() == {"status": "ignored"}
    assert store.queued == []


def test_outbound_direction_is_ignored_even_under_the_inbound_event(client: TestClient, store: FakeStore) -> None:
    # Arrange
    body = webhook_body(payload={"direction": "outbound"})

    # Act
    response = client.post("/notification", json=body)

    # Assert
    assert response.json() == {"status": "ignored"}
    assert store.queued == []


def test_failover_url_queues_the_same_way(client: TestClient, store: FakeStore) -> None:
    # Act
    response = client.post("/failure", json=webhook_body())

    # Assert
    assert response.status_code == 202
    assert response.json() == {"status": "queued"}
    assert store.queued[0].event_id == EVENT_ID


def test_media_urls_travel_with_the_message(client: TestClient, store: FakeStore) -> None:
    # Arrange
    body = webhook_body(
        payload={
            "text": None,
            "type": "MMS",
            "media": [
                {"url": "https://example.com/a.png", "content_type": "image/png"},
                {"url": "https://example.com/b.png", "content_type": "image/png"},
            ],
        }
    )

    # Act
    client.post("/notification", json=body)

    # Assert
    queued = store.queued[0]
    assert queued.body == ""
    assert queued.media == "https://example.com/a.png\nhttps://example.com/b.png"


def test_body_without_the_expected_fields_is_rejected(client: TestClient, store: FakeStore) -> None:
    # Act
    response = client.post("/notification", json={"data": {"event_type": "message.received"}})

    # Assert
    assert response.status_code == 422
    assert store.queued == []


def test_message_without_a_recipient_still_gets_queued(client: TestClient, store: FakeStore) -> None:
    # Arrange: список `to` пуст — сообщение всё равно нельзя терять.
    body = webhook_body(payload={"to": []})

    # Act
    response = client.post("/notification", json=body)

    # Assert
    assert response.json() == {"status": "queued"}
    assert store.queued[0].recipient == "—"
