import pytest
import uvicorn
from fastapi.testclient import TestClient

from tests.conftest import CHAT_ID, SECRET, TOKEN
from tgtn import __version__
from tgtn.__main__ import create_app, main
from tgtn.core.config import Settings
from tgtn.handlers import ROUTERS
from tgtn.handlers.health import router as health_router


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


def test_health_reports_ok_with_the_running_version(client: TestClient) -> None:
    # Act
    response = client.get("/health")

    # Assert
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_unknown_path_is_not_served(client: TestClient) -> None:
    assert client.get("/").status_code == 404


def test_settings_are_reachable_from_application_state(settings: Settings) -> None:
    # Act
    app = create_app(settings)

    # Assert
    assert app.state.settings is settings


def test_surface_is_limited_to_the_routers_passed_in(settings: Settings) -> None:
    # Arrange
    app = create_app(settings, routers=())

    # Act
    response = TestClient(app).get("/health")

    # Assert
    assert response.status_code == 404


def test_health_router_is_part_of_the_default_surface() -> None:
    assert health_router in ROUTERS


@pytest.mark.usefixtures("restore_logging")
def test_main_serves_on_uvloop_with_the_configured_address(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("TGTN_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TGTN_CHAT_ID", str(CHAT_ID))
    monkeypatch.setenv("TGTN_TELEGRAM_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("TGTN_HOST", "127.0.0.1")
    monkeypatch.setenv("TGTN_PORT", "9001")
    captured: dict[str, object] = {}

    def capture(app: object, **options: object) -> None:
        captured["app"] = app
        captured.update(options)

    monkeypatch.setattr(uvicorn, "run", capture)

    # Act
    main()

    # Assert
    assert captured["loop"] == "uvloop"
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9001
    # Иначе dictConfig uvicorn снёс бы обработчик, поставленный setup_logging.
    assert captured["log_config"] is None
