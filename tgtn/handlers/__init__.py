"""Обработчики входящих событий — по модулю на источник события.

Граница пакета: модуль отсюда разбирает и валидирует то, что пришло снаружи, и
зовёт отправку. Разговором с Telegram и с Telnyx занимается не он — обработчик
остаётся проверяемым без сети.

``ROUTERS`` — вся HTTP-поверхность сервиса. Приложение набирается из этого
перечня (:func:`tgtn.__main__.create_app`), поэтому новый маршрут появляется
снаружи ровно тогда, когда его маршрутизатор дописан сюда.

Команды бота (:mod:`tgtn.handlers.commands`) сюда не входят: их разбирает не
FastAPI, а диспетчер aiogram, которому апдейт передаёт
:mod:`tgtn.handlers.telegram`.
"""

from fastapi import APIRouter

from tgtn.handlers.health import router as health_router
from tgtn.handlers.notification import router as notification_router
from tgtn.handlers.telegram import router as telegram_router

ROUTERS: tuple[APIRouter, ...] = (health_router, notification_router, telegram_router)

__all__ = ["ROUTERS"]
