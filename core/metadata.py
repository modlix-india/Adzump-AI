import re
from pathlib import Path

SERVICE_NAME = "ds-service"
APP_TITLE = "Adzump AI: Automate, Optimize, Analyze"


def _read_version() -> str:
    changelog = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
    if changelog.exists():
        match = re.search(r"##\s*\[(.+?)\]", changelog.read_text())
        if match:
            return match.group(1)
    return "unknown"


VERSION = _read_version()