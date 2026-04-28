from unittest.mock import MagicMock, patch

import invitation_service as svc


def _lead():
    return {
        "lead_id": "lead-1",
        "linkedin_url": "https://www.linkedin.com/in/test-person",
        "first_name": "Test",
        "chat_id": None,
    }


def _cfg_value(key, default=None):
    values = {
        "MAX_LEADS_PER_ACCOUNT": 5,
        "GLOBAL_MAX_LEADS_PER_ACCOUNT": 5,
        "CAMPAIGN_MAX_LEADS_PER_ACCOUNT": 10,
        "INVITE_DELAY_MIN": 1,
        "INVITE_DELAY_MAX": 1,
        "LEAD_FULL_STATS_SHEET_ID": "sheet-1",
        "LEAD_FULL_STATS_TAB_NAME": "lead_full_stats",
    }
    return values.get(key, default)


def _fetch_all_single_lead(query, params=None):
    if "FROM lead_full_stats" in query:
        return [_lead()]
    return []


# ── campaign_max daily cap tests ───────────────────────────────────────────────

def _make_fetch_all(usage_today: int):
    """
    Returns a fetch_all side_effect that:
    - gives one eligible lead from lead_full_stats
    - returns the given daily usage count for account 'acct-1' from dispatcher_queue
    """
    def _fetch(query, params=None):
        if "FROM lead_full_stats" in query:
            return [_lead()]
        if "FROM dispatcher_queue" in query and "Asia/Kolkata" in query:
            # daily usage query
            if usage_today > 0:
                return [{"account_id": "acct-1", "cnt": usage_today}]
            return []
        return []
    return _fetch


def _cfg_campaign_max_10(key, default=None):
    """campaign_max=10, daily account cap=20 so campaign_max is the binding limit."""
    values = {
        "MAX_LEADS_PER_ACCOUNT": 20,
        "GLOBAL_MAX_LEADS_PER_ACCOUNT": 20,
        "CAMPAIGN_MAX_LEADS_PER_ACCOUNT": 10,
        "INVITE_DELAY_MIN": 1,
        "INVITE_DELAY_MAX": 1,
        "LEAD_FULL_STATS_SHEET_ID": "sheet-1",
        "LEAD_FULL_STATS_TAB_NAME": "lead_full_stats",
    }
    return values.get(key, default)


def test_campaign_max_blocks_when_daily_count_at_cap():
    """If account already has campaign_max invites today, 11th lead is blocked."""
    with patch.object(svc, "fetch_all", side_effect=_make_fetch_all(usage_today=10)), \
         patch.object(svc.config, "get_campaign_id", return_value="CAMPAIGN_4"), \
         patch.object(svc.config, "get_accounts", return_value=["acct-1"]), \
         patch.object(svc.config, "get_account_name_map", return_value={"acct-1": "Account 1"}), \
         patch.object(svc.config, "cfg", side_effect=_cfg_campaign_max_10), \
         patch.object(svc, "get_profile") as get_profile, \
         patch.object(svc, "enqueue_outbound_task") as enqueue, \
         patch.object(svc, "update_lead"), \
         patch.object(svc, "append_timeline_event"):
        svc.send_invitations()

    get_profile.assert_not_called()
    enqueue.assert_not_called()


def test_campaign_max_allows_when_daily_count_is_zero():
    """If account had 10 invites yesterday and 0 today, it is NOT blocked today."""
    with patch.object(svc, "fetch_all", side_effect=_make_fetch_all(usage_today=0)), \
         patch.object(svc.config, "get_campaign_id", return_value="CAMPAIGN_4"), \
         patch.object(svc.config, "get_accounts", return_value=["acct-1"]), \
         patch.object(svc.config, "get_account_name_map", return_value={"acct-1": "Account 1"}), \
         patch.object(svc.config, "cfg", side_effect=_cfg_campaign_max_10), \
         patch.object(svc, "get_profile", return_value={"provider_id": "prov-1", "network_distance": "SECOND_DEGREE"}), \
         patch.object(svc, "claim_lead_account", return_value=True), \
         patch.object(svc, "queue_task_exists", return_value=False), \
         patch.object(svc, "enqueue_outbound_task") as enqueue, \
         patch.object(svc, "upsert_lead_full_stats"), \
         patch.object(svc, "update_lead"), \
         patch.object(svc, "append_timeline_event"):
        svc.send_invitations()

    enqueue.assert_called_once()


def test_daily_usage_query_uses_ist_boundary():
    """Verify the daily usage query contains the IST timezone expression."""
    import inspect
    source = inspect.getsource(svc.send_invitations)
    assert "Asia/Kolkata" in source, "Daily cap query must use IST (Asia/Kolkata) day boundary"


def test_releases_claim_when_enqueue_fails():
    with patch.object(svc, "fetch_all", side_effect=_fetch_all_single_lead), \
         patch.object(svc.config, "get_campaign_id", return_value="CAMPAIGN_3"), \
         patch.object(svc.config, "get_accounts", return_value=["acct-1"]), \
         patch.object(svc.config, "get_account_name_map", return_value={"acct-1": "Account 1"}), \
         patch.object(svc.config, "cfg", side_effect=_cfg_value), \
         patch.object(svc, "get_profile", return_value={"provider_id": "prov-1", "network_distance": "SECOND_DEGREE"}), \
         patch.object(svc, "claim_lead_account", return_value=True), \
         patch.object(svc, "queue_task_exists", return_value=False), \
         patch.object(svc, "enqueue_outbound_task", side_effect=RuntimeError("queue write failed")), \
         patch.object(svc, "upsert_lead_full_stats"), \
         patch.object(svc, "append_timeline_event"), \
         patch.object(svc, "update_lead") as update_lead:
        svc.send_invitations()

    assert any(
        call.kwargs.get("lead_id") == "lead-1"
        and call.kwargs.get("account_id") is None
        and call.kwargs.get("account_name") is None
        and call.kwargs.get("provider_id") is None
        and call.kwargs.get("assignment_status") is None
        for call in update_lead.call_args_list
    )


def test_sheet_sync_failure_does_not_try_second_account_after_enqueue():
    with patch.object(svc, "fetch_all", side_effect=_fetch_all_single_lead), \
         patch.object(svc.config, "get_campaign_id", return_value="CAMPAIGN_3"), \
         patch.object(svc.config, "get_accounts", return_value=["acct-1", "acct-2"]), \
         patch.object(svc.config, "get_account_name_map", return_value={"acct-1": "Account 1", "acct-2": "Account 2"}), \
         patch.object(svc.config, "cfg", side_effect=_cfg_value), \
         patch.object(svc, "get_profile", return_value={"provider_id": "prov-1", "network_distance": "SECOND_DEGREE"}) as get_profile, \
         patch.object(svc, "claim_lead_account", return_value=True), \
         patch.object(svc, "queue_task_exists", return_value=False), \
         patch.object(svc, "enqueue_outbound_task") as enqueue_outbound_task, \
         patch.object(svc, "upsert_lead_full_stats", side_effect=RuntimeError("sheet broken")), \
         patch.object(svc, "append_timeline_event"), \
         patch.object(svc, "update_lead"):
        svc.send_invitations()

    assert enqueue_outbound_task.call_count == 1
    assert get_profile.call_count == 1
