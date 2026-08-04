from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tgtn.modules.store import Incoming, Store


def incoming(event_id: str = "evt-1", **overrides: object) -> Incoming:
    base: dict[str, object] = {
        "event_id": event_id,
        "sender": "+15551110000",
        "recipient": "+15552220000",
        "body": "привет",
    }
    return Incoming(**(base | overrides))  # type: ignore[arg-type]


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "queue.sqlite3"


@pytest.mark.asyncio
async def test_accepted_message_becomes_the_head_of_the_queue(db_path: Path) -> None:
    async with Store(db_path) as store:
        # Act
        accepted = await store.enqueue(incoming())

        # Assert
        head = await store.head()
        assert accepted is True
        assert head is not None
        assert head.event_id == "evt-1"
        assert head.attempts == 0


@pytest.mark.asyncio
async def test_repeated_delivery_of_the_same_event_is_not_queued_twice(db_path: Path) -> None:
    async with Store(db_path) as store:
        # Arrange
        await store.enqueue(incoming("evt-repeat"))

        # Act
        second = await store.enqueue(incoming("evt-repeat"))

        # Assert
        assert second is False
        counters = await store.counters()
        assert counters.pending == 1


@pytest.mark.asyncio
async def test_sent_message_leaves_the_queue_and_counts_as_sent(db_path: Path) -> None:
    async with Store(db_path) as store:
        # Arrange
        await store.enqueue(incoming())
        head = await store.head()
        assert head is not None

        # Act
        await store.mark_sent(head.row_id)

        # Assert
        counters = await store.counters()
        assert await store.has_pending() is False
        assert counters.sent_today == 1
        assert counters.pending == 0


@pytest.mark.asyncio
async def test_failed_message_leaves_the_queue_and_keeps_the_reason(db_path: Path) -> None:
    async with Store(db_path) as store:
        # Arrange
        await store.enqueue(incoming())
        head = await store.head()
        assert head is not None

        # Act
        await store.mark_failed(head.row_id, "chat not found")

        # Assert
        counters = await store.counters()
        assert await store.has_pending() is False
        assert counters.failed_today == 1


@pytest.mark.asyncio
async def test_recorded_attempt_keeps_the_message_at_the_head(db_path: Path) -> None:
    async with Store(db_path) as store:
        # Arrange
        await store.enqueue(incoming())
        first = await store.head()
        assert first is not None

        # Act
        await store.record_attempt(first.row_id, "network is unreachable")

        # Assert
        again = await store.head()
        assert again is not None
        assert again.row_id == first.row_id
        assert again.attempts == 1


@pytest.mark.asyncio
async def test_queue_keeps_arrival_order(db_path: Path) -> None:
    async with Store(db_path) as store:
        # Arrange
        await store.enqueue(incoming("evt-first"))
        await store.enqueue(incoming("evt-second"))

        # Act
        head = await store.head()
        assert head is not None
        await store.mark_sent(head.row_id)
        following = await store.head()

        # Assert
        assert head.event_id == "evt-first"
        assert following is not None
        assert following.event_id == "evt-second"


@pytest.mark.asyncio
async def test_sent_message_is_removed_immediately_regardless_of_retention(db_path: Path) -> None:
    async with Store(db_path) as store:
        # Arrange: сообщение принято давно — историю отправленных purge не трогает,
        # об этом заботится сама mark_sent.
        long_ago = datetime.now(UTC) - timedelta(days=90)
        await store.enqueue(incoming("evt-old", received_at=long_ago))
        old = await store.head()
        assert old is not None

        # Act
        await store.mark_sent(old.row_id)

        # Assert
        removed = await store.purge(history_days=30)
        assert removed == 0
        assert await store.has_pending() is False


@pytest.mark.asyncio
async def test_purge_removes_old_failures_but_never_the_queue(db_path: Path) -> None:
    async with Store(db_path) as store:
        # Arrange
        long_ago = datetime.now(UTC) - timedelta(days=90)
        await store.enqueue(incoming("evt-old", received_at=long_ago))
        old = await store.head()
        assert old is not None
        await store.mark_failed(old.row_id, "chat not found")
        await store.enqueue(incoming("evt-waiting", received_at=long_ago))

        # Act
        removed = await store.purge(history_days=30)

        # Assert
        assert removed == 1
        assert await store.has_pending() is True


@pytest.mark.asyncio
async def test_purge_is_disabled_by_a_non_positive_retention(db_path: Path) -> None:
    async with Store(db_path) as store:
        # Arrange
        await store.enqueue(incoming("evt-old", received_at=datetime.now(UTC) - timedelta(days=90)))
        head = await store.head()
        assert head is not None
        await store.mark_failed(head.row_id, "chat not found")

        # Act
        removed = await store.purge(history_days=0)

        # Assert
        assert removed == 0


@pytest.mark.asyncio
async def test_queue_survives_reopening_the_database(db_path: Path) -> None:
    # Arrange
    async with Store(db_path) as store:
        await store.enqueue(incoming("evt-durable"))

    # Act
    async with Store(db_path) as reopened:
        head = await reopened.head()

    # Assert
    assert head is not None
    assert head.event_id == "evt-durable"


@pytest.mark.asyncio
async def test_closed_store_refuses_to_work(db_path: Path) -> None:
    store = Store(db_path)

    with pytest.raises(RuntimeError, match="не открыто"):
        await store.head()


@pytest.mark.asyncio
async def test_rendered_post_carries_both_numbers_and_the_text(db_path: Path) -> None:
    async with Store(db_path) as store:
        await store.enqueue(incoming(body="код 1234", media="https://example.com/a.png"))
        head = await store.head()
        assert head is not None

        assert head.render() == "+15551110000 → +15552220000\nкод 1234\nhttps://example.com/a.png"


@pytest.mark.asyncio
async def test_media_only_message_renders_without_an_empty_line(db_path: Path) -> None:
    async with Store(db_path) as store:
        await store.enqueue(incoming(body="", media="https://example.com/a.png"))
        head = await store.head()
        assert head is not None

        assert head.render() == "+15551110000 → +15552220000\nhttps://example.com/a.png"
