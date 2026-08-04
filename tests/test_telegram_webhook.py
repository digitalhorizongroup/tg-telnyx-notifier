from typing import Any, cast

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi.testclient import TestClient

from tests.conftest import SECRET, TOKEN
from tgtn.__main__ import create_app
from tgtn.core.config import TELEGRAM_WEBHOOK_PATH, Settings
from tgtn.handlers.telegram import router as telegram_router

UPDATE: dict[str, Any] = {"update_id": 1}


class FakeDispatcher:
    def __init__(self) -> None:
        self.fed: list[Update] = []

    async def feed_update(self, bot: Bot, update: Update, **kwargs: Any) -> None:
        self.fed.append(update)


@pytest.fixture
def dispatcher() -> FakeDispatcher:
    return FakeDispatcher()


@pytest.fixture
def client(settings: Settings, dispatcher: FakeDispatcher) -> TestClient:
    app = create_app(settings, routers=(telegram_router,))
    app.state.bot = Bot(token=TOKEN)
    app.state.dispatcher = cast(Dispatcher, dispatcher)
    return TestClient(app)


def test_update_with_the_right_secret_reaches_the_dispatcher(client: TestClient, dispatcher: FakeDispatcher) -> None:
    # Act
    response = client.post(
        TELEGRAM_WEBHOOK_PATH,
        json=UPDATE,
        headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
    )

    # Assert
    assert response.status_code == 200
    assert [update.update_id for update in dispatcher.fed] == [1]


def test_update_without_the_header_is_refused(client: TestClient, dispatcher: FakeDispatcher) -> None:
    # Act
    response = client.post(TELEGRAM_WEBHOOK_PATH, json=UPDATE)

    # Assert
    assert response.status_code == 403
    assert dispatcher.fed == []


def test_update_with_a_wrong_secret_is_refused(client: TestClient, dispatcher: FakeDispatcher) -> None:
    # Act
    response = client.post(
        TELEGRAM_WEBHOOK_PATH,
        json=UPDATE,
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
    )

    # Assert
    assert response.status_code == 403
    assert dispatcher.fed == []
