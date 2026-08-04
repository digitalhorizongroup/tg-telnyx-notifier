"""Схемы pydantic: форма данных на границах сервиса.

Здесь описано то, что пересекает границу процесса, — тело запроса, тело ответа,
разобранное событие. Настройки сюда не входят: они тоже модель pydantic, но
приходят из окружения, а не из запроса, и живут в :mod:`tgtn.core.config`.
"""

from tgtn.core.schemas.activity import Activity
from tgtn.core.schemas.health import Health
from tgtn.core.schemas.telnyx import INBOUND_DIRECTION, INBOUND_EVENT, InboundMessage, Webhook

__all__ = ["INBOUND_DIRECTION", "INBOUND_EVENT", "Activity", "Health", "InboundMessage", "Webhook"]
