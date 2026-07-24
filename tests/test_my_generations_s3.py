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
