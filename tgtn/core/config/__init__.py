"""Конфигурация сервиса: значения из окружения и настройка логирования.

Разделение по вопросу, на который отвечает модуль: ``environ.py`` — откуда
берутся значения, ``logger.py`` — что делать с двумя из них.
"""

from tgtn.core.config.environ import LogLevel, Settings
from tgtn.core.config.logger import SERVICE, setup_logging

__all__ = ["SERVICE", "LogLevel", "Settings", "setup_logging"]
