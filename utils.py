import os
from datetime import date, datetime
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


def update_threshold(domain: str, field: str, value: float) -> None:
    """Update a single numeric field in thresholds.yaml, preserving comments."""
    content = read_file("thresholds.yaml")
    lines = content.splitlines()
    in_domain = False
    result = []
    updated = False
    for line in lines:
        stripped = line.strip()
        if not line.startswith(" ") and stripped == f"{domain}:":
            in_domain = True
        elif in_domain and line and not line.startswith(" ") and not line.startswith("#"):
            in_domain = False
        if in_domain and stripped.startswith(f"{field}:"):
            indent = len(line) - len(line.lstrip())
            result.append(" " * indent + f"{field}: {value}")
            updated = True
        else:
            result.append(line)
    if not updated:
        raise ValueError(f"Field '{domain}.{field}' not found in thresholds.yaml")
    write_file("thresholds.yaml", "\n".join(result) + "\n")


def append_inbox(task_text: str) -> None:
    """Append a task line to inbox.md."""
    append_to_file("inbox.md", f"- [ ] {task_text}\n")


def write_ingest_note(domain: str, body: str) -> str:
    """Write a bot-generated note. Returns the relative path written.

    The literal token ``dev`` routes to ``ingest/dev/`` — the Dev-Note Bin
    a Code session drains into ``dev/TODO.md``. Everything else goes to
    ``ingest/``, which Cowork drains for life notes. The ``domain:`` field
    still carries the literal tag (`dev` or the domain name or blank).
    """
    now = datetime.now()
    filename = now.strftime("%Y-%m-%d-%H-%M") + ".md"
    domain_line = domain if domain else ""
    folder = "ingest/dev" if domain == "dev" else "ingest"
    content = (
        f"source: telegram\n"
        f"date: {now.strftime('%Y-%m-%d')}\n"
        f"time: {now.strftime('%H:%M')}\n"
        f"domain: {domain_line}\n"
        f"---\n"
        f"{body}\n"
    )
    rel = f"{folder}/{filename}"
    write_file(rel, content)
    return rel


def append_log_entry(entry: dict) -> None:
    lines = [f"## {entry.get('date', date.today().isoformat())}", ""]
    for field in ("duration", "type", "covered", "outcome", "task", "domain", "notes", "waiting"):
        if entry.get(field):
            lines.append(f"- **{field}:** {entry[field]}")
    lines.append("")
    append_to_file(f"daily/logs/{date.today().isoformat()}.md", "\n".join(lines))
