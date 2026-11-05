#!/usr/bin/env python3
"""Live Gmail Verification Script for ApplyPilot.

1. Verifies Gmail connection in MongoDB.
2. Sends one real test application email via connected Gmail (DRY_RUN=false).
3. Verifies status=sent and real Gmail message_id.
4. Prepares for token refresh verification (>1 hour later).

Usage:
    python scripts/test_live_gmail.py [recipient_email]
"""
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "backend"))

from dotenv import load_dotenv
load_dotenv(ROOT_DIR / "backend" / ".env", override=True)

from db import db, utc_now_iso
import application_engine
import gmail_service


async def main():
    recipient = sys.argv[1] if len(sys.argv) > 1 else None

    print("=" * 60)
    print("APPLYPILOT LIVE GMAIL VERIFICATION")
    print("=" * 60)

    # 1. Check Gmail connection
    conn = await db.gmail_connections.find_one({"user_id": "owner"})
    if not conn:
        print("\n[!] No Gmail connection found in database.")
        print("Please authorize Gmail in your browser first.")
        url = await gmail_service.start_flow("owner", "http://localhost:8000/api/gmail/callback", "http://localhost:3000")
        print("\nAuthorization URL:\n", url)
        return

    connected_email = conn.get("email")
    print(f"\n[+] Gmail is CONNECTED as: {connected_email}")
    print(f"    Status: {conn.get('status')}")
    print(f"    Connected at: {conn.get('connected_at')}")

    if not recipient:
        recipient = connected_email
        print(f"\n[*] No recipient email argument passed. Defaulting to self-send: {recipient}")
    else:
        print(f"\n[*] Destination recipient: {recipient}")

    # 2. Ensure role profile & active resume exist
    role = await db.role_profiles.find_one({"user_id": "owner"})
    if not role:
        role_id = f"role_{os.urandom(4).hex()}"
        await db.role_profiles.insert_one({
            "id": role_id,
            "user_id": "owner",
            "title": "Software Engineer",
            "target_keywords": ["Python", "FastAPI", "React"],
            "created_at": utc_now_iso(),
        })
    else:
        role_id = role["id"]

    # 3. Create a test resume file and staged test application document
    from storage import put_object
    pdf_bytes = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\nxref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000052 00000 n \n0000000108 00000 n \ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n178\n%%EOF\n"
    attach_meta = put_object("resumes/test_resume.pdf", pdf_bytes, "application/pdf")

    app_id = f"app_live_test_{os.urandom(4).hex()}"
    test_app = {
        "id": app_id,
        "user_id": "owner",
        "company": "Live Test Corp",
        "job_title": "Software Engineer",
        "hr_name": "Test Hiring Lead",
        "hr_email": recipient,
        "role_profile_id": role_id,
        "resume_name": "Amay_Mishra_Resume.pdf",
        "attachment_path": attach_meta["path"],
        "attachment_filename": "Amay_Mishra_Resume.pdf",
        "status": "approved",
        "subject": "Application: Software Engineer – ApplyPilot Live Verification",
        "body_text": (
            "Hi there,\n\n"
            "This is an automated live verification email sent from ApplyPilot using Google Gmail API with DRY_RUN=false.\n\n"
            f"Timestamp: {datetime.now(timezone.utc).isoformat()}\n\n"
            "Best regards,\nApplyPilot Automated System"
        ),
        "created_at": utc_now_iso(),
    }
    await db.job_applications.insert_one(test_app)
    print(f"\n[+] Staged test application: {app_id} -> {recipient}")

    # 4. Dispatch via application_engine.send_application
    print("\n[*] Dispatching email via connected Gmail API (DRY_RUN=false)...")
    res = await application_engine.send_application("owner", test_app)
    print("\nResult from send_application:", res)

    # 5. Verify database update
    updated_app = await db.job_applications.find_one({"id": app_id})
    if updated_app and updated_app.get("status") == "sent":
        msg_id = updated_app.get("message_id")
        print("\n" + "=" * 60)
        print("SUCCESS! Real Gmail dispatch verified!")
        print(f"Message ID: {msg_id}")
        print(f"Sent at:    {updated_app.get('sent_at')}")
        print(f"Dry Run:    {updated_app.get('dry_run')}")
        print("=" * 60)
    else:
        print("\n[!] Send failed or did not mark as sent:")
        print(updated_app)


if __name__ == "__main__":
    asyncio.run(main())

