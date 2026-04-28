import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

from campaign_validate import validate_campaign_json

load_dotenv()

FOLDER_MIME = "application/vnd.google-apps.folder"
ALLOWED_TEMPLATE_STEPS = {"step_1", "step_2", "step_3", "step_4"}
ALLOWED_PROMPT_KEYS = {"claude_system_prompt", "claude_user_prompt", "screening_prompt"}


def _service_account_file() -> str:
    path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not path:
        fallback = Path(__file__).parent.parent / "outreach_automation" / "google_service_account.json"
        if fallback.exists():
            path = str(fallback)
    if not path:
        raise RuntimeError("Missing GOOGLE_SERVICE_ACCOUNT_JSON")
    if not Path(path).exists():
        raise RuntimeError(f"Service account file not found: {path}")
    return path


@lru_cache(maxsize=1)
def _drive():
    creds = Credentials.from_service_account_file(
        _service_account_file(),
        scopes=["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"],
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _escape(value: str) -> str:
    return value.replace("'", "\\'")


def _find_child(parent_id: str, name: str, mime_type: str | None = None) -> dict[str, Any] | None:
    q = f"'{parent_id}' in parents and name = '{_escape(name)}' and trashed = false"
    if mime_type:
        q += f" and mimeType = '{mime_type}'"
    resp = _drive().files().list(
        q=q,
        spaces="drive",
        fields="files(id,name,mimeType,modifiedTime)",
        pageSize=1,
    ).execute()
    files = resp.get("files", [])
    return files[0] if files else None


def _list_children(parent_id: str, mime_type: str | None = None) -> list[dict[str, Any]]:
    q = f"'{parent_id}' in parents and trashed = false"
    if mime_type:
        q += f" and mimeType = '{mime_type}'"
    resp = _drive().files().list(
        q=q,
        spaces="drive",
        fields="files(id,name,mimeType,modifiedTime)",
        pageSize=200,
        orderBy="name",
    ).execute()
    return resp.get("files", [])


def _ensure_folder(parent_id: str, name: str) -> dict[str, Any]:
    existing = _find_child(parent_id, name, FOLDER_MIME)
    if existing:
        return existing
    meta = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
    created = _drive().files().create(body=meta, fields="id,name,mimeType,modifiedTime").execute()
    return created


def _read_text_file(file_id: str) -> str:
    raw = _drive().files().get_media(fileId=file_id).execute()
    return raw.decode("utf-8")


def _upsert_text_file(parent_id: str, name: str, content: str) -> dict[str, Any]:
    existing = _find_child(parent_id, name)
    media = MediaInMemoryUpload(content.encode("utf-8"), mimetype="text/plain", resumable=False)
    if existing:
        return _drive().files().update(
            fileId=existing["id"],
            media_body=media,
            fields="id,name,mimeType,modifiedTime",
        ).execute()
    meta = {"name": name, "parents": [parent_id], "mimeType": "text/plain"}
    return _drive().files().create(
        body=meta,
        media_body=media,
        fields="id,name,mimeType,modifiedTime",
    ).execute()


def _config_root_id() -> str:
    root_id = os.getenv("DRIVE_CONFIG_ROOT_FOLDER_ID", "").strip()
    if not root_id:
        raise RuntimeError("Missing DRIVE_CONFIG_ROOT_FOLDER_ID")
    return root_id


def _campaigns_folder() -> dict[str, Any]:
    explicit = os.getenv("DRIVE_CAMPAIGNS_FOLDER_ID", "").strip()
    if explicit:
        return {"id": explicit, "name": "campaigns", "mimeType": FOLDER_MIME}
    return _ensure_folder(_config_root_id(), "campaigns")


def _campaign_folder(campaign_id: str, create: bool = False) -> dict[str, Any] | None:
    parent = _campaigns_folder()["id"]
    existing = _find_child(parent, campaign_id, FOLDER_MIME)
    if existing or not create:
        return existing
    return _ensure_folder(parent, campaign_id)


def _collect_campaign_files(campaign_folder_id: str) -> dict[str, Any]:
    children = _list_children(campaign_folder_id)
    by_name = {f["name"]: f for f in children}

    templates_folder = by_name.get("templates")
    prompts_folder = by_name.get("prompts")
    campaign_json_file = by_name.get("campaign.json")

    template_files = []
    prompt_files = []
    if templates_folder and templates_folder.get("mimeType") == FOLDER_MIME:
        template_files = _list_children(templates_folder["id"])
    if prompts_folder and prompts_folder.get("mimeType") == FOLDER_MIME:
        prompt_files = _list_children(prompts_folder["id"])

    campaign_json = None
    campaign_json_raw = None
    parse_error = None
    if campaign_json_file:
        campaign_json_raw = _read_text_file(campaign_json_file["id"])
        try:
            campaign_json = json.loads(campaign_json_raw)
        except json.JSONDecodeError as exc:
            parse_error = str(exc)

    return {
        "campaign_json_file": campaign_json_file,
        "campaign_json_raw": campaign_json_raw,
        "campaign_json": campaign_json,
        "campaign_json_parse_error": parse_error,
        "template_files": template_files,
        "prompt_files": prompt_files,
    }


def list_campaigns_drive() -> list[dict[str, Any]]:
    folder = _campaigns_folder()
    campaigns = _list_children(folder["id"], FOLDER_MIME)
    output: list[dict[str, Any]] = []
    for item in campaigns:
        files = _collect_campaign_files(item["id"])
        output.append(
            {
                "campaign_id": item["name"],
                "folder_id": item["id"],
                "modified_time": item.get("modifiedTime"),
                "has_campaign_json": files["campaign_json_file"] is not None,
                "campaign_json_parse_error": files["campaign_json_parse_error"],
                "template_count": len(files["template_files"]),
                "prompt_count": len(files["prompt_files"]),
            }
        )
    return output


def get_campaign_drive(campaign_id: str) -> dict[str, Any]:
    folder = _campaign_folder(campaign_id, create=False)
    if not folder:
        raise FileNotFoundError(f"Campaign folder not found in Drive: {campaign_id}")
    files = _collect_campaign_files(folder["id"])
    validation_errors: list[dict[str, str]] = []
    if files["campaign_json"]:
        validation_errors = validate_campaign_json(
            folder_campaign_id=campaign_id,
            payload=files["campaign_json"],
            template_files={f["name"] for f in files["template_files"]},
            prompt_files={f["name"] for f in files["prompt_files"]},
        )
    return {
        "campaign_id": campaign_id,
        "folder_id": folder["id"],
        "modified_time": folder.get("modifiedTime"),
        "campaign_json_file": files["campaign_json_file"],
        "campaign_json": files["campaign_json"],
        "campaign_json_raw": files["campaign_json_raw"],
        "campaign_json_parse_error": files["campaign_json_parse_error"],
        "templates": files["template_files"],
        "prompts": files["prompt_files"],
        "validation_errors": validation_errors,
    }


def create_campaign_from_template(
    *,
    campaign_id: str,
    template_campaign_id: str = "CAMPAIGN_1",
    campaign_name: str | None = None,
) -> dict[str, Any]:
    existing = _campaign_folder(campaign_id, create=False)
    if existing:
        raise RuntimeError(f"Campaign folder already exists: {campaign_id}")

    template = get_campaign_drive(template_campaign_id)
    if not template["campaign_json"]:
        raise RuntimeError(f"Template campaign has invalid/missing campaign.json: {template_campaign_id}")

    folder = _campaign_folder(campaign_id, create=True)
    templates_folder = _ensure_folder(folder["id"], "templates")
    prompts_folder = _ensure_folder(folder["id"], "prompts")

    payload = dict(template["campaign_json"])
    payload["campaign_id"] = campaign_id
    payload["name"] = campaign_name or campaign_id.replace("_", " ").title()
    _upsert_text_file(folder["id"], "campaign.json", json.dumps(payload, indent=2))

    for f in template["templates"]:
        body = _read_text_file(f["id"])
        _upsert_text_file(templates_folder["id"], f["name"], body)
    for f in template["prompts"]:
        body = _read_text_file(f["id"])
        _upsert_text_file(prompts_folder["id"], f["name"], body)

    return get_campaign_drive(campaign_id)


def write_campaign_json(campaign_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    folder = _campaign_folder(campaign_id, create=False)
    if not folder:
        raise FileNotFoundError(f"Campaign folder not found in Drive: {campaign_id}")
    _upsert_text_file(folder["id"], "campaign.json", json.dumps(payload, indent=2))
    return get_campaign_drive(campaign_id)


def read_template(campaign_id: str, step: str) -> str:
    if step not in ALLOWED_TEMPLATE_STEPS:
        raise ValueError(f"Unsupported step: {step}")
    folder = _campaign_folder(campaign_id, create=False)
    if not folder:
        raise FileNotFoundError(f"Campaign folder not found in Drive: {campaign_id}")
    files = _collect_campaign_files(folder["id"])
    for f in files["template_files"]:
        if f["name"] == f"{step}.txt":
            return _read_text_file(f["id"])
    return ""


def read_prompt(campaign_id: str, key: str) -> str:
    if key not in ALLOWED_PROMPT_KEYS:
        raise ValueError(f"Unsupported prompt key: {key}")
    folder = _campaign_folder(campaign_id, create=False)
    if not folder:
        raise FileNotFoundError(f"Campaign folder not found in Drive: {campaign_id}")
    files = _collect_campaign_files(folder["id"])
    for f in files["prompt_files"]:
        if f["name"] == f"{key}.txt":
            return _read_text_file(f["id"])
    return ""


def write_template(campaign_id: str, step: str, body: str) -> dict[str, Any]:
    if step not in ALLOWED_TEMPLATE_STEPS:
        raise ValueError(f"Unsupported step: {step}")
    folder = _campaign_folder(campaign_id, create=False)
    if not folder:
        raise FileNotFoundError(f"Campaign folder not found in Drive: {campaign_id}")
    templates_folder = _ensure_folder(folder["id"], "templates")
    file_name = f"{step}.txt"
    return _upsert_text_file(templates_folder["id"], file_name, body)


def write_prompt(campaign_id: str, key: str, body: str) -> dict[str, Any]:
    if key not in ALLOWED_PROMPT_KEYS:
        raise ValueError(f"Unsupported prompt key: {key}")
    folder = _campaign_folder(campaign_id, create=False)
    if not folder:
        raise FileNotFoundError(f"Campaign folder not found in Drive: {campaign_id}")
    prompts_folder = _ensure_folder(folder["id"], "prompts")
    file_name = f"{key}.txt"
    return _upsert_text_file(prompts_folder["id"], file_name, body)


def get_drive_file_timestamps(campaign_id: str) -> list[dict[str, Any]]:
    campaign = get_campaign_drive(campaign_id)
    output: list[dict[str, Any]] = []

    if campaign.get("campaign_json_file"):
        item = campaign["campaign_json_file"]
        output.append(
            {
                "file_id": item["id"],
                "file_path": f"campaigns/{campaign_id}/campaign.json",
                "modified_time": item.get("modifiedTime"),
            }
        )
    for f in campaign["templates"]:
        output.append(
            {
                "file_id": f["id"],
                "file_path": f"campaigns/{campaign_id}/templates/{f['name']}",
                "modified_time": f.get("modifiedTime"),
            }
        )
    for f in campaign["prompts"]:
        output.append(
            {
                "file_id": f["id"],
                "file_path": f"campaigns/{campaign_id}/prompts/{f['name']}",
                "modified_time": f.get("modifiedTime"),
            }
        )
    return output
