"""Отправка в канал и проверка доступности Telegram.

Здесь же проходит единственная в сервисе классификация отказов: устранимые
(:class:`UnavailableError`) означают «повторить позже и не трогать очередь»,
неустранимые (:class:`RejectedError`) — «повтор ничего не изменит, сообщение
отбросить». Без этого деления либо одно битое сообщение навсегда встаёт головой
очереди, либо недоступность Telegram выглядит как отказ и теряет всё подряд.
"""

import logging

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)

LOG = logging.getLogger(__name__)


class DeliveryError(Exception):
    """Отправка не удалась."""


class UnavailableError(DeliveryError):
    """Отказ устранимый: Telegram недоступен либо просит подождать.

    Attributes:
        retry_after: Сколько секунд ждать по требованию Telegram; ``None``,
            когда срок не назван и его выбирает вызывающий.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class RejectedError(DeliveryError):
    """Отказ неустранимый: бот выгнан из канала, канал удалён, тело не принято."""


class Telegram:
    """Канал доставки: один бот, один адресат."""

    def __init__(self, bot: Bot, chat_id: int) -> None:
        self._bot = bot
        self._chat_id = chat_id

    async def send(self, text: str) -> None:
        """Отправить текст в канал.

        Разметка выключена явно (``parse_mode=None``): текст пришёл из SMS, и
        любой символ вроде ``<`` или ``_`` Telegram иначе разбирал бы как тег —
        сообщение либо исказится, либо будет отвергнуто целиком.

        Raises:
            UnavailableError: Telegram недоступен или требует паузы.
            RejectedError: Telegram отверг сообщение, и повтор ничего не изменит.
        """
        try:
            await self._bot.send_message(chat_id=self._chat_id, text=text, parse_mode=None)
        except TelegramRetryAfter as exc:
            raise UnavailableError(str(exc), retry_after=float(exc.retry_after)) from exc
        except (TelegramNetworkError, TelegramServerError) as exc:
            raise UnavailableError(str(exc)) from exc
        except TelegramAPIError as exc:
            # Остаток семейства — 4xx: неверный адресат, отозванный токен,
            # слишком большое тело. Все они повторяются с тем же исходом.
            raise RejectedError(str(exc)) from exc

    async def probe(self) -> tuple[bool, str | None]:
        """Проверить доступность живым запросом.

        Returns:
            Пара «доступен, причина отказа». Причина — ``None``, когда Telegram
            ответил.
        """
        try:
            await self._bot.get_me()
        except TelegramAPIError as exc:
            return False, str(exc)
        return True, None

    async def register_webhook(self, url: str, secret: str) -> None:
        """Указать Telegram, куда слать апдейты.

        Вызов идемпотентен: повторная регистрация того же адреса ничего не
        меняет, поэтому делается на каждом старте, а не однократно руками.
        Ошибка не роняет сервис — пересылка сообщений от неё не зависит.
        """
        try:
            await self._bot.set_webhook(url=url, secret_token=secret, drop_pending_updates=False)
        except TelegramAPIError:
            LOG.warning("webhook не зарегистрирован (%s); команда активности недоступна", url, exc_info=True)
        else:
            LOG.info("webhook зарегистрирован: %s", url)

    async def close(self) -> None:
        """Закрыть HTTP-сессию бота."""
        await self._bot.session.close()


__all__ = ["DeliveryError", "RejectedError", "Telegram", "UnavailableError"]
