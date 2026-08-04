"""Приём webhook Telnyx о входящем сообщении.

Два адреса, один разбор: ``/notification`` — основной адрес профиля,
``/failure`` — запасной, куда Telnyx повторяет доставку, если основной не
ответил. Событие в них одинаковое, поэтому и обработка одна; различается только
запись в журнале — по ней видно, что основной адрес не отвечал.

Обработчик кладёт сообщение в очередь и сразу отвечает. Отправка идёт фоновым
воркером: Telnyx ждёт ответа считаные секунды, а пауза между постами доходит до
тридцати.
"""

import logging

from fastapi import APIRouter, status

from tgtn.core.schemas import INBOUND_DIRECTION, INBOUND_EVENT, Webhook
from tgtn.core.store import Incoming
from tgtn.handlers.deps import OutboxDep, StoreDep

LOG = logging.getLogger(__name__)

router = APIRouter(tags=["telnyx"])


@router.post("/notification", status_code=status.HTTP_202_ACCEPTED)
async def notification(event: Webhook, store: StoreDep, outbox: OutboxDep) -> dict[str, str]:
    """Принять событие с основного адреса профиля."""
    return await _accept(event, store, outbox, source="notification")


@router.post("/failure", status_code=status.HTTP_202_ACCEPTED)
async def failure(event: Webhook, store: StoreDep, outbox: OutboxDep) -> dict[str, str]:
    """Принять событие с запасного адреса профиля."""
    return await _accept(event, store, outbox, source="failure")


async def _accept(event: Webhook, store: StoreDep, outbox: OutboxDep, source: str) -> dict[str, str]:
    """Поставить входящее сообщение в очередь.

    Ответ всегда успешный, даже когда событие не про входящее сообщение или
    приезжает повторно: код ошибки заставил бы Telnyx повторять доставку того,
    что сервис намеренно пропустил, — до трёх раз и с тем же исходом.

    Args:
        event: Разобранное тело запроса.
        store: Хранилище очереди.
        outbox: Воркер, которого будят после успешной записи.
        source: Адрес, на который пришло событие, — для журнала.

    Returns:
        Что сделано с событием: ``queued``, ``duplicate`` или ``ignored``.
    """
    message = event.data.payload
    if event.data.event_type != INBOUND_EVENT or message.direction != INBOUND_DIRECTION:
        LOG.debug("событие %s (%s) пропущено: не входящее сообщение", event.data.event_type, source)
        return {"status": "ignored"}

    recipient = message.to[0].phone_number if message.to else "—"
    queued = await store.enqueue(
        Incoming(
            event_id=message.id,
            sender=message.sender.phone_number,
            recipient=recipient,
            body=message.text or "",
            media="\n".join(item.url for item in message.media),
            received_at=message.received_at,
        )
    )
    if not queued:
        LOG.info("сообщение %s уже принято (%s); повтор доставки", message.id, source)
        return {"status": "duplicate"}

    outbox.notify()
    LOG.info("сообщение %s принято с %s → %s (%s)", message.id, message.sender.phone_number, recipient, source)
    return {"status": "queued"}


__all__ = ["router"]
