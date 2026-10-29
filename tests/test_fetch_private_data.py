from __future__ import annotations

from pathlib import Path

import pytest
import requests

from scripts import fetch_private_data
from scripts.fetch_private_data import PRIVATE_FILES


class FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error")


def test_fetch_writes_every_private_file_with_bearer_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests_seen: list[tuple[str, str]] = []

    def fake_get(self: requests.Session, url: str, timeout: int) -> FakeResponse:
        requests_seen.append((url, self.headers["Authorization"]))
        return FakeResponse(f"rows for {url.rsplit('/', 1)[-1]}\n".encode())

    monkeypatch.setattr(requests.Session, "get", fake_get)

    fetch_private_data.fetch_private_data("owner/private-data", "test-token", tmp_path)

    assert len(requests_seen) == len(PRIVATE_FILES)
    assert all(header == "Bearer test-token" for _, header in requests_seen)
    assert requests_seen[0][0] == (
        "https://huggingface.co/datasets/owner/private-data/resolve/main/" + PRIVATE_FILES[0]
    )
    fancam = tmp_path / "data" / "play_zone" / "daily_fancam.csv"
    assert fancam.read_text(encoding="utf-8") == "rows for daily_fancam.csv\n"
    assert not list(tmp_path.rglob("*.part"))


def test_main_without_token_leaves_local_files_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)

    def fail_get(*args: object, **kwargs: object) -> None:
        raise AssertionError("must not download without HF_TOKEN")

    monkeypatch.setattr(requests.Session, "get", fail_get)

    assert fetch_private_data.main() == 0


def test_main_reports_failure_without_leaking_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HF_TOKEN", "secret-test-token")
    monkeypatch.setattr(
        requests.Session, "get", lambda self, url, timeout: FakeResponse(b"", status_code=401)
    )

    assert fetch_private_data.main() == 1
    captured = capsys.readouterr()
    assert "401" in captured.err
    assert "secret-test-token" not in captured.out + captured.err
