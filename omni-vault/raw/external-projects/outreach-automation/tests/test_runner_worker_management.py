import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


AUTOMATION_ROOT = str(Path(__file__).parent.parent)
if AUTOMATION_ROOT not in sys.path:
    sys.path.insert(0, AUTOMATION_ROOT)


sys.modules.setdefault("rollbar", MagicMock())
sys.modules.setdefault("logger", MagicMock())
sys.modules.setdefault("rollbar_init", MagicMock())
sys.modules.setdefault("lead_ingestion", MagicMock())
sys.modules.setdefault("invitation_service", MagicMock())
sys.modules.setdefault("acceptance_checker", MagicMock())
sys.modules.setdefault("first_message_service", MagicMock())
sys.modules.setdefault("followup_service", MagicMock())
sys.modules.setdefault("conversation_guard", MagicMock())
sys.modules.setdefault("manual_message_service", MagicMock())
sys.modules.setdefault("approval_checker", MagicMock())

import runner


def test_reconcile_workers_starts_new_campaigns():
    worker = {"thread": MagicMock(), "stop_event": MagicMock()}
    active = {}

    with patch.object(runner, "_start_campaign_worker", return_value=worker) as start_worker:
        updated = runner._reconcile_workers(active, ["CAMPAIGN_3"])

    start_worker.assert_called_once_with("CAMPAIGN_3")
    assert updated["CAMPAIGN_3"] is worker


def test_reconcile_workers_stops_removed_campaigns():
    stop_event = MagicMock()
    thread = MagicMock()
    active = {"CAMPAIGN_1": {"thread": thread, "stop_event": stop_event}}

    updated = runner._reconcile_workers(active, [])

    stop_event.set.assert_called_once()
    thread.join.assert_called_once_with(timeout=5)
    assert updated == {}
