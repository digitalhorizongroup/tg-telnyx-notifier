import logging

import pytest
from pydantic import ValidationError

from tests.conftest import CHAT_ID, TOKEN, SettingsFactory
from tgtn.core.config import SERVICE, Settings, setup_logging


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

    # Act / Assert
    with pytest.raises(ValidationError, match="bot_token"):
        Settings.model_validate({"chat_id": CHAT_ID, "_env_file": None})


def test_token_is_hidden_from_repr(settings: Settings) -> None:
    assert TOKEN not in repr(settings)


def test_webhook_secret_is_hidden_from_repr(settings: Settings) -> None:
    assert settings.telegram_webhook_secret.get_secret_value() not in repr(settings)


def test_settings_are_frozen_after_load(settings: Settings) -> None:
    # Act / Assert
    # Через setattr, а не прямым присваиванием: прямое отвергает уже mypy
    # (поле read-only), а проверяется здесь рантайм-запрет pydantic.
    with pytest.raises(ValidationError):
        setattr(settings, "chat_id", 42)


def test_default_log_levels_split_own_records_from_library_ones(settings: Settings) -> None:
    assert settings.app_log_level == "DEBUG"
    assert settings.lib_log_level == "INFO"


def test_default_delays_match_the_agreed_schedule(settings: Settings) -> None:
    assert settings.send_base_delay == 5.0
    assert settings.send_max_delay == 30.0


def test_webhook_url_is_built_from_the_public_address(make_settings: SettingsFactory) -> None:
    # Arrange: завершающий слэш встречается в адресах и не должен удваиваться.
    settings = make_settings(public_url="https://example.com/")

    # Assert
    assert settings.telegram_webhook_url == "https://example.com/telegram/updates"


def test_without_a_public_address_there_is_no_webhook_url(settings: Settings) -> None:
    assert settings.telegram_webhook_url is None


def test_database_lives_inside_the_data_directory(make_settings: SettingsFactory, tmp_path: object) -> None:
    # Arrange
    settings = make_settings(data_dir=tmp_path)

    # Assert
    assert settings.database_path.parent == tmp_path
    assert settings.database_path.name == "tgtn.sqlite3"


@pytest.mark.usefixtures("restore_logging")
def test_setup_logging_applies_both_thresholds(make_settings: SettingsFactory) -> None:
    # Arrange
    settings = make_settings(app_log_level="WARNING", lib_log_level="ERROR")

    # Act
    setup_logging(settings)

    # Assert
    assert logging.getLogger().level == logging.ERROR
    assert logging.getLogger(SERVICE).level == logging.WARNING


@pytest.mark.usefixtures("restore_logging")
def test_handler_passes_the_more_verbose_of_the_two_thresholds(make_settings: SettingsFactory) -> None:
    # Arrange
    settings = make_settings(app_log_level="DEBUG", lib_log_level="ERROR")

    # Act
    setup_logging(settings)

    # Assert
    assert logging.getLogger().handlers[0].level == logging.DEBUG


@pytest.mark.usefixtures("restore_logging")
def test_repeated_setup_does_not_duplicate_output(settings: Settings) -> None:
    # Act
    setup_logging(settings)
    setup_logging(settings)

    # Assert
    assert len(logging.getLogger().handlers) == 1
