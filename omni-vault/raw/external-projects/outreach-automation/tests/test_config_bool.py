import os

import config


def test_cfg_bool_parses_false_from_env(monkeypatch):
    monkeypatch.setenv("INBOUND_RESPONSE_ENABLED", "false")
    monkeypatch.setattr(config._state, "db_cfg", {}, raising=False)
    assert config.cfg_bool("INBOUND_RESPONSE_ENABLED", True) is False


def test_cfg_bool_prefers_db_boolean(monkeypatch):
    monkeypatch.setenv("INBOUND_RESPONSE_ENABLED", "false")
    monkeypatch.setattr(config._state, "db_cfg", {"INBOUND_RESPONSE_ENABLED": True}, raising=False)
    assert config.cfg_bool("INBOUND_RESPONSE_ENABLED", False) is True
