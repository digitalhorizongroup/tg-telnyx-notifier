"""Доступ обработчиков к состоянию приложения.

Хранилище, канал доставки и воркер создаются в lifespan и живут в
``app.state``: обработчику виден только запрос, и это единственный путь от него
к тому, что подняли на старте.
"""

from typing import Annotated

from aiogram import Bot, Dispatcher
from fastapi import Depends, Request

from tgtn.core.config import Settings
from tgtn.core.outbox import Outbox
from tgtn.core.store import Store
from tgtn.core.telegram import Telegram


def get_settings(request: Request) -> Settings:
    """Настройки сервиса."""
    settings: Settings = request.app.state.settings
    return settings


def get_store(request: Request) -> Store:
    """Хранилище очереди."""
    store: Store = request.app.state.store
    return store


def get_outbox(request: Request) -> Outbox:
    """Воркер очереди отправки."""
    outbox: Outbox = request.app.state.outbox
    return outbox


def get_telegram(request: Request) -> Telegram:
    """Канал доставки."""
    telegram: Telegram = request.app.state.telegram
    return telegram


def get_bot(request: Request) -> Bot:
    """Клиент Telegram."""
    bot: Bot = request.app.state.bot
    return bot


def get_dispatcher(request: Request) -> Dispatcher:
    """Диспетчер aiogram с командами бота."""
    dispatcher: Dispatcher = request.app.state.dispatcher
    return dispatcher


type SettingsDep = Annotated[Settings, Depends(get_settings)]
type StoreDep = Annotated[Store, Depends(get_store)]
type OutboxDep = Annotated[Outbox, Depends(get_outbox)]
type TelegramDep = Annotated[Telegram, Depends(get_telegram)]
type BotDep = Annotated[Bot, Depends(get_bot)]
type DispatcherDep = Annotated[Dispatcher, Depends(get_dispatcher)]

__all__ = ["BotDep", "DispatcherDep", "OutboxDep", "SettingsDep", "StoreDep", "TelegramDep"]
