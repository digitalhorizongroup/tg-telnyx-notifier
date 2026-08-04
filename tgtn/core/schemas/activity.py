"""Сводка активности: что сервис сделал за сутки и жив ли Telegram."""

from pydantic import BaseModel


class Activity(BaseModel):
    """Ответ команды активности.

    Сутки считаются по UTC — той же зоне, в которой пишется журнал; иначе
    «сегодня» в сводке и «сегодня» в логах расходятся на несколько часов.

    Attributes:
        received_today: Сколько сообщений принято от Telnyx за сутки.
        sent_today: Сколько из них ушло в канал. Меньше принятых — значит часть
            ещё ждёт очереди либо не доставлена.
        failed_today: Сколько отброшено по неустранимой причине: бота выгнали из
            канала, канал удалён, тело не принято Telegram.
        pending: Сколько сообщений сейчас в очереди, включая принятые вчера.
        delay_seconds: Текущая пауза между отправками. Больше базовой — очередь
            под наплывом.
        telegram_available: Отвечает ли Telegram прямо сейчас; проверяется живым
            запросом в момент команды, а не берётся из прошлой отправки.
        telegram_error: Чем ответил Telegram, когда недоступен.
    """

    received_today: int
    sent_today: int
    failed_today: int
    pending: int
    delay_seconds: float
    telegram_available: bool
    telegram_error: str | None = None


__all__ = ["Activity"]
