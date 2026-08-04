"""Настройки из окружения ``TGTN_*``: чем бот входит в Telegram и куда постит.

Значения приходят из переменных окружения, а на разработческой машине — из
файла ``.env`` рядом с манифестом. Приоритет стандартный для pydantic-settings:
переменная окружения перекрывает файл, поэтому ``TGTN_CHAT_ID=… docker run``
меняет адресата на один запуск, не трогая ``.env``.

Настройки неизменны после загрузки (``frozen=True``): перечитывать конфиг на
живом процессе нечем и незачем — рестарт дешевле, чем согласование половины
процесса, увидевшей новое значение, с половиной, оставшейся на старом.
"""

from functools import cached_property
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BeforeValidator, SecretStr
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def _split_ids(value: object) -> object:
    """Разобрать список идентификаторов, записанный через запятую.

    В ``.env`` строка ``1,2`` читается человеком лучше, чем JSON-массив, а
    pydantic без этого ждёт именно JSON. Значение не-строка уходит дальше как
    есть: так же поле задаётся напрямую в тестах.
    """
    if isinstance(value, str):
        return [chunk.strip() for chunk in value.split(",") if chunk.strip()]
    return value


# `NoDecode` обязателен: множество — составной тип, и без него pydantic-settings
# разбирает значение переменной как JSON ещё до валидаторов. Пустая строка и
# `1,2` на этом разборе падают, не доходя до `_split_ids`.
type AdminIds = Annotated[frozenset[int], NoDecode, BeforeValidator(_split_ids)]


class Settings(BaseSettings):
    """Настройки сервиса.

    Attributes:
        bot_token: Токен бота от BotFather. ``SecretStr``, чтобы значение не
            утекло в журнал ни через ``repr`` настроек, ни через трассировку
            падения: наружу такое поле печатается как ``**********``, а сама
            строка достаётся явным ``.get_secret_value()``.
        chat_id: Куда уходят сообщения. Числовой идентификатор, а не ``@имя``:
            у канала имя может смениться, идентификатор — нет. У каналов и
            супергрупп он отрицательный, у личной переписки положительный.
        admin_ids: Кому кроме канала отвечает команда активности. Пустое
            множество — команда работает только в самом канале.
        public_url: Внешний адрес сервиса без завершающего слэша; по нему
            Telegram доставляет апдейты. ``None`` — webhook не регистрируется, и
            команда активности недоступна: локально внешнего адреса нет.
        telegram_webhook_secret: Общий секрет с Telegram. Уходит в ``setWebhook``
            и приезжает обратно заголовком ``X-Telegram-Bot-Api-Secret-Token``:
            маршрут апдейтов открыт наружу, и это единственное, что отличает
            Telegram от постороннего.
        data_dir: Каталог рантайм-данных. В контейнере — точка монтирования
            тома, поэтому настраивается, а не вычисляется.
        history_days: Сколько суток доставленные сообщения лежат в базе.
            Отправленное старше этого срока удаляется на старте.
        send_base_delay: Пауза между отправками, когда очередь спокойна.
        send_max_delay: Потолок паузы при непрерывном наплыве.
        host: Адрес привязки HTTP-сервера. ``0.0.0.0`` — в контейнере свой адрес
            заранее неизвестен, а ``127.0.0.1`` закрыл бы порт вместе с внешним
            миром и от того, кто пробрасывает webhook.
        port: Порт HTTP-сервера; тот же, что открывает ``EXPOSE`` в образе.
        lib_log_level: Порог для сторонних библиотек; они наследуют его от
            root-логгера.
        app_log_level: Порог для дерева логгеров самого сервиса, независимый от
            ``lib_log_level``, — свои записи держатся подробными, не заливая
            вывод чужими.
    """

    model_config = SettingsConfigDict(
        env_prefix="TGTN_",
        env_file=".env",
        env_file_encoding="utf-8",
        # В окружении контейнера живут и чужие переменные (PATH, HOME); лишнее
        # под нашим префиксом тоже не роняет старт.
        extra="ignore",
        case_sensitive=False,
        frozen=True,
    )

    bot_token: SecretStr
    chat_id: int
    admin_ids: AdminIds = frozenset()

    public_url: str | None = None
    telegram_webhook_secret: SecretStr

    data_dir: Path = Path(".project")
    history_days: int = 30

    send_base_delay: float = 5.0
    send_max_delay: float = 30.0

    host: str = "0.0.0.0"
    port: int = 8000

    lib_log_level: LogLevel = "INFO"
    app_log_level: LogLevel = "DEBUG"

    @classmethod
    def load(cls) -> Self:
        """Собрать настройки из окружения процесса.

        Через ``model_validate({})``, а не ``cls()``: плагин ``pydantic.mypy``
        восстанавливает сигнатуру конструктора по полям и требует обязательные
        аргументы, которых при чтении из окружения не передают.

        Raises:
            ValidationError: Если обязательное значение не задано ни в
                окружении, ни в ``.env``. Падение на старте, а не отказ на
                первом же сообщении.
        """
        return cls.model_validate({})

    @cached_property
    def database_path(self) -> Path:
        """Файл базы очереди; каталог заводится при первом обращении."""
        self.data_dir.mkdir(exist_ok=True, parents=True)
        return self.data_dir / "tgtn.sqlite3"

    @cached_property
    def telegram_webhook_url(self) -> str | None:
        """Полный адрес маршрута апдейтов или ``None``, если внешний адрес не задан."""
        if self.public_url is None:
            return None
        return f"{self.public_url.rstrip('/')}{TELEGRAM_WEBHOOK_PATH}"


TELEGRAM_WEBHOOK_PATH = "/telegram/updates"

__all__ = ["TELEGRAM_WEBHOOK_PATH", "AdminIds", "LogLevel", "Settings"]
