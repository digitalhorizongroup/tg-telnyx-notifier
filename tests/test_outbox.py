import asyncio
from datetime import UTC, datetime
from typing import cast

import pytest

from tgtn.core.outbox import Outbox
from tgtn.core.store import Pending, Store
from tgtn.core.telegram import RejectedError, Telegram, UnavailableError

# Реальные паузы, только мелкие: шкала проверяется на тех же вычислениях, что и
# в рантайме, а прогон остаётся быстрым. Подмена asyncio.sleep проверяла бы
# арифметику вокруг несуществующего ожидания.
BASE = 0.01
MAX = 0.06


def pending(row_id: int = 1, event_id: str = "evt-1") -> Pending:
    return Pending(
        row_id=row_id,
        event_id=event_id,
        sender="+15551110000",
        recipient="+15552220000",
        body="привет",
        media="",
        received_at=datetime.now(UTC),
        attempts=0,
    )


class FakeStore:
    """Очередь в памяти с теми же методами, что читает воркер."""

    def __init__(self, queue: list[Pending] | None = None) -> None:
        self.queue = queue if queue is not None else []
        self.sent: list[int] = []
        self.failed: list[tuple[int, str]] = []
        self.attempts: list[tuple[int, str]] = []

    async def has_pending(self) -> bool:
        return bool(self.queue)

    async def head(self) -> Pending | None:
        return self.queue[0] if self.queue else None

    async def mark_sent(self, row_id: int) -> None:
        self.sent.append(row_id)
        self.queue.pop(0)

    async def mark_failed(self, row_id: int, error: str) -> None:
        self.failed.append((row_id, error))
        self.queue.pop(0)

    async def record_attempt(self, row_id: int, error: str) -> None:
        self.attempts.append((row_id, error))


class FakeTelegram:
    """Канал доставки, который отдаёт заранее назначенный исход."""

    def __init__(self, outcome: Exception | None = None) -> None:
        self.outcome = outcome
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)
        if self.outcome is not None:
            raise self.outcome


def build(store: FakeStore, telegram: FakeTelegram) -> Outbox:
    return Outbox(cast(Store, store), cast(Telegram, telegram), base_delay=BASE, max_delay=MAX)


def test_production_schedule_runs_5_10_20_30_and_stops_there() -> None:
    # Arrange: настройки по умолчанию, без ожидания — проверяется сама шкала.
    outbox = Outbox(cast(Store, FakeStore()), cast(Telegram, FakeTelegram()), base_delay=5.0, max_delay=30.0)

    # Act
    schedule = []
    for _ in range(5):
        outbox._delay = outbox._next_delay(has_pending=True)
        schedule.append(outbox._delay)

    # Assert
    assert schedule == [10.0, 20.0, 30.0, 30.0, 30.0]


def test_empty_queue_returns_the_delay_to_the_base_value() -> None:
    # Arrange
    outbox = Outbox(cast(Store, FakeStore()), cast(Telegram, FakeTelegram()), base_delay=5.0, max_delay=30.0)
    outbox._delay = 30.0

    # Act / Assert
    assert outbox._next_delay(has_pending=False) == 5.0


@pytest.mark.asyncio
async def test_delay_doubles_while_the_queue_keeps_filling() -> None:
    # Arrange: очередь не пустеет — воркер видит её непрерывным наплывом.
    store = FakeStore([pending(row_id=index) for index in range(1, 8)])
    outbox = build(store, FakeTelegram())

    # Act
    schedule = []
    for _ in range(5):
        await outbox._step()
        schedule.append(round(outbox.delay, 4))

    # Assert: 5 → 10 → 20 → 30 → 30 в масштабе теста.
    assert schedule == [BASE * 2, BASE * 4, MAX, MAX, MAX]


