import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import SettingsFactory, webhook_body
from tgtn.__main__ import STARTUP_MESSAGE, create_app
from tgtn.modules.outbox import Outbox
from tgtn.modules.store import Store
from tgtn.modules.telegram import Telegram, UnavailableError

# Сквозные проверки гоняют настоящую очередь на настоящем SQLite; ожидание
# сокращено до миллисекунд, чтобы прогон не упирался в паузу воркера.
FAST = {"send_base_delay": 0.01, "send_max_delay": 0.02}


def wait_for(condition: object, timeout: float = 5.0) -> bool:
    """Дождаться, пока фоновый воркер отработает в своём потоке."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if callable(condition) and condition():
            return True
        time.sleep(0.01)
    return False


def test_lifespan_raises_the_whole_pipeline(make_settings: SettingsFactory, tmp_path: Path) -> None:
    # Arrange
    settings = make_settings(data_dir=tmp_path, **FAST)
    app = create_app(settings)

    # Act
    with TestClient(app) as client:
        health = client.get("/health")

        # Assert
        assert health.status_code == 200
        assert isinstance(app.state.store, Store)
        assert isinstance(app.state.outbox, Outbox)
        assert isinstance(app.state.telegram, Telegram)
        assert app.state.dispatcher is not None

    assert settings.database_path.exists()


def test_message_travels_from_webhook_to_telegram(
    make_settings: SettingsFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange: подменён только разговор с сетью, весь остальной путь настоящий.
    posted: list[str] = []

    async def capture(self: Telegram, text: str) -> None:
        posted.append(text)

    monkeypatch.setattr(Telegram, "send", capture)
    settings = make_settings(data_dir=tmp_path, **FAST)
    app = create_app(settings)

    # Act: старт уже шлёт в канал приветствие, реальное сообщение приходит вторым.
    with TestClient(app) as client:
        accepted = client.post("/notification", json=webhook_body())
        delivered = wait_for(lambda: len(posted) >= 2)

    # Assert
    assert accepted.status_code == 202
    assert delivered is True
    assert posted == [STARTUP_MESSAGE, "+15551110000 → +15552220000\nкод 1234"]


def test_undelivered_message_stays_in_the_queue_after_a_restart(
    make_settings: SettingsFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange: Telegram недоступен всё время работы процесса.
    attempts: list[str] = []

    async def refuse(self: Telegram, text: str) -> None:
        attempts.append(text)
        message = "connection reset"
        raise UnavailableError(message)

    monkeypatch.setattr(Telegram, "send", refuse)
    settings = make_settings(data_dir=tmp_path, **FAST)

    # Act: приветствие при старте уже провалилось, дожидаемся попытки и с реальным
    # сообщением — процесс останавливается прежде, чем оно доставлено.
    with TestClient(create_app(settings)) as client:
        client.post("/notification", json=webhook_body())
        wait_for(lambda: len(attempts) >= 2)

    # Assert: очередь пережила остановку и ждёт в базе.
    posted: list[str] = []

    async def accept(self: Telegram, text: str) -> None:
        posted.append(text)

    monkeypatch.setattr(Telegram, "send", accept)
    with TestClient(create_app(settings)):
        delivered = wait_for(lambda: len(posted) >= 2)

    assert delivered is True
    assert posted == [STARTUP_MESSAGE, "+15551110000 → +15552220000\nкод 1234"]


def test_repeated_webhook_delivers_the_message_once(
    make_settings: SettingsFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    posted: list[str] = []

    async def capture(self: Telegram, text: str) -> None:
        posted.append(text)

    monkeypatch.setattr(Telegram, "send", capture)
    settings = make_settings(data_dir=tmp_path, **FAST)

    # Act: Telnyx повторяет доставку одного и того же события.
    with TestClient(create_app(settings)) as client:
        first = client.post("/notification", json=webhook_body())
        second = client.post("/failure", json=webhook_body())
        wait_for(lambda: len(posted) >= 2)
        time.sleep(0.1)

    # Assert: приветствие при старте плюс ровно одна доставка события, без дубля.
    assert first.json() == {"status": "queued"}
    assert second.json() == {"status": "duplicate"}
    assert len(posted) == 2
