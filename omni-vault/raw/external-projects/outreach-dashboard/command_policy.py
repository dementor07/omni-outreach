import re

BLOCK_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\bdel\s+/f\s+/q\b",
    r"\bformat\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bhalt\b",
]

RISKY_PATTERNS = [
    r"\bgit\s+push\b",
    r"\bgit\s+commit\b",
    r"\bapt(-get)?\s+",
    r"\bpip\s+install\b",
    r"\bsystemctl\s+",
    r"\bdocker\s+",
    r"\bkubectl\s+",
    r">\s*[^|]",
    r"\|\s*tee\b",
]

SAFE_PREFIXES = [
    "ls",
    "dir",
    "pwd",
    "whoami",
    "date",
    "echo ",
    "cat ",
    "type ",
    "Get-ChildItem",
    "Get-Content",
    "git status",
    "git log",
    "git diff",
    "python --version",
    "pip --version",
    "journalctl",
    "sudo journalctl",
    "tail ",
    "head ",
    "ps ",
    "df ",
    "du ",
    "free ",
    "uptime",
    "PGPASSWORD=",
]


def classify_command(command: str) -> dict[str, object]:
    cmd = (command or "").strip()
    if not cmd:
        return {
            "risk_level": "blocked",
            "requires_approval": False,
            "allowed": False,
            "reason": "Empty command",
        }

    lowered = cmd.lower()
    for pattern in BLOCK_PATTERNS:
        if re.search(pattern, lowered):
            return {
                "risk_level": "blocked",
                "requires_approval": False,
                "allowed": False,
                "reason": f"Blocked by policy pattern: {pattern}",
            }

    for pattern in RISKY_PATTERNS:
        if re.search(pattern, lowered):
            return {
                "risk_level": "risky",
                "requires_approval": True,
                "allowed": True,
                "reason": f"Potentially mutating command matched: {pattern}",
            }

    for prefix in SAFE_PREFIXES:
        if cmd.startswith(prefix):
            return {
                "risk_level": "safe",
                "requires_approval": False,
                "allowed": True,
                "reason": "Read-only/safe command class",
            }

    return {
        "risk_level": "risky",
        "requires_approval": True,
        "allowed": True,
        "reason": "Unknown command class; approval required",
    }

