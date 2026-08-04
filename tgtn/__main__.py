"""Точка входа сервиса: сборка ASGI-приложения и запуск сервера на uvloop."""

from collections.abc import Sequence

import uvicorn
from fastapi import APIRouter, FastAPI

from tgtn import __version__
from tgtn.core.config import Settings, setup_logging
from tgtn.handlers import ROUTERS


def create_app(settings: Settings, routers: Sequence[APIRouter] = ROUTERS) -> FastAPI:
    """Собрать приложение из маршрутизаторов.

    Args:
        settings: Настройки сервиса; кладутся в состояние приложения, потому что
            обработчик доступа к ним иначе не имеет — ему видно только запрос.
        routers: Чем набирается поверхность. По умолчанию весь сервис; тест
            передаёт ровно те маршрутизаторы, которые проверяет, и получает
            приложение без чужих маршрутов.
    """
    app = FastAPI(title="tg-telnyx-notifier", version=__version__)
    app.state.settings = settings
    for router in routers:
        app.include_router(router)
    return app


def main() -> None:
    """Поднять HTTP-сервис на цикле uvloop.

    Настройки и логирование встают до сервера: неверное окружение роняет процесс,
    пока поднимать и гасить ещё нечего.
    """
    settings = Settings.load()
    setup_logging(settings)
    uvicorn.run(
        # Приложение уходит объектом, а не строкой импорта: строка нужна только
        # для `workers` и `reload`, а сервис работает в один процесс.
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
