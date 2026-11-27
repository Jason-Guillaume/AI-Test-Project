"""平台保存的音频通过真实项目归属检查后才能交给转写模型。"""

import hashlib
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database.base import Base
from app.core.security.crypto import encrypt_secret
from app.features.asr_evaluation.models import AsrAudio, AsrAudioVersion
from app.features.asr_evaluation.providers import audio_transcriptions
from app.features.asr_evaluation.providers.generic_json import AsrProviderError
from .test_audio_transcriptions import execution


@pytest.fixture
def managed_sandbox():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    tables = [Base.metadata.tables["asr_audio"], Base.metadata.tables["asr_audio_version"]]
    Base.metadata.create_all(engine, tables=tables)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    audio = AsrAudio(project_id=1, name="managed synthetic", url_ciphertext="cipher", url_display="managed synthetic")
    db.add(audio)
    db.flush()
    yield db, audio
    db.close()
    engine.dispose()


def test_managed_audio_upload_enforces_project_and_size(managed_sandbox, tmp_path, monkeypatch):
    db, audio = managed_sandbox
    content = b"synthetic managed recording"
    digest = hashlib.sha256(content).hexdigest()
    key = digest + ".m4a"
    uri = "managed-audio://" + key
    directory = tmp_path / "media"
    directory.mkdir()
    (directory / key).write_bytes(content)
    monkeypatch.setattr(settings, "ASR_ARTIFACT_DIR", str(tmp_path))
    audio.content_fingerprint = digest
    version = AsrAudioVersion(audio_id=audio.id, version=2, name="managed synthetic",
        url_ciphertext=encrypt_secret(uri), url_display="managed synthetic", content_fingerprint=digest,
        source_info={"local_media_key": key})
    db.add(version)
    db.commit()
    targets = []

    def authorize(_db, target, project_id):
        targets.append((target, project_id))
        return SimpleNamespace(rejection_message=None)

    monkeypatch.setattr(audio_transcriptions, "resolve_project_outbound_target", authorize)
    monkeypatch.setattr(audio_transcriptions.httpx, "Client", lambda **_: pytest.fail("must not fetch managed audio over HTTP"))
    uploads = []

    class Executor:
        def execute(self, _db, **kwargs):
            stream = kwargs["files"][0][1][1]
            uploads.append((stream, stream.read()))
            return "uploaded"

    config = execution(audio_url=uri)
    headers = {"Authorization": "Bearer synthetic"}

    def submit(project_id, **updates):
        return audio_transcriptions.send_audio_transcription(Executor(), db, project_id=project_id,
            method="POST", url=config["endpoint"], headers=headers, body={"parameters": {}},
            execution=dict(config, **updates))

    assert submit(audio.project_id) == "uploaded"
    assert uploads[0][1] == content and uploads[0][0].closed
    assert targets == [(config["endpoint"], audio.project_id)]
    with pytest.raises(AsrProviderError, match="当前项目"):
        submit(audio.project_id + 100)
    with pytest.raises(AsrProviderError, match="大小上限"):
        submit(audio.project_id, max_audio_bytes=2)
    assert len(uploads) == 1