import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from gmail_service import SCOPES, start_flow


def test_gmail_scopes_are_least_privilege():
    # Must NOT have dangerous modify or label manipulation scopes
    assert "https://www.googleapis.com/auth/gmail.modify" not in SCOPES
    assert "https://www.googleapis.com/auth/gmail.labels" not in SCOPES

    # Must contain necessary send and read scopes
    assert "https://www.googleapis.com/auth/gmail.send" in SCOPES
    assert "https://www.googleapis.com/auth/gmail.readonly" in SCOPES
    assert "https://www.googleapis.com/auth/userinfo.email" in SCOPES
    assert "openid" in SCOPES

    # Ensure no unexpected scopes
    assert set(SCOPES) == {
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/userinfo.email",
        "openid",
    }


@pytest.mark.asyncio
async def test_oauth_flow_uses_reduced_scopes():
    with patch("gmail_service.get_google_config", return_value=("fake_client_id", "fake_secret")), \
         patch("google_auth_oauthlib.flow.Flow.from_client_config") as mock_flow_cls:

        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?...", "state123")
        mock_flow_cls.return_value = mock_flow

        url = await start_flow("owner", "https://applypilot.local/api/gmail/callback", "https://applypilot.local")
        assert url.startswith("https://accounts.google.com")

        # Verify from_client_config was called with least-privilege SCOPES
        mock_flow_cls.assert_called_once()
        _, kwargs = mock_flow_cls.call_args
        assert kwargs["scopes"] == SCOPES
        assert "https://www.googleapis.com/auth/gmail.modify" not in kwargs["scopes"]
