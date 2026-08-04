"""Точка входа сервиса: сборка ASGI-приложения и запуск сервера на uvloop."""

import logging
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager

import uvicorn
from aiogram import Bot, Dispatcher
from fastapi import APIRouter, FastAPI

from tgtn import __version__
from tgtn.core.config import Settings, setup_logging
from tgtn.core.outbox import Outbox
from tgtn.core.store import Store
from tgtn.core.telegram import Telegram
from tgtn.handlers import ROUTERS, commands

LOG = logging.getLogger(__name__)


def create_app(settings: Settings, routers: Sequence[APIRouter] = ROUTERS) -> FastAPI:
    """Собрать приложение из маршрутизаторов.

    Args:
        settings: Настройки сервиса; кладутся в состояние приложения, потому что
            обработчик доступа к ним иначе не имеет — ему видно только запрос.
        routers: Чем набирается поверхность. По умолчанию весь сервис; тест
            передаёт ровно те маршрутизаторы, которые проверяет, и получает
            приложение без чужих маршрутов.
    """
    app = FastAPI(title="tg-telnyx-notifier", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    for router in routers:
        app.include_router(router)
    return app


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Поднять базу, бота и воркер очереди до первого запроса и закрыть после последнего.

    Всё это строится здесь, а не в :func:`create_app`: соединение с базой и
    примитивы ``asyncio`` требуют работающего цикла, а приложение собирается до
    него. База открывается раньше сокета — первый же webhook застаёт готовую
    очередь.
    """
    settings: Settings = app.state.settings

    store = Store(settings.database_path)
    await store.open()
    purged = await store.purge(settings.history_days)

    bot = Bot(token=settings.bot_token.get_secret_value())
    telegram = Telegram(bot, settings.chat_id)
    outbox = Outbox(store, telegram, settings.send_base_delay, settings.send_max_delay)

    dispatcher = Dispatcher(settings=settings, store=store, outbox=outbox, telegram=telegram)
    dispatcher.include_router(commands.build_router())

    app.state.store = store
    app.state.bot = bot
    app.state.telegram = telegram
    app.state.outbox = outbox
    app.state.dispatcher = dispatcher

    await outbox.start()
    await _register_webhook(settings, telegram)
    LOG.info("очередь готова, база %s; удалено старых записей — %d", settings.database_path, purged)

    try:
        yield
    finally:
        # Порядок обратный подъёму: сперва снимается воркер, чтобы он не
        # обратился к закрытой сессии бота или закрытой базе.
        await outbox.stop()
        await telegram.close()
        await store.close()


async def _register_webhook(settings: Settings, telegram: Telegram) -> None:
    """Указать Telegram адрес для апдейтов, если внешний адрес известен.

    Без ``public_url`` регистрировать нечего: локально внешнего адреса нет, и
    сервис работает как обычно — молча остаётся без команды активности, о чём и
    предупреждает.
    """
    url = settings.telegram_webhook_url
    if url is None:
        LOG.warning("TGTN_PUBLIC_URL не задан: команда активности недоступна, пересылка сообщений работает")
        return
    await telegram.register_webhook(url, settings.telegram_webhook_secret.get_secret_value())


def main() -> None:
    """Поднять HTTP-сервис на цикле uvloop.

    Настройки и логирование встают до сервера: неверное окружение роняет процесс,
    пока поднимать и гасить ещё нечего. Цикл поднимает сам uvicorn — асинхронной
    половины у точки входа нет, всё, что работает внутри цикла, живёт в
    :func:`lifespan`.
    """
    settings = Settings.load()
    setup_logging(settings)
    uvicorn.run(
        # Приложение уходит объектом, а не строкой импорта: строка нужна только
        # для `workers` и `reload`, а сервис работает в один процесс — очередь и
        # её воркер живут в нём же.
        create_app(settings),
        host=settings.host,
        port=settings.port,
        # Цикл выбирается явно, а не значением `auto`: при неустановленном
        # uvloop `auto` молча берёт цикл из стандартной библиотеки, и подмену
        # видно только по нагрузке. uvloop здесь в основных зависимостях, так
        # что ветки без него нет.
        loop="uvloop",
        # Логирование uvicorn отключено, а не настроено: его dictConfig снёс бы
        # обработчик, который только что поставил setup_logging.
        log_config=None,
    )


if __name__ == "__main__":
    main()
