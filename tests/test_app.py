from fastapi.testclient import TestClient

from tg_telnyx_notifier import __version__
from tg_telnyx_notifier.app import app

client = TestClient(app)


def test_health_reports_ok_with_the_running_version() -> None:
    # Act
    response = client.get("/health")

    # Assert
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_unknown_path_is_not_served() -> None:
    assert client.get("/").status_code == 404
