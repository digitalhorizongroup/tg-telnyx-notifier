"""Логирование: единственный поток в stdout, пороги врозь для своих и чужих.

Файловых обработчиков и ротации здесь нет намеренно. Сервис живёт в контейнере,
а там журнал собирает драйвер логов docker — файл внутри образа он не читает, и
второй экземпляр записей пришлось бы вычищать томом и ретенцией. Единственный
поток в stdout снимает и то, и другое; ``PYTHONUNBUFFERED`` в Dockerfile не даёт
ему всплывать пачками.

Время в записях — UTC с суффиксом ``Z``. Без него запись выглядит местной, и
разбор инцидента начинается с угадывания зоны контейнера.
"""

import logging
import sys
import time

from tgtn.core.config.environ import Settings

SERVICE = "tgtn"

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%SZ"


def setup_logging(settings: Settings) -> None:
    """Настроить root-логгер: единственный обработчик в stdout, пороги из настроек.

    Зовётся один раз на старте, до подъёма цикла событий. Уже установленные
    обработчики отцепляются, поэтому повторный вызов не удваивает вывод — и
    заодно снимает тот, что ставит ``logging.basicConfig`` внутри чужой
    библиотеки.

    Args:
        settings: Пороги для своего дерева логгеров и для сторонних библиотек.
    """
    levels = logging.getLevelNamesMapping()
    root_level = levels[settings.lib_log_level]
    app_level = levels[settings.app_log_level]
    # Обработчик обязан пропускать более подробный из двух порогов, иначе
    # отрежет записи, которые более щедрый логгер намеренно выпустил.
    handler_level = min(root_level, app_level)

    root_logger = logging.getLogger()
    root_logger.setLevel(root_level)
    logging.getLogger(SERVICE).setLevel(app_level)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(fmt=_FORMAT, datefmt=_DATE_FORMAT)
    formatter.converter = time.gmtime

    # stdout, а не stderr по умолчанию: журнал сервиса — не поток ошибок, и в
    # `docker logs` они всё равно сходятся вместе.
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(handler_level)
    console.setFormatter(formatter)
    root_logger.addHandler(console)


__all__ = ["SERVICE", "setup_logging"]
