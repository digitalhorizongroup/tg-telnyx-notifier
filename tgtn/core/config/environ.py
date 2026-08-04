"""Настройки из окружения ``TGTN_*``: чем бот входит в Telegram и куда постит.

Значения приходят из переменных окружения, а на разработческой машине — из
файла ``.env`` рядом с манифестом. Приоритет стандартный для pydantic-settings:
переменная окружения перекрывает файл, поэтому ``TGTN_CHAT_ID=… docker run``
меняет адресата на один запуск, не трогая ``.env``.

Настройки неизменны после загрузки (``frozen=True``): перечитывать конфиг на
живом процессе нечем и незачем — рестарт дешевле, чем согласование половины
процесса, увидевшей новое значение, с половиной, оставшейся на старом.
"""

from typing import Literal, Self

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


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

    lib_log_level: LogLevel = "INFO"
    app_log_level: LogLevel = "DEBUG"

    @classmethod
    def load(cls) -> Self:
        """Собрать настройки из окружения процесса.

        Через ``model_validate({})``, а не ``cls()``: плагин ``pydantic.mypy``
        восстанавливает сигнатуру конструктора по полям и требует обязательные
        аргументы, которых при чтении из окружения не передают.

        Raises:
            ValidationError: Если ``TGTN_BOT_TOKEN`` или ``TGTN_CHAT_ID`` не
                заданы ни в окружении, ни в ``.env``. Падение на старте, а не
                отказ на первом же сообщении.
        """
        return cls.model_validate({})


__all__ = ["LogLevel", "Settings"]
