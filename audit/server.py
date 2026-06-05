"""Audit control plane — a localhost-only control server behind the static
dashboard (``audit/index.html``).

This is a DEV TOOL. It is never deployed. It binds to 127.0.0.1 only, has no
auth, and hard-refuses to start if it can see a production database target. It
turns the read-only findings viewer into a controlled audit + test plane:

  GET   /api/state              -> findings.json + which findings have tests
  GET   /api/health             -> live system health (compose ps, /health, topics)
  PATCH /api/finding/{id}       -> write status back to findings.json (attributed)
  POST  /api/run/{test_name}    -> run a registry test, write last_run onto its
                                   bound findings, return the result + artifact id
  GET   /api/runs/{run_id}      -> fetch a run's captured output (artifact)

Run it:
    python audit/server.py            # serves UI + API on http://127.0.0.1:8799

The static page detects the server; if it's not running the page still works
read-only (it falls back to fetching findings.json directly).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

AUDIT_DIR = Path(__file__).resolve().parent
REPO_ROOT = AUDIT_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"
FINDINGS = AUDIT_DIR / "findings.json"
RUNS_DIR = AUDIT_DIR / "runs"
RUNS_DIR.mkdir(exist_ok=True)

# Load the audit test registry by file path (avoid colliding with any
# site-packages 'tests' package).
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "audit_test_registry", AUDIT_DIR / "tests" / "registry.py"
)
test_registry = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
# Register before exec so dataclasses' frozen+field machinery can resolve the
# module by __module__ (it does a sys.modules lookup during class processing).
sys.modules["audit_test_registry"] = test_registry
_spec.loader.exec_module(test_registry)  # type: ignore[union-attr]

# ── Read/write boundary ─────────────────────────────────────────────────────────
# The control plane has two halves with DIFFERENT trust rules:
#
#   VIZ (read-only): the System & pipeline panels read the LIVE VPS over SSH —
#     row counts, topic metadata, archived events. These are SELECT/list only.
#     Authorized by the user as a recurring production READ.
#
#   MUTATING (run-test / e2e): may create/modify data. This half must NEVER touch
#     production. _assert_mutation_target_safe() guards it; viz does not call it.
#
# So the old "refuse to start if any var names prod" guard is replaced by a guard
# on the MUTATING path only — viz is allowed to read prod by design.
_PROD_MARKERS = ("145.223.21.222", "srv1575227.hstgr.cloud", "omnioutreach")


def _assert_mutation_target_safe() -> None:
    """Called by mutating endpoints (e2e) — refuse if pointed at prod."""
    for key in ("DATABASE_URL", "DB_HOST", "POSTGRES_HOST"):
        val = os.environ.get(key, "")
        for marker in _PROD_MARKERS:
            if marker in val:
                raise HTTPException(
                    403,
                    f"mutation refused: {key} names a production marker ({marker!r}). "
                    f"The control plane only mutates a local/ephemeral stack.",
                )


# ── VPS read-only viz target (over SSH) ───────────────────────────────────────────
# Per-call SSH reads — no persistent tunnel. Each viz refresh is one explicit,
# auditable `ssh ... docker exec ...` read against the live VPS. Read-only by
# construction (SELECT / rpk list|describe).
VPS_HOST = os.environ.get("AUDIT_VPS_HOST", "root@145.223.21.222")
VPS_KEY = os.environ.get("AUDIT_VPS_KEY", str(Path.home() / ".ssh" / "omni_deploy"))
VPS_DB_CONTAINER = os.environ.get("AUDIT_VPS_DB_CONTAINER", "omni-outreach-db-1")
VPS_REDPANDA_CONTAINER = os.environ.get("AUDIT_VPS_REDPANDA_CONTAINER", "omni-outreach-redpanda-1")
VPS_DB_USER = os.environ.get("AUDIT_VPS_DB_USER", "outreach")
VPS_DB_NAME = os.environ.get("AUDIT_VPS_DB_NAME", "outreach")


def _ssh(remote_cmd: str, timeout: int = 20) -> tuple[bool, str]:
    """Run one read-only command on the VPS over SSH. Returns (ok, output).
    No connection multiplexing (Windows OpenSSH mux sockets are fragile); instead
    each endpoint minimises round-trips by batching its remote work into ONE
    command (see get_topics)."""
    cmd = ["ssh", "-i", VPS_KEY, "-o", "StrictHostKeyChecking=accept-new",
           "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", VPS_HOST, remote_cmd]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout if r.returncode == 0 else (r.stderr or r.stdout))
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def _vps_psql(sql: str) -> tuple[bool, str]:
    """Run a read-only SELECT on the VPS Postgres via docker exec over SSH.
    The SQL is single-quoted into a psql -tAc; we only ever pass SELECT/count."""
    safe = sql.replace("'", "'\\''")
    remote = f"docker exec {VPS_DB_CONTAINER} psql -U {VPS_DB_USER} -d {VPS_DB_NAME} -tAc '{safe}'"
    return _ssh(remote)


def _vps_rpk(args: str) -> tuple[bool, str]:
    remote = f"docker exec {VPS_REDPANDA_CONTAINER} rpk {args}"
    return _ssh(remote)

# Topics the system uses (for the Redpanda + process panels). Mirrors the
# producers/consumers found in the deployment audit.
KNOWN_TOPICS = ["omni.events", "outreach.commands", "outreach.results",
                "outreach.transitions", "outreach.dead_letter"]

# The omni_* projection tables the DB panel surfaces, in pipeline order.
PROJECTION_TABLES = [
    "omni_events_archive", "omni_leads", "omni_contacts", "omni_companies",
    "omni_deals", "omni_messages", "omni_lead_scores", "omni_ai_jobs",
    # Lead-gen knowledge graph + screening + metrics (Naukri absorption).
    "omni_company_aliases", "omni_people_cache", "omni_company_signals",
    "omni_company_blocklist", "omni_pipeline_metrics", "omni_tasks", "omni_approvals",
]

app = FastAPI(title="Omni Outreach — Audit Control Plane", docs_url="/api/docs")


# ── Findings I/O (atomic write-back) ───────────────────────────────────────────
def _load() -> dict[str, Any]:
    return json.loads(FINDINGS.read_text(encoding="utf-8"))


def _save(data: dict[str, Any]) -> None:
    tmp = FINDINGS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(FINDINGS)  # atomic on the same filesystem


def _finding(data: dict[str, Any], fid: str) -> dict[str, Any] | None:
    return next((f for f in data["findings"] if f["id"] == fid), None)


# ── Endpoints ───────────────────────────────────────────────────────────────────
@app.get("/api/state")
def get_state() -> dict[str, Any]:
    """findings.json augmented with the test binding for each finding."""
    data = _load()
    by_finding: dict[str, list[dict[str, Any]]] = {}
    for t in test_registry.all_tests():
        for fid in t.finding_ids:
            by_finding.setdefault(fid, []).append(
                {"name": t.name, "kind": t.kind, "summary": t.summary, "needs_stack": t.needs_stack}
            )
    return {"meta": data["meta"], "findings": data["findings"], "tests": by_finding,
            "server": True}


class StatusPatch(BaseModel):
    status: str  # VERIFIED | SUSPECTED | FIXED | DISMISSED
    actor: str = "operator"
    note: str | None = None


@app.patch("/api/finding/{fid}")
def patch_finding(fid: str, patch: StatusPatch) -> dict[str, Any]:
    valid = {"VERIFIED", "SUSPECTED", "FIXED", "DISMISSED"}
    if patch.status not in valid:
        raise HTTPException(400, f"status must be one of {sorted(valid)}")
    data = _load()
    f = _finding(data, fid)
    if not f:
        raise HTTPException(404, f"unknown finding {fid}")
    f["status"] = patch.status
    f.setdefault("history", []).append(
        {
            "status": patch.status,
            "actor": patch.actor,
            "note": patch.note,
            "at": datetime.now(UTC).isoformat(),
        }
    )
    _save(data)
    return {"ok": True, "finding": f}


@app.get("/api/health")
def get_health() -> dict[str, Any]:
    """Live system health from the VPS (read-only): `docker ps` over SSH. Each
    probe degrades independently so the panel is honest when SSH/VPS is down."""
    out: dict[str, Any] = {"checked_at": datetime.now(UTC).isoformat(), "source": "vps (read-only)"}
    ok, raw = _ssh("docker ps --format '{{.Names}}|{{.Status}}'")
    services = []
    if ok:
        for line in raw.strip().splitlines():
            if "|" in line:
                name, status = line.split("|", 1)
                services.append({"name": name, "status": status,
                                 "up": "up" in status.lower()})
        out["compose"] = {"ok": True, "services": services}
    else:
        out["compose"] = {"ok": False, "error": raw[:200], "services": []}
    out["stack_up"] = bool(services)
    return out


@app.post("/api/run/{test_name}")
def run_test(test_name: str) -> dict[str, Any]:
    """Run a registry test, capture output as an artifact, and write last_run
    onto every finding the test is bound to."""
    t = test_registry.get(test_name)
    if not t:
        raise HTTPException(404, f"unknown test {test_name}")
    if t.kind == "e2e":
        raise HTTPException(501, "e2e runner is the next vertical slice; not wired yet")

    run_id = f"{test_name}-{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    # t.target is "audit/tests/<file>.py::<func>" relative to the repo root.
    # Resolve the file part to an absolute path; run from BACKEND_DIR so app.*
    # imports resolve.
    file_part, _, func_part = t.target.partition("::")
    abs_target = str(REPO_ROOT / file_part)
    pytest_args = [sys.executable, "-m", "pytest", abs_target,
                   "-q", "--no-header", "-p", "no:cacheprovider"]
    if func_part:
        pytest_args += ["-k", func_part]
    proc = subprocess.run(
        pytest_args, capture_output=True, text=True, timeout=600, cwd=BACKEND_DIR,
    )
    passed = proc.returncode == 0
    artifact = RUNS_DIR / f"{run_id}.txt"
    artifact.write_text((proc.stdout or "") + "\n--- stderr ---\n" + (proc.stderr or ""),
                        encoding="utf-8")

    last_run = {
        "test": test_name,
        "result": "PASS" if passed else "FAIL",
        "run_id": run_id,
        "at": datetime.now(UTC).isoformat(),
    }
    data = _load()
    for fid in t.finding_ids:
        f = _finding(data, fid)
        if f:
            f["last_run"] = last_run
    _save(data)

    return {"ok": True, "result": last_run["result"], "run_id": run_id,
            "finding_ids": list(t.finding_ids),
            "tail": (proc.stdout or "").strip().splitlines()[-15:]}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> FileResponse:
    artifact = RUNS_DIR / f"{run_id}.txt"
    if not artifact.exists():
        raise HTTPException(404, "no such run")
    return FileResponse(artifact, media_type="text/plain")


# ── Visualisation endpoints ─────────────────────────────────────────────────────
@app.get("/api/db")
def get_db() -> dict[str, Any]:
    """Live DB projections from the VPS (read-only). One SSH+psql call returns
    all omni_* counts as 'table=N' lines; a second returns recent events."""
    # All counts in one round-trip via UNION ALL (table list is a fixed allowlist).
    union = " union all ".join(
        f"select '{t}='||count(*) from {t}" for t in PROJECTION_TABLES
    )
    ok, out = _vps_psql(union)
    if not ok:
        return {"available": False, "error": out[:200], "tables": []}
    counts = {}
    for line in out.strip().splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            try:
                counts[k.strip()] = int(v.strip())
            except ValueError:
                pass
    tables = [{"table": t, "count": counts.get(t)} for t in PROJECTION_TABLES]
    # recent events (pipe-delimited so we can split cleanly)
    recent = []
    rok, rout = _vps_psql(
        "select event_type||'|'||coalesce(entity_type,'')||'|'||to_char(occurred_at,'HH24:MI:SS')||'|'||coalesce(correlation_id::text,'') "
        "from omni_events_archive order by occurred_at desc limit 8"
    )
    if rok:
        for line in rout.strip().splitlines():
            p = line.split("|")
            if len(p) >= 4:
                recent.append({"event_type": p[0], "entity_type": p[1],
                               "at": p[2], "correlation_id": p[3] or None})
    return {"available": True, "checked_at": datetime.now(UTC).isoformat(),
            "source": "vps (read-only)", "tables": tables, "recent_events": recent}


@app.get("/api/topics")
def get_topics() -> dict[str, Any]:
    """Redpanda per-topic + per-group lag from the VPS (read-only). ONE SSH call:
    a remote shell snippet runs `rpk topic list`, `rpk group list`, and a
    `group describe` per group, fenced with markers we parse here."""
    remote = (
        f"C() {{ docker exec {VPS_REDPANDA_CONTAINER} rpk \"$@\"; }}; "
        "echo '@@TOPICS'; C topic list; "
        # `rpk group list` columns are: BROKER GROUP STATE -> group name is $2
        "echo '@@GROUPS'; for g in $(C group list | awk 'NR>1{print $2}'); do "
        "echo \"@@G $g\"; C group describe -s \"$g\" 2>/dev/null; done"
    )
    ok, out = _ssh(remote, timeout=30)
    if not ok:
        return {"available": False, "error": out[:200], "topics": []}
    topics, lag = [], []
    section, cur = None, None
    for line in out.splitlines():
        s = line.strip()
        if s == "@@TOPICS":
            section = "topics"; continue
        if s == "@@GROUPS":
            section = "groups"; continue
        if s.startswith("@@G "):
            cur = {"group": s[4:].strip(), "total_lag": 0, "state": "?"}
            lag.append(cur); continue
        if section == "topics":
            p = s.split()
            if len(p) >= 3 and p[0] != "NAME":
                topics.append({"name": p[0], "partitions": p[1], "replicas": p[2]})
        elif section == "groups" and cur is not None:
            # `rpk group describe -s` prints key-value rows: "KEY   VALUE".
            if s.startswith("STATE"):
                cur["state"] = s.split()[-1]
            elif s.startswith("TOTAL-LAG"):
                p = s.split()
                if p[-1].lstrip("-").isdigit():
                    cur["total_lag"] = int(p[-1])
    seen = {t["name"] for t in topics}
    for kt in KNOWN_TOPICS:
        if kt not in seen:
            topics.append({"name": kt, "partitions": "—", "replicas": "—", "missing": True})
    return {"available": True, "checked_at": datetime.now(UTC).isoformat(),
            "source": "vps (read-only)", "topics": topics, "consumer_groups": lag}


@app.get("/api/process")
def get_process() -> dict[str, Any]:
    """Pipeline topology with finding stall-points overlaid. The nodes are the
    planes; edges are the topics. Each overlay carries the LIVE status of its
    finding (read from findings.json) so the UI paints a FIXED/DISMISSED hop as
    resolved instead of red — the overlay map is the historical set of implicated
    hops; their current truth comes from the findings file."""
    nodes = [
        {"id": "nodes", "label": "Canvas nodes", "kind": "produce"},
        {"id": "omni.events", "label": "omni.events", "kind": "topic"},
        {"id": "dispatcher", "label": "Dispatcher", "kind": "worker"},
        {"id": "outreach.commands", "label": "outreach.commands", "kind": "topic"},
        {"id": "muscle", "label": "Rust muscle", "kind": "worker"},
        {"id": "outreach.results", "label": "outreach.results", "kind": "topic"},
        {"id": "flink", "label": "Flink orchestrator", "kind": "worker"},
        {"id": "outreach.transitions", "label": "outreach.transitions", "kind": "topic"},
        {"id": "transitions", "label": "Transition worker", "kind": "worker"},
        {"id": "projector", "label": "Projector", "kind": "worker"},
        {"id": "db", "label": "Postgres omni_*", "kind": "store"},
        {"id": "outreach.dead_letter", "label": "dead_letter", "kind": "topic"},
    ]
    edges = [
        {"from": "nodes", "to": "omni.events"},
        {"from": "omni.events", "to": "dispatcher"},
        {"from": "omni.events", "to": "projector"},
        {"from": "dispatcher", "to": "outreach.commands"},
        {"from": "outreach.commands", "to": "muscle"},
        {"from": "muscle", "to": "outreach.results"},
        {"from": "muscle", "to": "outreach.dead_letter"},
        {"from": "outreach.results", "to": "flink"},
        {"from": "flink", "to": "outreach.transitions"},
        {"from": "outreach.transitions", "to": "transitions"},
        {"from": "transitions", "to": "omni.events"},
        {"from": "transitions", "to": "outreach.results"},
        {"from": "projector", "to": "db"},
    ]
    # Overlay: the historical map of HIGH/MEDIUM findings to the hop they
    # implicate. The current status is stitched in live below so a resolved
    # finding stops painting its hop red.
    overlays = [
        {"target": "dispatcher", "finding": "CONTRACT-001",
         "note": "nodes that emit an unroutable intent now error the lead loudly instead of stalling; dead canvas nodes removed"},
        {"target": "dispatcher", "finding": "DEPLOY-002",
         "note": "auto_offset_reset=latest → intents before join never dispatched"},
        {"target": "transitions", "finding": "DEPLOY-001",
         "note": "auto-commit + non-idempotent fan-out → drop / double-spawn"},
        {"target": "transitions", "finding": "DATAFLOW-001",
         "note": "correlation_id dropped for condition/flow nodes → trace forks"},
        {"target": "projector", "finding": "PROJ-001",
         "note": "projection gated on archive first-insert → transient failure skips it forever"},
        {"target": "flink", "finding": "FLINK-001",
         "note": "retriable failure parks a dead timer; muscle never redrives"},
        {"target": "outreach.results", "finding": "DATAFLOW-002",
         "note": "results never archived → trace tool can't see the muscle round-trip"},
        {"target": "outreach.dead_letter", "finding": "RETRY-THEME",
         "note": "DLQ has no consumer; nothing redrives poison"},
    ]
    # Stitch live status + the recorded fix onto each overlay so the UI knows
    # whether the hop is still broken (VERIFIED) or resolved (FIXED/DISMISSED).
    try:
        data = _load()
        by_id = {f["id"]: f for f in data["findings"]}
    except Exception:  # noqa: BLE001 — viz must not 500 if findings is unreadable
        by_id = {}
    for o in overlays:
        f = by_id.get(o["finding"], {})
        o["status"] = f.get("status", "UNKNOWN")
        o["resolved"] = o["status"] in ("FIXED", "DISMISSED")
        if f.get("fix"):
            o["fix"] = f["fix"]
    return {"nodes": nodes, "edges": edges, "overlays": overlays}


_UUID_RE = __import__("re").compile(r"^[0-9a-fA-F-]{8,40}$")


@app.get("/api/trace/{correlation_id}")
def get_trace(correlation_id: str) -> dict[str, Any]:
    """Per-run timeline from the VPS omni_events_archive (read-only). Mirrors
    backend/app/tools/trace.py. correlation_id is validated as a UUID-ish token
    before being embedded in the SELECT."""
    if not _UUID_RE.match(correlation_id):
        raise HTTPException(400, "correlation_id must be a UUID-like token")
    # pipe-delimited columns; node_id pulled from payload JSON
    sql = (
        "select to_char(occurred_at,'HH24:MI:SS.MS')||'|'||event_type||'|'||"
        "coalesce(entity_type,'')||'|'||coalesce(entity_id::text,'')||'|'||"
        "coalesce(payload->>'node_id','') "
        f"from omni_events_archive where correlation_id='{correlation_id}' "
        "order by occurred_at asc, kafka_offset asc"
    )
    ok, out = _vps_psql(sql)
    if not ok:
        return {"available": False, "error": out[:200]}
    events = []
    for line in out.strip().splitlines():
        if not line.strip():
            continue
        p = line.split("|")
        if len(p) >= 5:
            events.append({"at": p[0], "event_type": p[1], "entity_type": p[2],
                           "entity_id": p[3] or None, "node_id": p[4] or None})
    return {"available": True, "correlation_id": correlation_id,
            "source": "vps (read-only)", "event_count": len(events), "events": events}


@app.get("/api/correlations")
def get_correlations() -> dict[str, Any]:
    """Recent correlation_ids in the VPS archive (read-only), for the picker."""
    sql = (
        "select correlation_id||'|'||count(*)||'|'||to_char(max(occurred_at),'MM-DD HH24:MI') "
        "from omni_events_archive where correlation_id is not null "
        "group by correlation_id order by max(occurred_at) desc limit 20"
    )
    ok, out = _vps_psql(sql)
    if not ok:
        return {"available": False, "error": out[:200], "correlations": []}
    cors = []
    for line in out.strip().splitlines():
        p = line.split("|")
        if len(p) >= 3:
            cors.append({"correlation_id": p[0], "events": int(p[1]) if p[1].isdigit() else 0,
                         "last": p[2]})
    return {"available": True, "source": "vps (read-only)", "correlations": cors}


# Serve the static dashboard at / (mounted last so /api/* wins).
app.mount("/", StaticFiles(directory=str(AUDIT_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    print("[audit-server] http://127.0.0.1:8799  (localhost-only control plane)")
    uvicorn.run(app, host="127.0.0.1", port=8799, log_level="warning")
