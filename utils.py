import os
from datetime import date
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)


def get_life_os_root() -> Path:
    root = os.getenv("LIFE_OS_ROOT")
    if not root:
        raise EnvironmentError("LIFE_OS_ROOT is not set in .env")
    return Path(root)


def read_file(relative_path: str) -> str:
    return (get_life_os_root() / relative_path).read_text(encoding="utf-8")


def write_file(relative_path: str, content: str) -> None:
    path = get_life_os_root() / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def append_to_file(relative_path: str, content: str) -> None:
    path = get_life_os_root() / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(content)


def get_domain_path(domain_name: str) -> Path:
    """Return the path to a domain folder under domains/.

    All nine domain folders moved from the Life-OS root into domains/ on 2026-05-28.
    Always use this helper rather than constructing domain paths manually.
    """
    return get_life_os_root() / "domains" / domain_name


def read_thresholds() -> dict:
    return yaml.safe_load(read_file("thresholds.yaml"))


def today_log_path() -> Path:
    return get_life_os_root() / "daily" / "logs" / f"{date.today().isoformat()}.md"


def append_log_entry(entry: dict) -> None:
    lines = [f"## {entry.get('date', date.today().isoformat())}", ""]
    for field in ("duration", "type", "covered", "outcome", "notes", "waiting"):
        if entry.get(field):
            lines.append(f"- **{field}:** {entry[field]}")
    lines.append("")
    append_to_file(f"daily/logs/{date.today().isoformat()}.md", "\n".join(lines))
