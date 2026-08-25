import json

import pytest

from app.monitoring import run_history
from app.monitoring.run_history import (
    AzureBlobHistoryBackend,
    LocalFileHistoryBackend,
    record_event,
    read_events,
)


class FakeDownloader:
    def __init__(self, payload: bytes):
        self._payload = payload

    def readall(self) -> bytes:
        return self._payload


class FakeBlobClient:
    def __init__(self):
        self.blocks: list[str] = []
        self.append_calls = 0
        self.create_calls = 0

    def exists(self) -> bool:
        return bool(self.blocks)

    def create_append_blob(self) -> None:
        self.create_calls += 1

    def append_block(self, data: str) -> None:
        self.append_calls += 1
        self.blocks.append(data)

    def download_blob(self) -> FakeDownloader:
        return FakeDownloader(
            "".join(self.blocks).encode("utf-8")
        )


class FakeContainerClient:
    def __init__(self):
        self.blobs: dict[str, FakeBlobClient] = {}

    def get_blob_client(self, name: str) -> FakeBlobClient:
        if name not in self.blobs:
            self.blobs[name] = FakeBlobClient()

        return self.blobs[name]


@pytest.fixture(autouse=True)
def reset_backend():
    run_history._backend = None

    yield

    run_history._backend = None


def test_local_backend_roundtrip(tmp_path, monkeypatch):
    history_path = tmp_path / "history.jsonl"

    monkeypatch.setattr(
        run_history,
        "HISTORY_PATH",
        history_path,
    )

    backend = LocalFileHistoryBackend()

    backend.append_line('{"a": 1}')
    backend.append_line('{"b": 2}')

    assert backend.read_lines() == [
        '{"a": 1}',
        '{"b": 2}',
    ]


def test_record_event_uses_local_backend(
    tmp_path,
    monkeypatch,
):
    history_path = tmp_path / "history.jsonl"

    monkeypatch.setattr(
        run_history,
        "HISTORY_PATH",
        history_path,
    )

    record_event({"record_type": "run", "outcome": "failed"})

    lines = history_path.read_text(
        encoding="utf-8"
    ).splitlines()

    assert len(lines) == 1
    assert json.loads(lines[0])["outcome"] == "failed"


def test_read_events_parses_records(tmp_path, monkeypatch):
    history_path = tmp_path / "history.jsonl"

    monkeypatch.setattr(
        run_history,
        "HISTORY_PATH",
        history_path,
    )

    record_event(
        {
            "record_type": "run",
            "run_id": "r1",
            "outcome": "failed",
        }
    )
    history_path.open("a", encoding="utf-8").write(
        "not-json\n"
    )

    events = read_events()

    assert len(events) == 1
    assert events[0]["run_id"] == "r1"


def test_azure_backend_appends_to_append_blob():
    container = FakeContainerClient()
    backend = AzureBlobHistoryBackend(
        container_client=container,
        blob_name="monitoring/run_history.jsonl",
    )

    backend.append_line('{"run_id": "r1"}')
    backend.append_line('{"run_id": "r2"}')

    blob = container.blobs["monitoring/run_history.jsonl"]

    assert blob.create_calls == 1
    assert blob.append_calls == 2
    assert backend.read_lines() == [
        '{"run_id": "r1"}',
        '{"run_id": "r2"}',
    ]


def test_azure_backend_creates_missing_blob():
    container = FakeContainerClient()
    backend = AzureBlobHistoryBackend(
        container_client=container,
        blob_name="monitoring/run_history.jsonl",
    )

    blob = container.blobs["monitoring/run_history.jsonl"]
    blob.exists = lambda: False

    backend.append_line('{"ok": true}')

    assert blob.create_calls == 1
    assert blob.append_calls == 1


def test_azure_backend_read_empty_when_absent():
    container = FakeContainerClient()
    backend = AzureBlobHistoryBackend(
        container_client=container,
        blob_name="monitoring/run_history.jsonl",
    )

    blob = container.blobs["monitoring/run_history.jsonl"]
    blob.exists = lambda: False

    assert backend.read_lines() == []


def test_record_event_survives_backend_failure(monkeypatch):
    class FailingBackend:
        name = "failing"

        def append_line(self, line: str) -> None:
            raise ConnectionError("blob unreachable")

        def read_lines(self):
            return []

    failing = FailingBackend()

    monkeypatch.setattr(
        run_history,
        "_get_backend",
        lambda: failing,
    )

    record_event({"record_type": "run"})

    events = read_events()

    assert events == []
