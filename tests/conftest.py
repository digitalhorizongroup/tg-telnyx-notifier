import logging
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from tgtn.core.config import SERVICE, Settings

TOKEN = "111:AAAfake-token-for-tests"
CHAT_ID = -1001234567890
SECRET = "webhook-secret-for-tests"
EVENT_ID = "40385f64-5717-4562-b3fc-2c963f66afa6"

type SettingsFactory = Callable[..., Settings]


def webhook_body(**overrides: Any) -> dict[str, Any]:
    """Тело webhook Telnyx о входящем сообщении; поля повторяют документацию.

    Именованный аргумент ``payload`` подменяет поля самого сообщения, остальные —
    поля верхнего уровня.
    """
    payload: dict[str, Any] = {
        "id": EVENT_ID,
        "direction": "inbound",
        "from": {"phone_number": "+15551110000", "carrier": "T-Mobile", "line_type": "long_code"},
        "to": [{"phone_number": "+15552220000", "status": "delivered"}],
        "text": "код 1234",
        "type": "SMS",
        "media": [],
        "received_at": "2026-08-04T10:00:00.000+00:00",
    }
    payload.update(overrides.pop("payload", {}))
    body: dict[str, Any] = {
        "data": {
            "event_type": "message.received",
            "id": "event-uuid",
            "occurred_at": "2026-08-04T10:00:00.000+00:00",
            "payload": payload,
            "record_type": "event",
        },
        "meta": {"attempt": 1, "delivered_to": "https://example.com/notification"},
    }
    body.update(overrides)
    return body


@pytest.fixture
def make_settings() -> SettingsFactory:
    """Собрать настройки с заведомо поддельными секретами.

    Значения передаются явно, а не читаются из `.env`: набор обязан давать один
    и тот же результат на машине с настроенным окружением и без него.
    """

    def factory(**overrides: object) -> Settings:
        base: dict[str, object] = {
            "bot_token": TOKEN,
            "chat_id": CHAT_ID,
            "telegram_webhook_secret": SECRET,
            # Источник `.env` отключён целиком: иначе поля, которые тест не
            # задал, приезжают из файла разработчика, и набор проверяет чужое
            # окружение вместо кода.
            "_env_file": None,
        }
        return Settings.model_validate(base | overrides)

    return factory


@pytest.fixture
def settings(make_settings: SettingsFactory) -> Settings:
    return make_settings()


@pytest.fixture
def restore_logging() -> Iterator[None]:
    """Вернуть дерево логгеров в исходное состояние после теста.

    setup_logging правит глобальный root-логгер, и без отката следующий тест
    получил бы чужие пороги и чужой обработчик.
    """
    root = logging.getLogger()
    handlers, root_level = root.handlers[:], root.level
    service_level = logging.getLogger(SERVICE).level

    yield

    for handler in root.handlers[:]:
        root.removeHandler(handler)
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(root_level)
    logging.getLogger(SERVICE).setLevel(service_level)
