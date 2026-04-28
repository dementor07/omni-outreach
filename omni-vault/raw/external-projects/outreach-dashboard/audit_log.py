import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

_LOCK = threading.Lock()


def _log_path() -> Path:
    configured = os.getenv("AUDIT_LOG_PATH", "logs/audit.jsonl").strip()
    path = Path(configured)
    if not path.is_absolute():
        path = Path(__file__).parent / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _max_bytes() -> int:
    return int(os.getenv("AUDIT_LOG_MAX_BYTES", str(5 * 1024 * 1024)))


def _max_backups() -> int:
    return int(os.getenv("AUDIT_LOG_MAX_BACKUPS", "5"))


def _rotate_if_needed(path: Path) -> None:
    if not path.exists() or path.stat().st_size < _max_bytes():
        return

    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    rotated = path.with_name(f"{path.stem}.{ts}{path.suffix}")
    path.rename(rotated)

    backups = sorted(path.parent.glob(f"{path.stem}.*{path.suffix}"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[_max_backups():]:
        old.unlink(missing_ok=True)


def log_event(
    *,
    action: str,
    actor: str,
    status: str,
    target: str | None = None,
    details: dict[str, Any] | None = None,
    approval_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "actor": actor,
        "action": action,
        "status": status,
        "target": target,
        "approval_id": approval_id,
        "details": details or {},
    }

    path = _log_path()
    line = json.dumps(payload, ensure_ascii=False)
    with _LOCK:
        _rotate_if_needed(path)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    return payload


def read_recent(limit: int = 200) -> list[dict[str, Any]]:
    path = _log_path()
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