@pytest.mark.asyncio
async def test_delay_resets_when_the_timer_expires_on_an_empty_queue() -> None:
    # Arrange: одно сообщение, после него очередь пуста.
    store = FakeStore([pending()])
    outbox = build(store, FakeTelegram())

    # Act
    await outbox._step()

    # Assert
    assert store.sent == [1]
    assert outbox.delay == BASE


@pytest.mark.asyncio
async def test_first_message_of_a_calm_queue_goes_out_before_any_wait() -> None:
    # Arrange
    store = FakeStore([pending()])
    telegram = FakeTelegram()
    outbox = build(store, telegram)

    # Act: пауза стоит после отправки, поэтому шаг успевает отправить.
    await asyncio.wait_for(outbox._step(), timeout=1)

    # Assert
    assert telegram.sent == ["+15551110000 → +15552220000\nпривет"]


@pytest.mark.asyncio
async def test_unavailable_telegram_keeps_the_message_at_the_head() -> None:
    # Arrange
    store = FakeStore([pending()])
    outbox = build(store, FakeTelegram(UnavailableError("network is unreachable")))

    # Act
    await outbox._step()

    # Assert
    assert store.sent == []
    assert store.failed == []
    assert store.attempts == [(1, "network is unreachable")]
    assert store.queue


@pytest.mark.asyncio
async def test_rejected_message_is_dropped_so_it_stops_blocking_the_queue() -> None:
    # Arrange
    store = FakeStore([pending(), pending(row_id=2, event_id="evt-2")])
    outbox = build(store, FakeTelegram(RejectedError("chat not found")))

    # Act
    await outbox._step()

    # Assert
    assert store.failed == [(1, "chat not found")]
    head = await store.head()
    assert head is not None
    assert head.row_id == 2


@pytest.mark.asyncio
async def test_retry_after_is_honoured_before_the_next_pass() -> None:
    # Arrange
    store = FakeStore([pending()])
    outbox = build(store, FakeTelegram(UnavailableError("flood", retry_after=BASE)))

    # Act
    started = asyncio.get_running_loop().time()
    await outbox._step()
    elapsed = asyncio.get_running_loop().time() - started

    # Assert: пауза Telegram выдержана поверх собственной паузы воркера.
    assert elapsed >= BASE * 2


@pytest.mark.asyncio
async def test_worker_sleeps_on_an_empty_queue_until_a_message_arrives() -> None:
    # Arrange
    store = FakeStore()
    outbox = build(store, FakeTelegram())
    step = asyncio.create_task(outbox._step())
    await asyncio.sleep(0)

    # Assert: без сообщений шаг не завершается.
    assert not step.done()

    # Act
    store.queue.append(pending())
    outbox.notify()
    await asyncio.wait_for(step, timeout=1)

    # Assert
    assert step.done()


@pytest.mark.asyncio
async def test_started_worker_drains_the_queue_and_stops_cleanly() -> None:
    # Arrange
    store = FakeStore([pending()])
    telegram = FakeTelegram()
    outbox = build(store, telegram)

    # Act
    await outbox.start()
    for _ in range(100):
        await asyncio.sleep(BASE)
        if store.sent:
            break
    await outbox.stop()

    # Assert
    assert store.sent == [1]
    assert telegram.sent


@pytest.mark.asyncio
async def test_broken_pass_does_not_kill_the_worker() -> None:
    # Arrange: хранилище срывается на первом обращении и чинится после него.
    class BrokenOnce(FakeStore):
        def __init__(self) -> None:
            super().__init__([pending()])
            self.calls = 0

        async def has_pending(self) -> bool:
            self.calls += 1
            if self.calls == 1:
                message = "база недоступна"
                raise OSError(message)
            return bool(self.queue)

    store = BrokenOnce()
    outbox = build(store, FakeTelegram())

    # Act
    await outbox.start()
    for _ in range(100):
        await asyncio.sleep(BASE)
        if store.sent:
            break
    await outbox.stop()

    # Assert
    assert store.sent == [1]
