from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import ai as ai_service
from app.services import auth as auth_service
from app.services.object_storage import ObjectStorage


@pytest.fixture()
def client(tmp_path):
    with TestClient(app) as test_client:
        yield test_client


def test_health_contract(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ONLINE"
    assert payload["application"] == "MedAxis 3D"
    assert payload["version"] == "4.1.1"
    assert "capabilities" in payload


def test_readiness_contract(client):
    response = client.get("/api/system/readiness")
    assert response.status_code == 200
    payload = response.json()
    assert payload["classification"] == "RESEARCH / EDUCATIONAL USE"
    assert payload["clinical_validation"] == "NOT ESTABLISHED"
    assert "database" in payload
    assert "object_storage" in payload
    assert "monai" in payload
    assert "synthesis" in payload


def test_model_catalog_has_no_false_ready_models():
    assert ai_service.MODEL_CATALOG
    for model_id in ai_service.MODEL_CATALOG:
        status = ai_service.model_status(model_id)
        if status["status"] == "MODEL READY":
            assert status["inference_ready"] is True
            assert status["config_file"]
            assert status["weight_files"]
        else:
            assert status["inference_ready"] is False


def test_unknown_model_is_rejected():
    with pytest.raises(KeyError):
        ai_service.model_status("definitely-not-a-real-model")


def test_auth_secret_is_strict_when_required(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("JWT_SECRET", "short")
    with pytest.raises(RuntimeError):
        auth_service.jwt_secret()


def test_auth_secret_is_accepted_when_sufficient(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    secret = "a" * 64
    monkeypatch.setenv("JWT_SECRET", secret)
    assert auth_service.jwt_secret() == secret


def test_local_object_storage_round_trip(tmp_path, monkeypatch):
    monkeypatch.delenv("S3_BUCKET", raising=False)
    storage = ObjectStorage(tmp_path / "objects")
    source = tmp_path / "source.bin"
    source.write_bytes(b"medaxis-test")
    result = storage.put_path(source, "cases/test/source.bin")
    assert result["mode"] == "LOCAL"
    assert storage.exists("cases/test/source.bin")
    restored = storage.get_path("cases/test/source.bin")
    assert restored.read_bytes() == b"medaxis-test"
    storage.delete_prefix("cases/test")
    assert not storage.exists("cases/test/source.bin")


def test_self_registration_disabled_by_default(client, monkeypatch):
    monkeypatch.setenv("ALLOW_SELF_REGISTER", "false")
    response = client.post(
        "/api/auth/register",
        json={"username": "ci-user", "password": "StrongPassword123!", "role": "viewer"},
    )
    assert response.status_code == 403
