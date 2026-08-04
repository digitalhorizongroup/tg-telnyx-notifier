"""Разбор webhook Telnyx о входящем сообщении.

Описаны только поля, которые сервис читает; всё остальное из тела запроса
отбрасывается (``extra="ignore"``). Так добавление поля на стороне Telnyx не
роняет приём, а нужные поля остаются обязательными и проверяются.

Событие приходит на оба адреса профиля — основной и запасной, — и там же
появляются события об исходящих (``message.sent``, ``message.finalized``).
Отбор по :data:`INBOUND_EVENT` и по ``direction`` делает обработчик.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

INBOUND_EVENT = "message.received"
INBOUND_DIRECTION = "inbound"


class Party(BaseModel):
    """Сторона переписки — номер в формате E.164."""

    model_config = ConfigDict(extra="ignore")

    phone_number: str


class Media(BaseModel):
    """Вложение MMS.

    Attributes:
        url: Ссылка на скачивание с истечением срока; сервис её пересылает, а
            не выкачивает содержимое.
        content_type: MIME-тип вложения.
    """

    model_config = ConfigDict(extra="ignore")

    url: str
    content_type: str | None = None


class InboundMessage(BaseModel):
    """Тело события: одно входящее сообщение.

    Attributes:
        id: Идентификатор сообщения у Telnyx. По нему идёт дедупликация:
            ``meta.attempt`` доходит до 3, то есть одно и то же сообщение
            приезжает повторно, пока приём не ответит успехом.
        direction: У входящего всегда ``inbound``; исходящие события приходят на
            тот же адрес и сюда не относятся.
        sender: Кто прислал. В теле запроса поле называется ``from`` — это
            ключевое слово Python, поэтому имя в модели своё, а связь задана
            алиасом.
        to: Номера профиля, на которые пришло сообщение.
        text: Текст. У MMS без подписи бывает пустым, поэтому не обязателен.
        media: Вложения; у SMS список пуст.
        received_at: Когда Telnyx принял сообщение.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    direction: str
    sender: Party = Field(alias="from")
    to: list[Party] = Field(default_factory=list)
    text: str | None = None
    media: list[Media] = Field(default_factory=list)
    received_at: datetime | None = None


class Event(BaseModel):
    """Конверт события.

    Attributes:
        event_type: Что произошло; входящее сообщение — :data:`INBOUND_EVENT`.
        payload: Само сообщение.
    """

    model_config = ConfigDict(extra="ignore")

    event_type: str
    payload: InboundMessage


class Webhook(BaseModel):
    """Тело POST-запроса от Telnyx целиком."""

    model_config = ConfigDict(extra="ignore")

    data: Event


__all__ = ["INBOUND_DIRECTION", "INBOUND_EVENT", "Event", "InboundMessage", "Media", "Party", "Webhook"]
