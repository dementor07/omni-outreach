from datetime import datetime
from unittest.mock import MagicMock, patch

import manual_message_service as mms


def _lead(**overrides):
    row = {
        "lead_id": "lead-1",
        "campaign_id": "CAMPAIGN_3",
        "linkedin_url": "https://www.linkedin.com/in/test-person",
        "chat_id": "chat-1",
        "account_id": "acct-1",
        "provider_id": "prov-1",
        "manual_message_sent_at": None,
        "automation_stopped_at": None,
    }
    row.update(overrides)
    return row


def test_send_single_manual_message_blocks_already_sent_lead():
    lead = _lead(manual_message_sent_at=datetime.utcnow())

    with patch.object(mms, "fetch_one", return_value=lead), \
         patch.object(mms, "send_message") as send_message, \
         patch.object(mms, "update_lead") as update_lead, \
         patch.object(mms, "cancel_future_tasks") as cancel_future_tasks, \
         patch.object(mms, "append_timeline_event") as append_timeline_event:
        result = mms.send_single_manual_message("lead-1", "hello")

    assert result == {
        "ok": False,
        "lead_id": "lead-1",
        "error": "manual_message_already_sent",
    }
    send_message.assert_not_called()
    update_lead.assert_not_called()
    cancel_future_tasks.assert_not_called()
    append_timeline_event.assert_not_called()


def test_send_single_manual_message_blocks_stopped_automation_lead():
    lead = _lead(automation_stopped_at=datetime.utcnow())

    with patch.object(mms, "fetch_one", return_value=lead), \
         patch.object(mms, "send_message") as send_message, \
         patch.object(mms, "update_lead") as update_lead, \
         patch.object(mms, "cancel_future_tasks") as cancel_future_tasks, \
         patch.object(mms, "append_timeline_event") as append_timeline_event:
        result = mms.send_single_manual_message("lead-1", "hello")

    assert result == {
        "ok": False,
        "lead_id": "lead-1",
        "error": "automation_already_stopped",
    }
    send_message.assert_not_called()
    update_lead.assert_not_called()
    cancel_future_tasks.assert_not_called()
    append_timeline_event.assert_not_called()


def test_sync_manual_messages_from_db_logs_and_aborts_when_sheet_fetch_fails():
    cfg_values = {
        "MANUAL_MESSAGES_SHEET_ID": "sheet-1",
        "MANUAL_MESSAGES_TAB_NAME": "manual_messages",
    }

    def fake_cfg(key, default=None):
        return cfg_values.get(key, default)

    with patch.object(mms.config, "cfg", side_effect=fake_cfg), \
         patch.object(mms.config, "get_campaign_id", return_value="CAMPAIGN_3"), \
         patch.object(mms, "fetch_leads", side_effect=RuntimeError("sheet down")), \
         patch.object(mms, "fetch_all") as fetch_all, \
         patch.object(mms, "upsert_row_by_key") as upsert_row_by_key, \
         patch("builtins.print") as print_mock:
        mms._sync_manual_messages_from_db()

    fetch_all.assert_not_called()
    upsert_row_by_key.assert_not_called()
    assert any("Failed to read manual messages sheet" in str(call.args[0]) for call in print_mock.call_args_list)
