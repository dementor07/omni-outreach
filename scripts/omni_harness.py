#!/usr/bin/env python3
"""Agent-ergonomic client for Omni's durable harness broker.

Human/default output is compact TOON. stdout is reserved for the final result;
poll banners and diagnostics go to stderr so agents can safely compose this
client. The API key is accepted only through OMNI_API_KEY and is never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


VIEW_SPEC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "description", "icon", "layout"],
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "icon": {"type": "string"},
        "layout": {
            "type": "array",
            "items": {"$ref": "#/$defs/widget"},
        },
    },
    "$defs": {
        "filter": {
            "type": "object",
            "additionalProperties": False,
            "required": ["field", "op", "value"],
            "properties": {
                "field": {"type": "string"},
                "op": {
                    "type": "string",
                    "enum": ["eq", "neq", "gt", "gte", "lt", "lte", "contains", "in", "not_in", "is_null", "not_null"],
                },
                "value": {"anyOf": [
                    {"type": "string"},
                    {"type": "number"},
                    {"type": "boolean"},
                    {"type": "array", "items": {"anyOf": [
                        {"type": "string"}, {"type": "number"},
                        {"type": "boolean"}, {"type": "null"},
                    ]}},
                    {"type": "null"},
                ]},
            },
        },
        "metric": {
            "type": "object",
            "additionalProperties": False,
            "required": ["fn", "field", "alias"],
            "properties": {
                "fn": {"type": "string", "enum": ["count", "count_distinct", "sum", "avg", "min", "max"]},
                "field": {"type": ["string", "null"]},
                "alias": {"type": ["string", "null"]},
            },
        },
        "sort": {
            "type": "object",
            "additionalProperties": False,
            "required": ["field", "dir"],
            "properties": {
                "field": {"type": "string"},
                "dir": {"type": "string", "enum": ["asc", "desc"]},
            },
        },
        "query": {
            "type": "object",
            "additionalProperties": False,
            "required": ["entity", "filters", "select", "group_by", "metrics", "time_bucket", "sort", "limit"],
            "properties": {
                "entity": {"type": "string"},
                "filters": {"type": "array", "items": {"$ref": "#/$defs/filter"}},
                "select": {"type": "array", "items": {"type": "string"}},
                "group_by": {"type": "array", "items": {"type": "string"}},
                "metrics": {"type": "array", "items": {"$ref": "#/$defs/metric"}},
                "time_bucket": {"type": ["string", "null"], "enum": ["day", "week", "month", None]},
                "sort": {"type": "array", "items": {"$ref": "#/$defs/sort"}},
                "limit": {"type": "integer"},
            },
        },
        "widget": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "type", "title", "query", "width", "height", "options"],
            "properties": {
                "id": {"type": "string"},
                "type": {"type": "string", "enum": ["stat", "table", "bar_chart", "line_chart", "list"]},
                "title": {"type": "string"},
                "query": {"$ref": "#/$defs/query"},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
                "options": {"type": "object", "additionalProperties": False, "properties": {}},
            },
        },
    },
}


class CliError(RuntimeError):
    def __init__(self, code: str, cause: str, next_step: str, exit_code: int = 1) -> None:
        super().__init__(cause)
        self.code = code
        self.cause = cause
        self.next_step = next_step
        self.exit_code = exit_code


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toon(mapping: dict[str, Any]) -> str:
    """Encode this client's deliberately flat AXI result envelopes as TOON."""
    lines: list[str] = []
    for key, value in mapping.items():
        if value is None:
            rendered = "null"
        elif isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, (int, float)):
            rendered = str(value)
        else:
            rendered = _quote(str(value))
        lines.append(f"{key}: {rendered}")
    return "\n".join(lines)


def _emit(mapping: dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(mapping, indent=2, ensure_ascii=False))
    else:
        print(_toon(mapping))


def _config() -> tuple[str, str]:
    base = os.environ.get("OMNI_API_URL", "").strip().rstrip("/")
    key = os.environ.get("OMNI_API_KEY", "").strip()
    if not base:
        raise CliError(
            "config_missing_url",
            "OMNI_API_URL is not set",
            "Set it to Omni's API base, for example https://host.example/api.",
            2,
        )
    if not key:
        raise CliError(
            "config_missing_key",
            "OMNI_API_KEY is not set",
            "Create a workspace API key in Settings, then export it only in this shell.",
            2,
        )
    return base, key


