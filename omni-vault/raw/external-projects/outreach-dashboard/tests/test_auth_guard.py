import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


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

import app as app_module


def test_campaigns_route_requires_auth():
    client = TestClient(app_module.app, raise_server_exceptions=True)
    response = client.get("/api/campaigns")
    assert response.status_code == 401


def test_repair_log_route_requires_auth():
    client = TestClient(app_module.app, raise_server_exceptions=True)
    response = client.get("/api/repair/log")
    assert response.status_code == 401


def test_auth_me_remains_public():
    client = TestClient(app_module.app, raise_server_exceptions=True)
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["authenticated"] is False


def test_authenticated_campaigns_route_succeeds():
    client = TestClient(app_module.app, raise_server_exceptions=True)
    with patch.object(app_module, "require_admin", return_value={"role": "admin", "actor": "test"}), \
         patch.object(app_module.queries, "get_campaign_rows", return_value=[]):
        response = client.get("/api/campaigns")
    assert response.status_code == 200
