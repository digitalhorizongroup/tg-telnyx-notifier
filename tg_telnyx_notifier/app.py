"""ASGI-приложение: HTTP-вход, куда Telnyx шлёт webhook о входящем сообщении.

Объект :data:`app` — точка входа для ASGI-сервера. Образ запускает его строкой
``uvicorn tg_telnyx_notifier.app:app``, поэтому имя модуля и имя переменной
входят в контракт с Dockerfile.
"""

from fastapi import FastAPI
from pydantic import BaseModel

from tg_telnyx_notifier import __version__

app = FastAPI(title="tg-telnyx-notifier", version=__version__)


class Health(BaseModel):
    """Ответ проверки живости."""

    status: str
    version: str


@app.get("/health")
async def health() -> Health:
    """Проверка живости для HEALTHCHECK образа и балансировщика.

    Версия в ответе — та же, что в метаданных дистрибутива: по ней видно, какая
    сборка отвечает на порту.
    """
    return Health(status="ok", version=__version__)
