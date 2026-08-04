import logging

import pytest
from pydantic import ValidationError

from tgtn.core.config import SERVICE, Settings, setup_logging

TOKEN = "111:AAAsecret-value-that-must-not-leak"
CHAT_ID = -1001234567890


def build_settings(**overrides: object) -> Settings:
    return Settings.model_validate({"bot_token": TOKEN, "chat_id": CHAT_ID, **overrides})


def test_values_are_read_from_the_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("TGTN_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TGTN_CHAT_ID", str(CHAT_ID))

    # Act
    settings = Settings.load()

    # Assert
    assert settings.bot_token.get_secret_value() == TOKEN
    assert settings.chat_id == CHAT_ID


def test_missing_token_fails_on_load_not_on_first_message(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.delenv("TGTN_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TGTN_CHAT_ID", str(CHAT_ID))

    # Act / Assert
    with pytest.raises(ValidationError, match="bot_token"):
        Settings.model_validate({"chat_id": CHAT_ID, "_env_file": None})


def test_token_is_hidden_from_repr() -> None:
    # Arrange
    settings = build_settings()

    # Assert
    assert TOKEN not in repr(settings)


def test_settings_are_frozen_after_load() -> None:
    # Arrange
    settings = build_settings()

    # Act / Assert
    # Через setattr, а не прямым присваиванием: прямое отвергает уже mypy
    # (поле read-only), а проверяется здесь рантайм-запрет pydantic.
    with pytest.raises(ValidationError):
        setattr(settings, "chat_id", 42)


def test_default_log_levels_split_own_records_from_library_ones() -> None:
    # Arrange
    settings = build_settings()

    # Assert
    assert settings.app_log_level == "DEBUG"
    assert settings.lib_log_level == "INFO"


@pytest.mark.usefixtures("restore_logging")
def test_setup_logging_applies_both_thresholds() -> None:
    # Arrange
    settings = build_settings(app_log_level="WARNING", lib_log_level="ERROR")

    # Act
    setup_logging(settings)

    # Assert
    assert logging.getLogger().level == logging.ERROR
    assert logging.getLogger(SERVICE).level == logging.WARNING


@pytest.mark.usefixtures("restore_logging")
def test_handler_passes_the_more_verbose_of_the_two_thresholds() -> None:
    # Arrange
    settings = build_settings(app_log_level="DEBUG", lib_log_level="ERROR")

    # Act
    setup_logging(settings)

    # Assert
    assert logging.getLogger().handlers[0].level == logging.DEBUG


@pytest.mark.usefixtures("restore_logging")
def test_repeated_setup_does_not_duplicate_output() -> None:
    # Arrange
    settings = build_settings()

    # Act
    setup_logging(settings)
    setup_logging(settings)

    # Assert
    assert len(logging.getLogger().handlers) == 1
