"""Команды бота: сводка активности.

Зависимости приезжают именованными аргументами — их кладёт диспетчер из
``DISPATCHER.workflow_data`` (:func:`tgtn.__main__.lifespan`). Обработчик
ничего не создаёт сам и потому проверяется без сети: в тесте те же аргументы
передаются напрямую.
"""

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from tgtn.core.config import Settings
from tgtn.core.schemas import Activity
from tgtn.modules.outbox import Outbox
from tgtn.modules.store import Store
from tgtn.modules.telegram import Telegram

LOG = logging.getLogger(__name__)

COMMAND = "activity"

router = Router(name="commands")


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


@router.message(Command(COMMAND))
@router.channel_post(Command(COMMAND))
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


__all__ = ["COMMAND", "activity", "allowed", "collect", "render", "router"]
