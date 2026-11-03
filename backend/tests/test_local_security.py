import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app, base_url="http://127.0.0.1")


@pytest.mark.parametrize(
    "origin",
    [
        "http://127.0.0.1:5175",
        "http://localhost:5175",
        "http://localhost:4173",
        "http://localhost:8001",
        "http://[::1]:5175",
        "https://localhost:5175",
    ],
)
def test_vite_fallback_local_origins(origin):
    response = client.get("/api/status", headers={"Origin": origin})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "http://localhost.evil.example:5175",
        "http://192.168.1.20:5175",
        "null",
        "http://127.0.0.1:99999",
        "http://user@localhost:5175",
        "http://localhost:5175/path",
        "http://localhost:5175?private=1",
    ],
)
def test_remote_and_malformed_origins_still_rejected(origin):
    response = client.get("/api/status", headers={"Origin": origin})
    assert response.status_code == 403
    assert response.json()["code"] == "ORIGIN_NOT_LOOPBACK"
    assert "access-control-allow-origin" not in response.headers


def test_cors_patch_and_upload_preflight_share_same_policy():
    for method in ("POST", "PATCH", "PUT", "DELETE"):
        response = client.options(
            "/api/library/documents",
            headers={
                "Origin": "http://127.0.0.1:5175",
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code == 200
        assert (
            response.headers["access-control-allow-origin"] == "http://127.0.0.1:5175"
        )
    assert (
        client.options(
            "/api/library/documents",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
            },
        ).status_code
        == 400
    )


def test_forwarded_origin_does_not_bypass_host_guard():
    response = client.get(
        "/api/status",
        headers={
            "Host": "evil.example",
            "Origin": "http://127.0.0.1:5175",
            "X-Forwarded-Host": "localhost",
        },
    )
    assert (
        response.status_code == 403 and response.json()["code"] == "HOST_NOT_LOOPBACK"
    )


def test_test_client_hostname_is_not_a_production_exception():
    assert client.get('/api/status',headers={'Host':'testserver'}).status_code==403
