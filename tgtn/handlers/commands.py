"""Команды бота: сводка активности.

Зависимости приезжают именованными аргументами — их кладёт диспетчер, которому
их передали при сборке (:func:`tgtn.__main__.create_app`). Обработчик ничего не
создаёт сам и потому проверяется без сети: в тесте те же аргументы передаются
напрямую.
"""

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from tgtn.core.config import Settings
from tgtn.core.outbox import Outbox
from tgtn.core.schemas import Activity
from tgtn.core.store import Store
from tgtn.core.telegram import Telegram

LOG = logging.getLogger(__name__)

COMMAND = "activity"


def allowed(message: Message, settings: Settings) -> bool:
    """Можно ли отвечать на это сообщение.

    Отвечаем в самом канале и тем, кто перечислен в ``admin_ids``. Бот открыт
    всему миру — любой, кто знает его имя, напишет ему в личку, — и без этой
    проверки сводка по чужому трафику уходила бы постороннему.
    """
    if message.chat.id == settings.chat_id:
        return True
    return message.from_user is not None and message.from_user.id in settings.admin_ids


def render(activity: Activity) -> str:
    """Разложить сводку в текст поста."""
    telegram_line = "доступен" if activity.telegram_available else f"недоступен ({activity.telegram_error})"
    lines = [
        "Активность за сегодня (UTC)",
        f"принято: {activity.received_today}",
        f"отправлено: {activity.sent_today}",
        f"отброшено: {activity.failed_today}",
        f"в очереди: {activity.pending}",
        f"пауза между отправками: {activity.delay_seconds:.0f} с",
        f"telegram: {telegram_line}",
    ]
    return "\n".join(lines)


async def collect(store: Store, outbox: Outbox, telegram: Telegram) -> Activity:
    """Собрать сводку: счётчики из базы и живая проверка Telegram."""
    counters = await store.counters()
    available, error = await telegram.probe()
    return Activity(
        received_today=counters.received_today,
        sent_today=counters.sent_today,
        failed_today=counters.failed_today,
        pending=counters.pending,
        delay_seconds=outbox.delay,
        telegram_available=available,
        telegram_error=error,
    )


async def activity(
    message: Message,
    settings: Settings,
    store: Store,
    outbox: Outbox,
    telegram: Telegram,
) -> None:
    """Ответить сводкой активности на ``/activity``.

    Постороннему не отвечаем вовсе, а не отказом: молчание не подтверждает, что
    за этим именем стоит живой сервис.
    """
    if not allowed(message, settings):
        LOG.info("команда активности от постороннего: чат %s", message.chat.id)
        return
    report = await collect(store, outbox, telegram)
    await message.answer(render(report), parse_mode=None)


def build_router() -> Router:
    """Собрать маршрутизатор команд заново.

    Новый экземпляр на каждый вызов, а не модульный синглтон: aiogram запрещает
    подключать один и тот же ``Router`` к двум ``Dispatcher`` подряд, а второй
    подъём приложения в том же процессе — обычный случай в тестах.
    """
    router = Router(name="commands")
    router.message(Command(COMMAND))(activity)
    router.channel_post(Command(COMMAND))(activity)
    return router


__all__ = ["COMMAND", "activity", "allowed", "build_router", "collect", "render"]
