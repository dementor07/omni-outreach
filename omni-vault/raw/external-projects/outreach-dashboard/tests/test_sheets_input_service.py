import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


DASHBOARD_ROOT = str(Path(__file__).parent.parent)
if DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, DASHBOARD_ROOT)


sys.modules.setdefault("db", MagicMock())
sys.modules.setdefault("gspread", MagicMock())
sys.modules.setdefault("dotenv", MagicMock())
sys.modules.setdefault("google", MagicMock())
sys.modules.setdefault("google.oauth2", MagicMock())
sys.modules.setdefault("google.oauth2.service_account", MagicMock(Credentials=MagicMock()))
sys.modules.setdefault("lead_screener", MagicMock(screen_lead=MagicMock(return_value=("ACCEPT", ""))))
sys.modules.pop("sheets_input_service", None)

import sheets_input_service as sis


def test_get_working_account_id_uses_campaign_assignment():
    with patch.object(sis, "fetch_one", return_value={"account_id": "acct-1"}) as fetch_one:
        result = sis._get_working_account_id("CAMPAIGN_3")

    assert result == "acct-1"
    query, params = fetch_one.call_args.args
    assert "campaign_linkedin_accounts" in query
    assert params == ("CAMPAIGN_3",)


def test_append_leads_fails_closed_when_prompt_lookup_errors():
    worksheet = SimpleNamespace()
    with patch.object(sis, "_campaign_sheet_config", return_value={"leads_sheet_id": "sheet-1", "leads_tab": "leads"}), \
         patch.object(sis, "_open_worksheet", return_value=worksheet), \
         patch.object(sis, "_worksheet_headers", return_value=["linkedin_url"]), \
         patch.object(sis, "_existing_values_by_header", return_value=set()), \
         patch.object(sis, "_get_screening_prompt", side_effect=RuntimeError("drive down")):
        with pytest.raises(RuntimeError, match="drive down"):
            sis.append_leads("CAMPAIGN_3", [{"linkedin_url": "https://www.linkedin.com/in/test-person"}])


def test_append_manual_messages_normalizes_duplicate_urls_in_sheet():
    worksheet = SimpleNamespace(
        get_all_records=lambda: [
            {
                "linkedin_url": "https://www.linkedin.com/in/test-person/?trk=foo",
                "manual_message": "Hello there",
            }
        ],
        append_rows=MagicMock(),
    )
    with patch.object(
        sis,
        "_campaign_sheet_config",
        return_value={"manual_messages_sheet_id": "sheet-1", "manual_messages_tab": "manual_messages"},
    ), patch.object(sis, "_open_worksheet", return_value=worksheet), \
         patch.object(sis, "_worksheet_headers", return_value=["linkedin_url", "manual_message"]), \
         patch.object(sis, "_lead_known_for_manual", return_value=True):
        result = sis.append_manual_messages(
            "CAMPAIGN_3",
            [{"linkedin_url": "https://www.linkedin.com/in/test-person", "manual_message": "Hello there"}],
        )

    assert result["appended"] == 0
    assert result["skipped"][0]["reason"] == "duplicate_in_sheet"
