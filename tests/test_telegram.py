from typing import Any, cast

import pytest
from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.methods import SendMessage

from tests.conftest import CHAT_ID
from tgtn.modules.telegram import RejectedError, Telegram, UnavailableError

METHOD = SendMessage(chat_id=CHAT_ID, text="проверка")


class FakeBot:
    """Клиент Telegram, отвечающий заранее назначенным исходом."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.sent: list[dict[str, Any]] = []
        self.webhooks: list[dict[str, Any]] = []
        self.closed = False

    async def send_message(self, **kwargs: Any) -> None:
        self.sent.append(kwargs)
        if self.error is not None:
            raise self.error

    async def get_me(self) -> None:
        if self.error is not None:
            raise self.error

    async def set_webhook(self, **kwargs: Any) -> None:
        self.webhooks.append(kwargs)
        if self.error is not None:
            raise self.error


def build(error: Exception | None = None) -> tuple[Telegram, FakeBot]:
    bot = FakeBot(error)
    return Telegram(cast(Bot, bot), CHAT_ID), bot


@pytest.mark.asyncio
async def test_post_goes_to_the_configured_chat_without_markup() -> None:
    # Arrange
    telegram, bot = build()

    # Act
    await telegram.send("код 1234")

    # Assert: разметка выключена — текст из SMS не разбирается как теги.
    assert bot.sent == [{"chat_id": CHAT_ID, "text": "код 1234", "parse_mode": None}]


@pytest.mark.asyncio
async def test_flood_limit_is_transient_and_carries_the_requested_pause() -> None:
    # Arrange
    telegram, _ = build(TelegramRetryAfter(method=METHOD, message="Flood control exceeded", retry_after=17))

    # Act / Assert
    with pytest.raises(UnavailableError) as raised:
        await telegram.send("привет")
    assert raised.value.retry_after == 17.0


@pytest.mark.asyncio
async def test_network_failure_is_transient_without_a_named_pause() -> None:
    # Arrange
    telegram, _ = build(TelegramNetworkError(method=METHOD, message="connection reset"))

    # Act / Assert
    with pytest.raises(UnavailableError) as raised:
        await telegram.send("привет")
    assert raised.value.retry_after is None


@pytest.mark.asyncio
async def test_server_failure_is_transient() -> None:
    telegram, _ = build(TelegramServerError(method=METHOD, message="Bad Gateway"))

    with pytest.raises(UnavailableError):
        await telegram.send("привет")


@pytest.mark.asyncio
async def test_bot_removed_from_the_channel_is_permanent() -> None:
    telegram, _ = build(TelegramForbiddenError(method=METHOD, message="bot was kicked"))

    with pytest.raises(RejectedError):
        await telegram.send("привет")


@pytest.mark.asyncio
async def test_body_refused_by_telegram_is_permanent() -> None:
    telegram, _ = build(TelegramBadRequest(method=METHOD, message="message is too long"))

    with pytest.raises(RejectedError):
        await telegram.send("привет")


@pytest.mark.asyncio
async def test_probe_reports_a_live_telegram() -> None:
    telegram, _ = build()

    assert await telegram.probe() == (True, None)


@pytest.mark.asyncio
async def test_probe_reports_the_reason_when_telegram_is_down() -> None:
    # Arrange
    telegram, _ = build(TelegramServerError(method=METHOD, message="Bad Gateway"))

    # Act
    available, reason = await telegram.probe()

    # Assert
    assert available is False
    assert reason is not None
    assert "Bad Gateway" in reason


@pytest.mark.asyncio
async def test_webhook_registration_passes_the_shared_secret() -> None:
    # Arrange
    telegram, bot = build()

    # Act
    await telegram.register_webhook("https://example.com/telegram/updates", "s3cret")

    # Assert
    assert bot.webhooks == [
        {
            "url": "https://example.com/telegram/updates",
            "secret_token": "s3cret",
            "drop_pending_updates": False,
        }
    ]


@pytest.mark.asyncio
async def test_failed_registration_does_not_bring_the_service_down() -> None:
    # Arrange: пересылка сообщений от регистрации webhook не зависит.
    telegram, _ = build(TelegramBadRequest(method=METHOD, message="bad webhook url"))

    # Act / Assert
    await telegram.register_webhook("https://example.com/telegram/updates", "s3cret")
