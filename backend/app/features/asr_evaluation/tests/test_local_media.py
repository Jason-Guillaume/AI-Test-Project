"""平台持久保存的音频必须授权读取并支持拖动试听。"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from app.features.asr_evaluation.models import AsrAudio
from app.features.asr_evaluation.services import media_service


def test_managed_audio_supports_range_and_enforces_project_access(tmp_path, monkeypatch):
    key = "a" * 64 + ".m4a"
    directory = tmp_path / "media"
    directory.mkdir()
    (directory / key).write_bytes(b"0123456789")
    monkeypatch.setattr(media_service.settings, "ASR_ARTIFACT_DIR", str(tmp_path))
    audio = SimpleNamespace(id=7, project_id=2)
    version = SimpleNamespace(id=9, audio_id=7, source_info={"local_media_key": key})
    db = SimpleNamespace(get=lambda cls, _: audio if cls is AsrAudio else version)
    allowed = [True]

    def authorize(*_):
        if not allowed[0]:
            raise HTTPException(404)

    monkeypatch.setattr(media_service, "get_project_or_404", authorize)
    app = FastAPI()

    @app.get("/media")
    def media(range: str | None = Header(None)):
        return media_service.stream_audio(db, 7, SimpleNamespace(), range, audio_version_id=9)

    with TestClient(app) as client:
        result = client.get("/media", headers={"Range": "bytes=3-6"})
        assert result.status_code == 206
        assert result.content == b"3456"
        assert result.headers["content-range"] == "bytes 3-6/10"
        assert result.headers["content-type"] == "audio/mp4"
        assert client.get("/media", headers={"Range": "bytes=20-"}).status_code == 416
        assert client.get("/media", headers={"Range": "bytes=0-1,4-5"}).status_code == 400
        allowed[0] = False
        assert client.get("/media").status_code == 404


def test_managed_audio_rejects_paths_and_symlinks_outside_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(media_service.settings, "ASR_ARTIFACT_DIR", str(tmp_path))
    with pytest.raises(HTTPException):
        media_service._managed_audio_path(SimpleNamespace(source_info={"local_media_key": "../secret.m4a"}))
    directory = tmp_path / "media"
    directory.mkdir()
    outside = tmp_path / "secret.m4a"
    outside.write_bytes(b"private")
    key = "b" * 64 + ".m4a"
    (directory / key).symlink_to(outside)
    with pytest.raises(HTTPException):
        media_service._managed_audio_path(SimpleNamespace(source_info={"local_media_key": key}))
