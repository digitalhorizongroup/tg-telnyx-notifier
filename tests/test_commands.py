from datetime import UTC, datetime
from typing import cast

import pytest
from aiogram.types import Chat, Message, User

from tests.conftest import CHAT_ID, SettingsFactory
from tgtn.core.schemas import Activity
from tgtn.handlers.commands import allowed, collect, render
from tgtn.modules.outbox import Outbox
from tgtn.modules.store import Counters, Store
from tgtn.modules.telegram import Telegram


def message_from(chat_id: int, user_id: int | None = None) -> Message:
    user = User(id=user_id, is_bot=False, first_name="кто-то") if user_id is not None else None
    return Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=chat_id, type="private"),
        from_user=user,
    )


class FakeStore:
    def __init__(self, counters: Counters) -> None:
        self._counters = counters

    async def counters(self) -> Counters:
        return self._counters


class FakeOutbox:
    def __init__(self, delay: float) -> None:
        self.delay = delay


class FakeTelegram:
    def __init__(self, outcome: tuple[bool, str | None]) -> None:
        self._outcome = outcome

    async def probe(self) -> tuple[bool, str | None]:
        return self._outcome


def test_channel_itself_is_always_allowed(make_settings: SettingsFactory) -> None:
    settings = make_settings()

    assert allowed(message_from(CHAT_ID), settings) is True


def test_listed_admin_is_allowed_from_a_private_chat(make_settings: SettingsFactory) -> None:
    settings = make_settings(admin_ids="777")

    assert allowed(message_from(chat_id=999, user_id=777), settings) is True


def test_stranger_is_not_allowed(make_settings: SettingsFactory) -> None:
    settings = make_settings()

    assert allowed(message_from(chat_id=999, user_id=777), settings) is False


def test_admin_ids_are_read_from_a_comma_separated_string(make_settings: SettingsFactory) -> None:
    settings = make_settings(admin_ids="1, 2 ,3")

    assert settings.admin_ids == frozenset({1, 2, 3})


@pytest.mark.asyncio
async def test_summary_joins_counters_with_a_live_telegram_probe() -> None:
    # Arrange
    store = FakeStore(Counters(received_today=7, sent_today=5, failed_today=1, pending=2))
    outbox = FakeOutbox(delay=20.0)
    telegram = FakeTelegram((True, None))

    # Act
    activity = await collect(cast(Store, store), cast(Outbox, outbox), cast(Telegram, telegram))

    # Assert
    assert activity.received_today == 7
    assert activity.sent_today == 5
    assert activity.failed_today == 1
    assert activity.pending == 2
    assert activity.delay_seconds == 20.0
    assert activity.telegram_available is True


@pytest.mark.asyncio
async def test_unavailable_telegram_carries_its_reason_into_the_summary() -> None:
    # Arrange
    store = FakeStore(Counters(received_today=0, sent_today=0, failed_today=0, pending=3))
    telegram = FakeTelegram((False, "Bad Gateway"))

    # Act
    activity = await collect(cast(Store, store), cast(Outbox, FakeOutbox(5.0)), cast(Telegram, telegram))

    # Assert
    assert activity.telegram_available is False
    assert activity.telegram_error == "Bad Gateway"


def test_report_names_every_counter() -> None:
    # Arrange
    activity = Activity(
        received_today=7,
        sent_today=5,
        failed_today=1,
        pending=2,
        delay_seconds=20.0,
        telegram_available=True,
    )

    # Act
    text = render(activity)

    # Assert
    assert "принято: 7" in text
    assert "отправлено: 5" in text
    assert "отброшено: 1" in text
    assert "в очереди: 2" in text
    assert "пауза между отправками: 20 с" in text
    assert "telegram: доступен" in text


def test_report_shows_why_telegram_is_unavailable() -> None:
    # Arrange
    activity = Activity(
        received_today=0,
        sent_today=0,
        failed_today=0,
        pending=3,
        delay_seconds=5.0,
        telegram_available=False,
        telegram_error="Bad Gateway",
    )

    # Act
    text = render(activity)

    # Assert
    assert "telegram: недоступен (Bad Gateway)" in text
