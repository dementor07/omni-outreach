from datetime import datetime, timedelta
from unittest.mock import patch

import followup_service as fs


def _lead(**overrides):
    row = {
        "lead_id": "lead-1",
        "campaign_id": "CAMPAIGN_3",
        "linkedin_url": "https://www.linkedin.com/in/test-person",
        "first_name": "Test",
        "account_id": "acct-1",
        "account_name": "Account 1",
        "provider_id": "prov-1",
        "chat_id": "chat-1",
        "first_message_sent_at": datetime(2026, 3, 20, 10, 0, 0),
        "followup_1_sent_at": None,
        "followup_2_sent_at": None,
        "followup_3_sent_at": None,
        "automation_stopped_at": None,
        "last_inbound_message_at": None,
        "conversation_active": False,
        "manual_message_sent_at": None,
    }
    row.update(overrides)
    return row


def test_followup_uses_config_base_days_plus_jitter_when_no_step_rules():
    lead = _lead()
    cfg_values = {
        "FIRST_FOLLOWUP_DAYS": 3,
        "SECOND_FOLLOWUP_DAYS": 6,
        "THIRD_FOLLOWUP_DAYS": 9,
        "FOLLOWUP_1_JITTER_DAYS": 2,
        "LEAD_FULL_STATS_SHEET_ID": "sheet-1",
        "LEAD_FULL_STATS_TAB_NAME": "lead_full_stats",
    }

    def fake_cfg(key, default=None):
        return cfg_values.get(key, default)

    with patch.object(fs.config, "get_campaign_id", return_value="CAMPAIGN_3"), \
         patch.object(fs.config, "cfg", side_effect=fake_cfg), \
         patch.object(fs, "fetch_all", side_effect=[[lead], []]), \
         patch.object(fs, "fetch_one", return_value=None), \
         patch.object(fs.random, "randint", return_value=1), \
         patch.object(fs, "update_lead"), \
         patch.object(fs, "append_timeline_event"), \
         patch.object(fs, "upsert_lead_full_stats"), \
         patch.object(fs, "enqueue_outbound_task") as enqueue:
        fs.send_followups()

    scheduled_at = enqueue.call_args.kwargs["scheduled_at"]
    assert scheduled_at == lead["first_message_sent_at"] + timedelta(days=4)


def test_followup_prefers_campaign_step_rule_delay_when_present():
    lead = _lead()
    cfg_values = {
        "FIRST_FOLLOWUP_DAYS": 3,
        "SECOND_FOLLOWUP_DAYS": 6,
        "THIRD_FOLLOWUP_DAYS": 9,
        "FOLLOWUP_1_JITTER_DAYS": 0,
        "LEAD_FULL_STATS_SHEET_ID": "sheet-1",
        "LEAD_FULL_STATS_TAB_NAME": "lead_full_stats",
    }

    def fake_cfg(key, default=None):
        return cfg_values.get(key, default)

    rules = [{"code": "linkedin_followup_1", "delay_days_from_previous": 6}]

    with patch.object(fs.config, "get_campaign_id", return_value="CAMPAIGN_3"), \
         patch.object(fs.config, "cfg", side_effect=fake_cfg), \
         patch.object(fs, "fetch_all", side_effect=[[lead], rules]), \
         patch.object(fs, "fetch_one", return_value=None), \
         patch.object(fs.random, "randint", return_value=0), \
         patch.object(fs, "update_lead"), \
         patch.object(fs, "append_timeline_event"), \
         patch.object(fs, "upsert_lead_full_stats"), \
         patch.object(fs, "enqueue_outbound_task") as enqueue:
        fs.send_followups()

    scheduled_at = enqueue.call_args.kwargs["scheduled_at"]
    assert scheduled_at == lead["first_message_sent_at"] + timedelta(days=6)
