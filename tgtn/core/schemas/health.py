"""Схема ответа проверки живости."""

from pydantic import BaseModel


class Health(BaseModel):
    """Ответ ``GET /health``.

    Attributes:
        status: Постоянное ``ok``. Значение несёт не текст, а сам факт ответа:
            процесс поднялся и обслуживает запросы.
        version: Версия дистрибутива — по ней видно, какая сборка отвечает на
            порту.
    """

    status: str
    version: str


__all__ = ["Health"]
