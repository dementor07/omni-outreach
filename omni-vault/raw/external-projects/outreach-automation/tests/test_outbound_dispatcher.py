import time
from unittest.mock import MagicMock, patch

import outbound_dispatcher as svc


def setup_function():
    svc._account_last_sent.clear()


def teardown_function():
    svc._account_last_sent.clear()


# ── Group A: pure helper tests (no mocks, no DB) ──────────────────────────────

def test_account_in_cooldown_false_for_unknown_account():
    assert svc._account_in_cooldown("acct-A") is False


def test_no_cross_account_blocking():
    svc._record_account_send("acct-A", delay=120)
    assert svc._account_in_cooldown("acct-B") is False
    assert svc._account_in_cooldown("acct-A") is True  # sanity: A is blocked


def test_same_account_in_cooldown_immediately_after_send():
    svc._record_account_send("acct-A", delay=120)
    assert svc._account_in_cooldown("acct-A") is True


def test_same_account_not_in_cooldown_after_delay_expires():
    svc._account_last_sent["acct-A"] = (time.monotonic() - 200, 120)
    assert svc._account_in_cooldown("acct-A") is False


# ── Group B: processor mock tests ────────────────────────────────────────────

def _invite_task():
    return {
        "queue_id": "q-1",
        "lead_id": "lead-1",
        "task_type": "invite",
        "campaign_id": "CAMPAIGN_4",
        "account_id": "acct-A",
        "provider_id": "prov-1",
        "chat_id": None,
        "message": None,
        "failure_reason": None,
    }


def _first_message_task():
    return {
        "queue_id": "q-2",
        "lead_id": "lead-2",
        "task_type": "first_message",
        "campaign_id": "CAMPAIGN_4",
        "account_id": "acct-A",
        "provider_id": "prov-1",
        "chat_id": None,
        "message": None,
        "failure_reason": None,
    }


def _inbound_task():
    return {
        "queue_id": "q-3",
        "lead_id": "lead-3",
        "task_type": "inbound_response",
        "campaign_id": "CAMPAIGN_4",
        "account_id": "acct-A",
        "provider_id": "prov-1",
        "chat_id": "chat-1",
        "message": None,
        "failure_reason": None,
    }


def test_daily_cap_requeues_until_tomorrow_in_invite():
    with patch.object(svc, "ensure_send_window", return_value=True), \
         patch.object(svc, "_within_daily_caps", return_value=False), \
         patch.object(svc, "_seconds_until_tomorrow", return_value=7200), \
         patch.object(svc, "requeue_task") as mock_requeue, \
         patch.object(svc, "unlock_task") as mock_unlock:
        result = svc._process_invite(_invite_task())

    assert result is False
    mock_requeue.assert_called_once()
    args = mock_requeue.call_args
    assert args[0][0] == "q-1"
    assert args[1]["delay_seconds"] > 3600  # must be hours away, not 900s
    mock_unlock.assert_not_called()


def test_daily_cap_requeues_until_tomorrow_in_outbound_message():
    with patch.object(svc, "ensure_send_window", return_value=True), \
         patch.object(svc, "_within_daily_caps", return_value=False), \
         patch.object(svc, "_seconds_until_tomorrow", return_value=7200), \
         patch.object(svc, "requeue_task") as mock_requeue, \
         patch.object(svc, "unlock_task") as mock_unlock, \
         patch.object(svc, "claim_first_message_slot") as mock_claim:
        result = svc._process_outbound_message(_first_message_task())

    assert result is False
    mock_requeue.assert_called_once()
    args = mock_requeue.call_args
    assert args[0][0] == "q-2"
    assert args[1]["delay_seconds"] > 3600
    mock_unlock.assert_not_called()
    mock_claim.assert_not_called()  # cap check is before slot claim


def test_daily_cap_requeues_until_tomorrow_in_inbound_response():
    with patch.object(svc, "ensure_send_window", return_value=True), \
         patch.object(svc, "_within_daily_caps", return_value=False), \
         patch.object(svc, "_seconds_until_tomorrow", return_value=7200), \
         patch.object(svc, "requeue_task") as mock_requeue, \
         patch.object(svc, "unlock_task") as mock_unlock:
        result = svc._process_inbound_response(_inbound_task())

    assert result is False
    mock_requeue.assert_called_once()
    args = mock_requeue.call_args
    assert args[0][0] == "q-3"
    assert args[1]["delay_seconds"] > 3600
    mock_unlock.assert_not_called()
