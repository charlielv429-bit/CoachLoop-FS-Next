import pytest
from app import library_store


@pytest.fixture(autouse=True)
def private_test_library(tmp_path, monkeypatch):
    monkeypatch.setenv("COACHLOOP_LIBRARY_DIR", str(tmp_path / "private-library"))
    library_store.initialize()
