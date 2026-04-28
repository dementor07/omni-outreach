import json
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from audit_log import log_event

load_dotenv()

_LOCK = threading.Lock()
_SESSIONS: dict[str, dict[str, Any]] = {}


def _terminal_log_path() -> Path:
    configured = os.getenv("TERMINAL_LOG_PATH", "logs/terminal.jsonl").strip()
    path = Path(configured)
    if not path.is_absolute():
        path = Path(__file__).parent / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _workdir() -> str | None:
    configured = os.getenv("TERMINAL_WORKDIR", "").strip()
    if configured:
        return configured
    return str(Path(__file__).parent)


def _timeout() -> int:
    return int(os.getenv("TERMINAL_COMMAND_TIMEOUT_SECONDS", "90"))


def _append_terminal_log(record: dict[str, Any]) -> None:
    path = _terminal_log_path()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def create_session(actor: str) -> dict[str, Any]:
    session_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()
    session = {
        "session_id": session_id,
        "actor": actor,
        "created_at": now,
        "history": [],
    }
    with _LOCK:
        _SESSIONS[session_id] = session

    log_event(
        action="terminal.session.create",
        actor=actor,
        status="ok",
        target=session_id,
    )
    return {"session_id": session_id, "created_at": now}


def _get_session(session_id: str) -> dict[str, Any]:
    with _LOCK:
        session = _SESSIONS.get(session_id)
        if not session:
            raise RuntimeError(f"Unknown session_id: {session_id}")
        return session


def execute_command(
    *,
    session_id: str,
    command: str,
    actor: str,
    approval_id: str | None = None,
) -> dict[str, Any]:
    session = _get_session(session_id)

    started = time.time()
    try:
        run = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=_timeout(),
            cwd=_workdir(),
        )
        exit_code = run.returncode
        stdout = run.stdout
        stderr = run.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + "\nCommand timed out."
    duration_ms = int((time.time() - started) * 1000)
    now = datetime.now(tz=timezone.utc).isoformat()

    record = {
        "timestamp": now,
        "session_id": session_id,
        "actor": actor,
        "approval_id": approval_id,
        "command": command,
        "exit_code": exit_code,
        "stdout": stdout[-12000:],
        "stderr": stderr[-12000:],
        "duration_ms": duration_ms,
    }

    with _LOCK:
        session["history"].append(record)

    _append_terminal_log(record)
    log_event(
        action="terminal.command.execute",
        actor=actor,
        status="ok" if exit_code == 0 else "failed",
        target=session_id,
        approval_id=approval_id,
        details={"command": command, "exit_code": exit_code},
    )
    return record


def list_history(limit: int = 200) -> list[dict[str, Any]]:
    path = _terminal_log_path()
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        lines = f.readlines()
    out: list[dict[str, Any]] = []
    for raw in lines[-limit:]:
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out
