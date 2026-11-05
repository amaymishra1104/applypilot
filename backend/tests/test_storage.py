import os
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

sys.path.insert(0, str(Path(__file__).parent.parent))

from db import db, utc_now_iso
from server import app
from storage import (
    BaseStorage,
    LocalStorage,
    S3Storage,
    get_object,
    get_storage_backend,
    object_exists,
    put_object,
    reset_storage_backend,
)


def test_local_storage_put_get_exists_delete(tmp_path):
    storage = LocalStorage(upload_dir=str(tmp_path))
    storage.init_storage()

    test_data = b"%PDF-1.4 test resume pdf bytes"
    path = "resumes/user123/resume_v1.pdf"

    # Put object
    put_res = storage.put_object(path, test_data, content_type="application/pdf")
    assert put_res["path"] == path
    assert put_res["size"] == len(test_data)
    assert put_res["content_type"] == "application/pdf"

    # Exists check
    assert storage.object_exists(path) is True
    assert storage.object_exists("resumes/user123/non_existent.pdf") is False

    # Get object
    retrieved_data, retrieved_ct = storage.get_object(path)
    assert retrieved_data == test_data
    assert retrieved_ct == "application/pdf"

    # Delete object
    assert storage.delete_object(path) is True
    assert storage.object_exists(path) is False
    assert storage.delete_object(path) is False


def test_local_storage_path_traversal_prevention(tmp_path):
    storage = LocalStorage(upload_dir=str(tmp_path))

    # Test directory traversal attacks
    traversal_paths = [
        "../../etc/passwd",
        "..\\..\\windows\\system32\\cmd.exe",
        "resumes/../../../secret.txt",
        "/absolute/path/outside",
    ]

    for malicious_path in traversal_paths:
        with pytest.raises((ValueError, FileNotFoundError)):
            storage.get_object(malicious_path)

        with pytest.raises(ValueError):
            storage.put_object(malicious_path, b"data")


def test_local_storage_missing_file_raises_reupload_required(tmp_path):
    storage = LocalStorage(upload_dir=str(tmp_path))
    with pytest.raises(FileNotFoundError) as exc_info:
        storage.get_object("resumes/missing.pdf")
    assert "re-upload required" in str(exc_info.value).lower()


def test_legacy_emergent_url_detected():
    storage = LocalStorage()
    legacy_url = "https://integrations.emergentagent.com/objstore/api/v1/storage/objects/applypilot/resumes/old.pdf"

    assert storage.object_exists(legacy_url) is False
    with pytest.raises(FileNotFoundError) as exc_info:
        storage.get_object(legacy_url)
    assert "re-upload required" in str(exc_info.value).lower()


def test_s3_storage_mocked():
    s3 = S3Storage(bucket="test-bucket", region="us-east-1")

    mock_client = MagicMock()
    mock_client.get_object.return_value = {
        "Body": MagicMock(read=lambda: b"s3 data"),
        "ContentType": "application/pdf",
    }
    s3._client = mock_client

    # Put
    res = s3.put_object("resumes/v1.pdf", b"s3 data", "application/pdf")
    assert res["path"] == "resumes/v1.pdf"
    mock_client.put_object.assert_called_once_with(
        Bucket="test-bucket", Key="resumes/v1.pdf", Body=b"s3 data", ContentType="application/pdf"
    )

    # Get
    data, ct = s3.get_object("resumes/v1.pdf")
    assert data == b"s3 data"
    assert ct == "application/pdf"

    # Head exists
    assert s3.object_exists("resumes/v1.pdf") is True

    # 404 NoSuchKey
    from botocore.exceptions import ClientError
    err = ClientError({"Error": {"Code": "NoSuchKey", "Message": "The specified key does not exist."}}, "GetObject")
    mock_client.get_object.side_effect = err
    with pytest.raises(FileNotFoundError) as exc_info:
        s3.get_object("missing.pdf")
    assert "re-upload required" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_reupload_warning_in_role_profiles(monkeypatch, tmp_path):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("OWNER_EMAIL", "owner@applypilot.dev")
    monkeypatch.setenv("SESSION_SECRET", "test_secret_key_session_1234567890123")
    monkeypatch.setenv("OWNER_PASSWORD_HASH", "$2b$12$e8q4K2aI58m4eI9BqV3Q7.wV1u3mR6e5zB3kY2lO0bK7iO6fN6O9u")
    reset_storage_backend()

    from auth import create_session_token

    token = create_session_token("owner")
    cookies = {"applypilot_session": token}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test", cookies=cookies) as client:
        # Create a role profile
        role_resp = await client.post("/api/roles", json={"title": "Platform Engineer", "skills": ["Go", "Kubernetes"]})
        assert role_resp.status_code == 200
        role_id = role_resp.json()["id"]

        # Insert a resume version with a non-existent legacy storage path in DB
        v_id = uuid.uuid4().hex
        await db.resume_versions.insert_one({
            "id": v_id,
            "user_id": "owner",
            "role_profile_id": role_id,
            "version_no": 1,
            "name": "legacy_resume.pdf",
            "size": 12345,
            "storage_path": "https://integrations.emergentagent.com/objstore/legacy.pdf",
            "content_type": "application/pdf",
            "active": True,
            "is_deleted": False,
            "created_at": utc_now_iso(),
        })

        # Fetch role profile - should surface reupload_required and reupload_warning
        get_role_resp = await client.get(f"/api/roles/{role_id}")
        assert get_role_resp.status_code == 200
        role_data = get_role_resp.json()
        assert role_data.get("reupload_required") is True
        assert "re-upload required" in role_data.get("reupload_warning", "").lower()
        assert role_data["active_resume"].get("reupload_required") is True

        # Fetch version list - should surface reupload_required
        versions_resp = await client.get(f"/api/roles/{role_id}/resumes")
        assert versions_resp.status_code == 200
        versions_list = versions_resp.json()
        assert len(versions_list) == 1
        assert versions_list[0].get("reupload_required") is True

        # Preview and Download should return 404 with "File not found; re-upload required"
        preview_resp = await client.get(f"/api/resumes/{v_id}/preview")
        assert preview_resp.status_code == 404
        assert "re-upload required" in preview_resp.json()["detail"].lower()

        download_resp = await client.get(f"/api/resumes/{v_id}/download")
        assert download_resp.status_code == 404
        assert "re-upload required" in download_resp.json()["detail"].lower()
