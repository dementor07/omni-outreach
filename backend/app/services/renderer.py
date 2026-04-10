import re

_ALIASES: list[tuple[str, str]] = [
    ("first_name", "firstname"),
    ("last_name", "lastname"),
]


def render(template: str, lead: dict) -> str:
    """Replace {{key}} placeholders with lead field values. Missing keys → empty string."""
    subs: dict[str, str] = {}
    for key, val in lead.items():
        subs[key] = str(val) if val is not None else ""

    # Populate aliases so both {{first_name}} and {{firstname}} work
    for a, b in _ALIASES:
        if a in subs and b not in subs:
            subs[b] = subs[a]
        elif b in subs and a not in subs:
            subs[a] = subs[b]

    result = template
    for key, val in subs.items():
        result = result.replace(f"{{{{{key}}}}}", val)

    # Clear any remaining unreplaced placeholders
    result = re.sub(r"\{\{[^}]+\}\}", "", result)

    return result.strip()
