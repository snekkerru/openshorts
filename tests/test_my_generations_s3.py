import pytest
pytest.importorskip("boto3")  # container/local only; CI env has no boto3

import s3_uploader


def test_get_s3_client_passes_endpoint_url(monkeypatch):
    captured = {}

    def fake_client(service, **kwargs):
        captured["service"] = service
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(s3_uploader.boto3, "client", fake_client)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s")
    monkeypatch.setenv("AWS_REGION", "fra1")
    monkeypatch.setenv("AWS_S3_ENDPOINT_URL", "https://fra1.digitaloceanspaces.com")

    s3_uploader.get_s3_client()
    assert captured["kwargs"]["endpoint_url"] == "https://fra1.digitaloceanspaces.com"
    assert captured["kwargs"]["region_name"] == "fra1"


def test_get_s3_client_no_endpoint_when_unset(monkeypatch):
    captured = {}
    monkeypatch.setattr(s3_uploader.boto3, "client", lambda service, **kw: captured.update(kw) or object())
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s")
    monkeypatch.delenv("AWS_S3_ENDPOINT_URL", raising=False)
    s3_uploader.get_s3_client()
    assert captured.get("endpoint_url") is None


# ── Task 3: S3 history I/O tests ──

import json


class _FakeS3:
    """Minimal in-memory S3 stand-in covering the calls the history fns make."""
    def __init__(self):
        self.store = {}  # key -> bytes

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.store[Key] = Body if isinstance(Body, bytes) else Body.encode()

    def upload_file(self, filename, Bucket, Key, ExtraArgs=None):
        with open(filename, "rb") as f:
            self.store[Key] = f.read()

    def get_object(self, Bucket, Key):
        import io
        return {"Body": io.BytesIO(self.store[Key])}

    def head_object(self, Bucket, Key):
        if Key not in self.store:
            from botocore.exceptions import ClientError
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {}

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"https://signed/{Params['Key']}"

    class _Paginator:
        def __init__(self, store): self.store = store
        def paginate(self, Bucket, Prefix):
            yield {"Contents": [{"Key": k, "LastModified": k} for k in self.store if k.startswith(Prefix)]}

    def get_paginator(self, name):
        return _FakeS3._Paginator(self.store)

    def delete_object(self, Bucket, Key):
        self.store.pop(Key, None)


def _patch_client(monkeypatch, fake):
    monkeypatch.setattr(s3_uploader, "get_s3_client", lambda: fake)
    monkeypatch.setenv("AWS_S3_BUCKET", "hist")


def test_save_and_list_roundtrip(monkeypatch, tmp_path):
    fake = _FakeS3()
    _patch_client(monkeypatch, fake)
    video = tmp_path / "v.mp4"; video.write_bytes(b"MP4")
    meta = {"job_id": "j1", "status": "processing", "title": "T"}

    assert s3_uploader.save_generation_record("local", "j1", meta, "completed",
                                              video_path=str(video)) is True
    key = "my-generations/local/j1/metadata.json"
    saved = json.loads(fake.store[key].decode())
    assert saved["status"] == "completed"
    assert saved["created_at"] and saved["updated_at"]
    assert "my-generations/local/j1/video.mp4" in fake.store

    out = s3_uploader.list_my_generations("local")
    assert len(out) == 1
    assert out[0]["job_id"] == "j1"
    assert out[0]["video_url"] == "https://signed/my-generations/local/j1/video.mp4"


def test_save_preserves_created_at(monkeypatch):
    fake = _FakeS3()
    _patch_client(monkeypatch, fake)
    s3_uploader.save_generation_record("local", "j1", {"job_id": "j1"}, "processing")
    first = json.loads(fake.store["my-generations/local/j1/metadata.json"].decode())
    s3_uploader.save_generation_record("local", "j1", {"job_id": "j1"}, "completed")
    second = json.loads(fake.store["my-generations/local/j1/metadata.json"].decode())
    assert second["created_at"] == first["created_at"]


def test_list_scoped_to_owner(monkeypatch):
    fake = _FakeS3()
    _patch_client(monkeypatch, fake)
    s3_uploader.save_generation_record("me", "j1", {"job_id": "j1"}, "completed")
    s3_uploader.save_generation_record("other", "j2", {"job_id": "j2"}, "completed")
    out = s3_uploader.list_my_generations("me")
    assert [r["job_id"] for r in out] == ["j1"]


def test_delete_removes_prefix(monkeypatch):
    fake = _FakeS3()
    _patch_client(monkeypatch, fake)
    s3_uploader.save_generation_record("local", "j1", {"job_id": "j1"}, "completed")
    assert s3_uploader.delete_my_generation("local", "j1") is True
    assert not any(k.startswith("my-generations/local/j1/") for k in fake.store)


def test_save_noop_without_client(monkeypatch):
    monkeypatch.setattr(s3_uploader, "get_s3_client", lambda: None)
    assert s3_uploader.save_generation_record("local", "j1", {}, "processing") is False
    assert s3_uploader.list_my_generations("local") == []
