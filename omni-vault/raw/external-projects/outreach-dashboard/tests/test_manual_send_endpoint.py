import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


DASHBOARD_ROOT = str(Path(__file__).parent.parent)
if DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, DASHBOARD_ROOT)


_DB_STUB = MagicMock()
sys.modules.setdefault("db", _DB_STUB)
sys.modules.setdefault("psycopg2", MagicMock())
sys.modules.setdefault("psycopg2.extras", MagicMock())
sys.modules.setdefault("dotenv", MagicMock())
sys.modules.setdefault("itsdangerous", MagicMock())
sys.modules.setdefault("approval_gate", MagicMock())
sys.modules.setdefault("approval_service", MagicMock())
sys.modules.setdefault("claude_terminal_service", MagicMock())
sys.modules.setdefault("drive_config_service", MagicMock())
sys.modules.setdefault("repair_agent", MagicMock())
sys.modules.setdefault("scenarios", MagicMock())
sys.modules.setdefault("sheets_input_service", MagicMock())
sys.modules.setdefault("terminal_service", MagicMock())
sys.modules.setdefault("audit_log", MagicMock())
sys.modules.setdefault("campaign_validate", MagicMock())
sys.modules.setdefault("command_policy", MagicMock())


class TestManualSendEndpoint:
    @pytest.fixture(autouse=True)
    def _setup_client(self):
        from fastapi.testclient import TestClient
        import app as app_module

        original_require_admin = app_module.require_admin
        app_module.require_admin = lambda request=None: {"role": "admin", "actor": "test"}
        app_module.app.dependency_overrides[original_require_admin] = lambda: {"role": "admin", "actor": "test"}
        self.client = TestClient(app_module.app, raise_server_exceptions=True)
        self.app_module = app_module
        yield
        app_module.require_admin = original_require_admin
        app_module.app.dependency_overrides.clear()

    def test_returns_409_when_manual_message_already_sent(self):
        with patch.object(self.app_module, "_load_manual_message_sender", return_value=lambda **_: {
            "ok": False,
            "lead_id": "lead-1",
            "error": "manual_message_already_sent",
        }):
            response = self.client.post("/api/leads/lead-1/send-message", json={"message": "hello"})

        assert response.status_code == 409
        assert response.json()["detail"] == "Manual message already sent for this lead"

    def test_returns_409_when_automation_already_stopped(self):
        with patch.object(self.app_module, "_load_manual_message_sender", return_value=lambda **_: {
            "ok": False,
            "lead_id": "lead-1",
            "error": "automation_already_stopped",
        }):
            response = self.client.post("/api/leads/lead-1/send-message", json={"message": "hello"})

        assert response.status_code == 409
        assert response.json()["detail"] == "Automation is already stopped for this lead"