def _harness_name(value: str | None) -> str:
    candidate = value or os.environ.get("OMNI_HARNESS_NAME") or f"agent-{socket.gethostname()}"
    normalized = re.sub(r"[^A-Za-z0-9._:-]", "-", candidate).strip("-._:")[:80]
    if not normalized:
        raise CliError("bad_harness_name", "harness name is empty after normalization", "Use --name with letters or digits.", 2)
    return normalized


def _request(method: str, path: str, body: dict[str, Any] | None = None, timeout: int = 40) -> tuple[int, Any]:
    base, key = _config()
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{base}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "omni-harness/1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw) if raw else {}
            detail = payload.get("detail") or str(payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            detail = raw.decode("utf-8", errors="replace")[:500]
        if exc.code == 401:
            next_step = "Check OMNI_API_KEY or mint a fresh workspace key in Settings."
        elif exc.code == 409:
            next_step = "The lease is no longer live. Poll again; never reuse an old claim file."
        elif exc.code == 422:
            next_step = "Correct the candidate or request shape described by the error, then retry."
        else:
            next_step = "Check the API health and retry. The durable job remains safe."
        raise CliError(f"http_{exc.code}", str(detail), next_step, 3) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise CliError(
            "network_unreachable",
            str(getattr(exc, "reason", exc)),
            "Check OMNI_API_URL and network reachability, then rerun the command.",
            4,
        ) from exc


def _state_root(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _job_dir(root: Path, job_id: str) -> Path:
    return root / "jobs" / job_id


def _write_claim(root: Path, claim: dict[str, Any]) -> tuple[Path, Path]:
    directory = _job_dir(root, str(claim["id"]))
    directory.mkdir(parents=True, exist_ok=True)
    claim_path = directory / "claim.local.json"
    brief_path = directory / "brief.json"
    claim_path.write_text(json.dumps(claim, indent=2, ensure_ascii=False), encoding="utf-8")
    brief_path.write_text(json.dumps(claim["payload"], indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(claim_path, 0o600)
        os.chmod(brief_path, 0o600)
    except OSError:
        pass
    return claim_path, brief_path


def _write_schema(root: Path, job_id: str) -> Path:
    path = _job_dir(root, job_id) / "result.schema.json"
    path.write_text(json.dumps(VIEW_SPEC_SCHEMA, indent=2), encoding="utf-8")
    return path


def _load_claim(root: Path, job_id: str) -> tuple[dict[str, Any], Path]:
    path = _job_dir(root, job_id) / "claim.local.json"
    if not path.exists():
        raise CliError(
            "claim_not_found",
            f"no local lease state for job {job_id}",
            "Run poll/listen from this state directory and use the returned job ID.",
            2,
        )
    try:
        return json.loads(path.read_text(encoding="utf-8")), path
    except (OSError, json.JSONDecodeError) as exc:
        raise CliError("claim_unreadable", str(exc), "Remove the corrupt local claim and poll again.", 2) from exc


def _poll_once(args: argparse.Namespace, *, silent_empty: bool) -> bool:
    harness_id = _harness_name(args.name)
    print(
        f"[omni-harness] listening as {harness_id!r}; held poll up to {args.wait}s",
        file=sys.stderr,
        flush=True,
    )
    status, claim = _request(
        "POST",
        "/agent-harness/jobs/poll",
        {"harness_id": harness_id, "wait_seconds": args.wait},
        timeout=args.wait + 15,
    )
    if status == 204 or claim is None:
        if not silent_empty:
            _emit(
                {
                    "state": "listening",
                    "job": None,
                    "waitedSeconds": args.wait,
                    "next": "Run poll again, or use listen to keep polling continuously.",
                },
                args.format,
            )
        return False

    claim["_harness_id"] = harness_id
    claim_path, brief_path = _write_claim(_state_root(args.state_dir), claim)
    _emit(
        {
            "state": "working",
            "jobId": claim["id"],
            "kind": claim["kind"],
            "attempt": claim["attempts"],
            "briefFile": brief_path,
            "claimFile": claim_path,
            "next": f"Read briefFile, then report progress and complete job {claim['id']}.",
        },
        args.format,
    )
    return True


def command_poll(args: argparse.Namespace) -> None:
    _poll_once(args, silent_empty=False)


def command_listen(args: argparse.Namespace) -> None:
    while not _poll_once(args, silent_empty=True):
        print("[omni-harness] no job; reconnecting", file=sys.stderr, flush=True)


def _lease_from_claim(claim: dict[str, Any]) -> dict[str, Any]:
    return {
        "harness_id": claim["_harness_id"],
        "lease_token": claim["lease_token"],
    }


def _job_event(claim: dict[str, Any], action: str, **extra: Any) -> Any:
    body = {**_lease_from_claim(claim), **extra}
    _, result = _request("POST", f"/agent-harness/jobs/{claim['id']}/{action}", body)
    return result


def _agent_environment() -> dict[str, str]:
    """Pass enough OS/Codex state to run, never the broker credential."""
    allowed = {
        "APPDATA", "CODEX_HOME", "COMSPEC", "HOME", "HOMEDRIVE", "HOMEPATH",
        "HTTP_PROXY", "HTTPS_PROXY", "LANG", "LC_ALL", "LOCALAPPDATA", "NO_PROXY",
        "NODE_EXTRA_CA_CERTS", "NPM_CONFIG_CACHE", "OPENAI_API_KEY", "OPENAI_BASE_URL",
        "PATH", "PATHEXT", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
        "SSL_CERT_FILE", "SYSTEMDRIVE", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE",
        "WINDIR", "XDG_CACHE_HOME", "XDG_CONFIG_HOME",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def _prompt_for(claim: dict[str, Any]) -> str:
    return (
        "You are the view-authoring harness for Omni Outreach. Work only from the grounded "
        "job brief below. Return exactly one complete ViewSpec JSON object matching the "
        "provided output schema. Do not edit files, inspect the host repository, call APIs, "
        "send messages, or change campaign state. Preserve unrequested widgets and stable "
        "widget IDs. Apply each widget annotation only to its named widget unless the "
        "whole-view instruction necessarily affects another widget. Use only entities and "
        "fields present in widget_catalog.\n\nGROUNDED JOB BRIEF:\n"
        + json.dumps(claim["payload"], indent=2, ensure_ascii=False)
    )


def _codex_command(args: argparse.Namespace, directory: Path, schema_path: Path, result_path: Path) -> list[str]:
    prefix = shlex.split(args.codex_command, posix=os.name != "nt")
    if not prefix:
        raise CliError("codex_command_empty", "--codex-command is empty", "Use the default npx command or provide a Codex executable.", 2)
    executable = shutil.which(prefix[0])
    if executable is None:
        raise CliError(
            "codex_not_found",
            f"could not find {prefix[0]!r} on PATH",
            "Install Codex CLI or keep the default 'npx -y @openai/codex' command.",
            5,
        )
    command = [executable, *prefix[1:], "exec", "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only"]
    if args.model:
        command.extend(["--model", args.model])
    command.extend([
        "-C", str(directory),
        "--output-schema", str(schema_path),
        "--output-last-message", str(result_path),
        "-",
    ])
    return command


def _external_command(args: argparse.Namespace, directory: Path, schema_path: Path, result_path: Path, brief_path: Path) -> list[str]:
    if not args.command:
        raise CliError(
            "command_missing",
            "--engine command requires --command",
            "Provide an argv template whose process writes JSON to {result}, for example 'agent --brief {brief} --schema {schema} --out {result}'.",
            2,
        )
    replacements = {
        "{brief}": str(brief_path),
        "{schema}": str(schema_path),
        "{result}": str(result_path),
        "{job_dir}": str(directory),
    }
    tokens = shlex.split(args.command, posix=os.name != "nt")
    command = [replacements.get(token, token) for token in tokens]
    if not command or not shutil.which(command[0]):
        raise CliError("agent_not_found", f"could not find agent command {command[0] if command else ''!r}", "Correct --command and rerun the harness.", 5)
    return command


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _execute_claim(args: argparse.Namespace, claim: dict[str, Any], root: Path) -> None:
    job_id = str(claim["id"])
    directory = _job_dir(root, job_id)
    claim_path, brief_path = _write_claim(root, claim)
    schema_path = _write_schema(root, job_id)
    result_path = directory / "result.json"
    result_path.unlink(missing_ok=True)
    command = (
        _codex_command(args, directory, schema_path, result_path)
        if args.engine == "codex"
        else _external_command(args, directory, schema_path, result_path, brief_path)
    )

    _job_event(claim, "progress", message=f"Invoking {args.engine} in an isolated job directory")
    print(f"[omni-harness] job {job_id}: starting {args.engine}", file=sys.stderr, flush=True)
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=directory,
        env=_agent_environment(),
        stdin=subprocess.PIPE if args.engine == "codex" else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    prompt = _prompt_for(claim) if args.engine == "codex" else None
    first_wait = True
    while True:
        try:
            stdout, stderr = process.communicate(
                input=prompt if first_wait else None,
                timeout=args.heartbeat_seconds,
            )
            break
        except subprocess.TimeoutExpired:
            first_wait = False
            try:
                _job_event(claim, "heartbeat")
                elapsed = int(time.monotonic() - started)
                if elapsed and elapsed % 60 < args.heartbeat_seconds:
                    _job_event(claim, "progress", message=f"{args.engine} is still working ({elapsed}s)")
            except CliError as exc:
                _stop_process(process)
                if exc.code == "http_409":
                    print(f"[omni-harness] job {job_id}: lease ended; agent stopped", file=sys.stderr, flush=True)
                    return
                raise

    if process.returncode != 0:
        detail = (stderr or stdout or f"{args.engine} exited {process.returncode}").strip()[-1200:]
        raise CliError("agent_failed", detail, "Inspect the local job directory, correct the agent setup, and queue a fresh job.", 5)
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CliError("agent_result_invalid", str(exc), "The agent must write one complete ViewSpec JSON object to the result path.", 5) from exc
    _job_event(claim, "complete", result=result)
    claim_path.unlink(missing_ok=True)
    print(f"[omni-harness] job {job_id}: validated result returned; polling again", file=sys.stderr, flush=True)


def _claim_once(args: argparse.Namespace) -> dict[str, Any] | None:
    harness_id = _harness_name(args.name)
    _, claim = _request(
        "POST",
        "/agent-harness/jobs/poll",
        {"harness_id": harness_id, "wait_seconds": args.wait},
        timeout=args.wait + 15,
    )
    if claim is None:
        return None
    claim["_harness_id"] = harness_id
    return claim


def command_run(args: argparse.Namespace) -> None:
    root = _state_root(args.state_dir)
    harness_id = _harness_name(args.name)
    print(
        f"[omni-harness] {harness_id!r} running with engine={args.engine}; continuous {args.wait}s polls",
        file=sys.stderr,
        flush=True,
    )
    while True:
        claim = _claim_once(args)
        if claim is None:
            print("[omni-harness] poll returned empty; reconnecting", file=sys.stderr, flush=True)
            continue
        try:
            _execute_claim(args, claim, root)
        except CliError as exc:
            print(_toon({"error": exc.code, "cause": exc.cause, "next": exc.next_step}), file=sys.stderr)
            try:
                _job_event(claim, "fail", error=f"{exc.code}: {exc.cause}"[:2000])
            except CliError as fail_exc:
                print(_toon({"error": fail_exc.code, "cause": fail_exc.cause, "next": fail_exc.next_step}), file=sys.stderr)
            (_job_dir(root, str(claim["id"])) / "claim.local.json").unlink(missing_ok=True)


def _lease_body(args: argparse.Namespace) -> tuple[dict[str, Any], Path]:
    claim, path = _load_claim(_state_root(args.state_dir), args.job)
    return {
        "harness_id": _harness_name(args.name or claim.get("_harness_id")),
        "lease_token": claim["lease_token"],
    }, path


def command_heartbeat(args: argparse.Namespace) -> None:
    body, _ = _lease_body(args)
    _, result = _request("POST", f"/agent-harness/jobs/{args.job}/heartbeat", body)
    _emit({"state": result["status"], "jobId": args.job, "leaseRenewed": True, "next": "Continue work or complete the job."}, args.format)


def command_progress(args: argparse.Namespace) -> None:
    body, _ = _lease_body(args)
    body["message"] = args.message
    _, result = _request("POST", f"/agent-harness/jobs/{args.job}/progress", body)
    _emit({"state": result["status"], "jobId": args.job, "progressEvents": len(result["progress"]), "next": "Continue work or complete the job."}, args.format)


def command_complete(args: argparse.Namespace) -> None:
    body, claim_path = _lease_body(args)
    result_path = Path(args.result).expanduser().resolve()
    try:
        body["result"] = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CliError("result_unreadable", str(exc), "Write one complete ViewSpec JSON object to --result.", 2) from exc
    _, result = _request("POST", f"/agent-harness/jobs/{args.job}/complete", body)
    claim_path.unlink(missing_ok=True)
    _emit({"state": result["status"], "jobId": args.job, "validated": True, "next": "Review and explicitly apply the candidate in Omni."}, args.format)


def command_fail(args: argparse.Namespace) -> None:
    body, claim_path = _lease_body(args)
    body["error"] = args.error
    _, result = _request("POST", f"/agent-harness/jobs/{args.job}/fail", body)
    claim_path.unlink(missing_ok=True)
    _emit({"state": result["status"], "jobId": args.job, "next": "Correct the cause and queue a fresh job in Omni."}, args.format)


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--name", help="Stable harness label (or OMNI_HARNESS_NAME)")
    common.add_argument("--state-dir", default=".omni-harness", help="Local lease/brief directory (default: .omni-harness)")
    common.add_argument("--format", choices=("toon", "json"), default="toon", help="stdout format (default: toon)")

    root = argparse.ArgumentParser(
        prog="omni-harness",
        description="Poll and complete durable Omni agent jobs. Reads OMNI_API_URL and OMNI_API_KEY.",
    )
    sub = root.add_subparsers(dest="command", required=True)
    for name, help_text, handler in (
        ("poll", "hold one poll, returning a job or definitive empty state", command_poll),
        ("listen", "keep reconnecting until one job is claimed", command_listen),
    ):
        item = sub.add_parser(name, parents=[common], help=help_text)
        item.add_argument("--wait", type=int, choices=range(1, 26), default=25, metavar="1..25")
        item.set_defaults(handler=handler)

    run = sub.add_parser("run", parents=[common], help="continuously poll, invoke an agent, heartbeat, and return validated results")
    run.add_argument("--wait", type=int, choices=range(1, 26), default=25, metavar="1..25")
    run.add_argument("--heartbeat-seconds", type=int, choices=range(10, 61), default=20, metavar="10..60")
    run.add_argument("--engine", choices=("codex", "command"), default="codex")
    run.add_argument("--model", help="Optional Codex model override")
    run.add_argument("--codex-command", default=os.environ.get("OMNI_CODEX_COMMAND", "npx -y @openai/codex@0.147.0"), help="Codex argv prefix (default: tested Codex CLI 0.147.0)")
    run.add_argument("--command", help="External argv template; supports {brief}, {schema}, {result}, {job_dir}")
    run.set_defaults(handler=command_run)

    for name, help_text, handler in (
        ("heartbeat", "renew a claimed job lease", command_heartbeat),
        ("progress", "append one visible progress message", command_progress),
        ("complete", "validate and return a JSON result", command_complete),
        ("fail", "finish a claimed job with a structured failure", command_fail),
    ):
        item = sub.add_parser(name, parents=[common], help=help_text)
        item.add_argument("--job", required=True, help="Job UUID returned by poll/listen")
        if name == "progress":
            item.add_argument("--message", required=True, help="Visible progress message (max 500 chars)")
        elif name == "complete":
            item.add_argument("--result", required=True, help="Path to one complete result JSON object")
        elif name == "fail":
            item.add_argument("--error", required=True, help="Actionable failure message")
        item.set_defaults(handler=handler)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        args.handler(args)
        return 0
    except CliError as exc:
        print(
            _toon({"error": exc.code, "cause": exc.cause, "next": exc.next_step}),
            file=sys.stderr,
        )
        return exc.exit_code
    except KeyboardInterrupt:
        print(_toon({"error": "interrupted", "cause": "operator stopped the poll", "next": "Run listen again when ready."}), file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
