"""Маршрут апдейтов Telegram.

Адрес открыт наружу, и отличить Telegram от постороннего можно только общим
секретом: он уходит в ``setWebhook`` и возвращается заголовком
``X-Telegram-Bot-Api-Secret-Token`` на каждом апдейте.
"""

import logging
from hmac import compare_digest
from typing import Annotated

from aiogram.types import Update
from fastapi import APIRouter, Header, HTTPException, Request, Response, status

from tgtn.core.config import TELEGRAM_WEBHOOK_PATH
from tgtn.handlers.deps import BotDep, DispatcherDep, SettingsDep

LOG = logging.getLogger(__name__)

router = APIRouter(tags=["telegram"])


@router.post(TELEGRAM_WEBHOOK_PATH)
async def updates(
    request: Request,
    settings: SettingsDep,
    bot: BotDep,
    dispatcher: DispatcherDep,
    secret: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
) -> Response:
    """Передать апдейт диспетчеру aiogram.

    Сравнение секрета — ``compare_digest``: обычное ``==`` выходит из сравнения
    на первом несовпавшем байте, и по времени ответа секрет подбирается посимвольно.

    Raises:
        HTTPException: 403, если секрет не совпал или заголовка нет вовсе.
    """
    expected = settings.telegram_webhook_secret.get_secret_value()
    if secret is None or not compare_digest(secret, expected):
        LOG.warning("апдейт с неверным секретом отклонён")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="неверный секрет вебхука")

    update = Update.model_validate(await request.json(), context={"bot": bot})
    await dispatcher.feed_update(bot, update)
    return Response(status_code=status.HTTP_200_OK)


__all__ = ["router"]
