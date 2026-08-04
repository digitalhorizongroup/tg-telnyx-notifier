"""Проверка живости: единственный маршрут, не требующий ни Telnyx, ни Telegram.

Отвечает, пока жив сам процесс. Внешние связи он не проверяет намеренно: по
этому маршруту бьёт ``HEALTHCHECK`` образа, и недоступность Telegram не повод
объявлять контейнер мёртвым и перезапускать его по кругу.
"""

from fastapi import APIRouter

from tgtn import __version__
from tgtn.core.schemas import Health

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> Health:
    """Отдать признак живости и версию отвечающей сборки."""
    return Health(status="ok", version=__version__)


__all__ = ["router"]
