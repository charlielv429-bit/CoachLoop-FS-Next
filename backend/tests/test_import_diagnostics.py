import subprocess
import pytest
from fastapi.testclient import TestClient
from app import main, library_api, library_store
from pdf_factory import make_pdf


@pytest.mark.parametrize(
    "failure,code",
    [
        ("timeout", "PDF_PRECHECK_TIMEOUT"),
        ("start", "PDF_WORKER_START_FAILED"),
        ("signal", "PDF_WORKER_TERMINATED"),
        ("reject", "PDF_PRECHECK_REJECTED"),
        ("response", "PDF_WORKER_RESPONSE_INVALID"),
        ("invalid_pages", "PDF_WORKER_RESPONSE_INVALID"),
    ],
)
def test_precheck_stage_and_sanitized_error(monkeypatch, failure, code):
    private = "PRIVATE_DOCUMENT_TEXT_MUST_NOT_LEAK"

    def run(*args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("worker", 25, stderr=private)
        if failure == "start":
            raise OSError(private)
        return subprocess.CompletedProcess(
            [],
            -9 if failure == "signal" else 1 if failure == "reject" else 0,
            b'{"pages":true}' if failure == "invalid_pages" else private.encode(),
            private.encode(),
        )

    monkeypatch.setattr(library_api, "run_worker", run)
    with TestClient(main.app, base_url="http://127.0.0.1") as client:
        response = client.post(
            "/api/library/documents",
            params={"title": "Self-authored diagnostic fixture"},
            content=make_pdf(),
            headers={
                "Content-Type": "application/pdf",
                "Origin": "http://127.0.0.1:5175",
            },
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert (
            detail["stage"] == "pdf_precheck"
            and detail["code"] == code
            and detail["advice"]
        )
        assert private not in response.text
        assert library_store.documents() == []
        assert not list(library_store.root().glob("*.part"))
