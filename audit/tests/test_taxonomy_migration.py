"""TAXONOMY-001 — migration 053 must map the combined nodes onto types that
actually exist, or a migrated row would stall exactly like a dead-on-arrival
node (the reachability invariant can't see DB rows, so this locks the bridge).
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

REPO = Path(__file__).resolve().parents[2]
_BACKEND = str(REPO / "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app.execution.commands import NODE_CHANNEL  # noqa: E402
from app.nodes import discover, manifests  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "migration_053", REPO / "backend/alembic/versions/053_split_mode_toggle_nodes.py"
)
_mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mig)

discover()
_REGISTERED = {m.type for m in manifests()}


def test_every_migrated_type_is_registered_and_routed():
    targets = (
        set(_mig.LINKEDIN_MODE_TO_TYPE.values())
        | {_mig.LINKEDIN_FALLBACK_TYPE}
        | set(_mig.ENRICH_SOURCE_TO_TYPE.values())
        | {_mig.ENRICH_FALLBACK_TYPE}
    )
    for node_type in targets:
        assert node_type in _REGISTERED, f"migration 053 maps onto unregistered {node_type}"
        assert node_type in NODE_CHANNEL, f"{node_type} has no NODE_CHANNEL route — migrated leads would stall"


def test_migration_covers_every_historical_mode():
    # The old config Literals: mode had 4 values, enrich_source had 3. A value
    # the migration doesn't map falls to the fallback — but the known ones must
    # all be mapped explicitly (no silent DM-ification of an invite).
    assert set(_mig.LINKEDIN_MODE_TO_TYPE) == {"invite", "dm", "inmail", "profile_view"}
    assert set(_mig.ENRICH_SOURCE_TO_TYPE) == {"apollo", "hunter", "proxycurl"}
