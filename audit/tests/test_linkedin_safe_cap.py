"""ACCOUNT-CAP-DEFAULT-001 — a LinkedIn seat must never sync/create UNCAPPED.

LinkedIn bans accounts that fire too many invites/DMs in a day. The column
semantic is `0 = unlimited`, which is right for email/SMS but a loaded gun for
LinkedIn: a synced-from-Unipile seat arrives with daily_cap=0, and an operator
adding one by hand may leave it 0. `_linkedin_safe_cap` forces a conservative
non-zero default (20/day) for linkedin ONLY when no explicit cap was set, while
leaving every other channel's 0=unlimited intact and respecting any cap the
operator did choose. This locks that floor so a refactor can't quietly drop it
and ship an uncapped LinkedIn account.
"""

from __future__ import annotations

import os

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

import pytest

from app.routers.integrations import _linkedin_safe_cap


def test_linkedin_uncapped_gets_safe_default():
    # the dangerous case: a linkedin seat with no cap → forced to 20/day.
    assert _linkedin_safe_cap("linkedin", 0) == 20


def test_linkedin_explicit_cap_is_respected():
    # an operator who set a real cap keeps it — we only fill in the 0 case.
    assert _linkedin_safe_cap("linkedin", 50) == 50
    assert _linkedin_safe_cap("linkedin", 5) == 5


@pytest.mark.parametrize("kind", ["email", "sms", "voice", "whatsapp", "instagram", "telegram"])
def test_non_linkedin_keeps_unlimited(kind):
    # 0 = unlimited stays unlimited for every non-linkedin channel.
    assert _linkedin_safe_cap(kind, 0) == 0


@pytest.mark.parametrize("kind", ["email", "sms", "whatsapp"])
def test_non_linkedin_explicit_cap_unchanged(kind):
    assert _linkedin_safe_cap(kind, 100) == 100
