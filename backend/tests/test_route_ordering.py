import os
import sys
import pytest
from httpx import AsyncClient, ASGITransport

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server import app
from deps import get_current_user
from db import db, utc_now_iso


@pytest.mark.asyncio
async def test_static_routes_not_captured_by_parameterized_routes():
    test_uid = "test_user_route_ordering"
    app.dependency_overrides[get_current_user] = lambda: {"user_id": test_uid, "email": "route@test.com"}

    try:
        # Seed a dummy dry-run app to verify DELETE /api/applications/dry-run deletes it and returns 200
        await db.job_applications.insert_one({
            "id": "dry_app_http_test",
            "user_id": test_uid,
            "dry_run": True,
            "status": "sent",
            "created_at": utc_now_iso(),
        })

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. DELETE /api/applications/dry-run
            # If captured by /api/applications/{app_id}, it would call delete_application("dry-run") -> 404
            r1 = await client.delete("/api/applications/dry-run")
            assert r1.status_code == 200, f"Expected 200 for DELETE /api/applications/dry-run, got {r1.status_code}: {r1.text}"
            data1 = r1.json()
            assert data1["ok"] is True
            assert data1["deleted_applications"] == 1

            # 2. GET /api/contacts/bulk-jobs/active
            # If captured by /api/contacts/bulk-jobs/{job_id}, it would call get_bulk_job("active") -> 404
            r2 = await client.get("/api/contacts/bulk-jobs/active")
            assert r2.status_code == 200, f"Expected 200 for GET /api/contacts/bulk-jobs/active, got {r2.status_code}: {r2.text}"
            data2 = r2.json()
            assert "job" in data2

            # 3. POST /api/applications/bulk-approve
            # If captured or mismatched, it would fail
            r3 = await client.post("/api/applications/bulk-approve", json={"application_ids": []})
            assert r3.status_code == 200, f"Expected 200 for POST /api/applications/bulk-approve, got {r3.status_code}: {r3.text}"
            data3 = r3.json()
            assert data3["ok"] is True
            assert data3["count"] == 0

            # 4. POST /api/applications/bulk-delete
            # If captured or mismatched, it would fail
            r4 = await client.post("/api/applications/bulk-delete", json={"application_ids": []})
            assert r4.status_code == 200, f"Expected 200 for POST /api/applications/bulk-delete, got {r4.status_code}: {r4.text}"
            data4 = r4.json()
            assert data4["ok"] is True
            assert data4["count"] == 0

    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await db.job_applications.delete_many({"user_id": test_uid})
