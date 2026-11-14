"""Settings, read once from environment variables (or a local .env file).

Nothing sensitive is hard-coded: the BIA URL, the API key and the service
token all come from the environment, so the code can live in any repo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Project root = the folder that holds this package (bia-ticket-service/).
ROOT = Path(__file__).resolve().parent.parent

# Load bia-ticket-service/.env if present; real environment variables win.
load_dotenv(ROOT / ".env", override=False)


def _list(name: str, default: str) -> tuple[str, ...]:
    """Comma-separated env var -> lower-cased tuple (used for status matching)."""
    raw = os.getenv(name, default)
    return tuple(item.strip().lower() for item in raw.split(",") if item.strip())


def _path(name: str, default: str) -> Path:
    """Env var path; relative paths are resolved from the project root."""
    value = Path(os.getenv(name, default))
    return value if value.is_absolute() else ROOT / value


@dataclass(frozen=True)
class Settings:
    # Where tickets come from: the live API, or a JSON file for offline testing.
    api_url: str = field(default_factory=lambda: os.getenv("BIA_API_URL", "").strip())
    api_key: str = field(default_factory=lambda: os.getenv("BIA_API_KEY", "").strip())
    tickets_file: str = field(default_factory=lambda: os.getenv("BIA_TICKETS_FILE", "").strip())
    request_timeout: float = field(default_factory=lambda: float(os.getenv("BIA_TIMEOUT_SECONDS", "30")))
    # Optional BIA-side filter, e.g. a tag that marks Engineering / Server tickets.
    filter_tag: str = field(default_factory=lambda: os.getenv("BIA_FILTER_TAG", "").strip())

    # How long a fetched ticket list is reused before calling BIA again.
    cache_seconds: int = field(default_factory=lambda: int(os.getenv("CACHE_SECONDS", "900")))

    # "Today" is judged in this time zone (IST by default).
    timezone: str = field(default_factory=lambda: os.getenv("TIMEZONE", "Asia/Kolkata"))

    # Status labels, matched case-insensitively. Adjust to BIA's real labels.
    done_statuses: tuple[str, ...] = field(
        default_factory=lambda: _list("DONE_STATUSES", "completed,closed,resolved,done,cancelled")
    )
    active_statuses: tuple[str, ...] = field(
        default_factory=lambda: _list("ACTIVE_STATUSES", "in progress,working,started,in-progress")
    )

    # An active ticket with no update for this many days is flagged as idle.
    idle_days: int = field(default_factory=lambda: int(os.getenv("IDLE_DAYS", "3")))

    # --- GitLab (optional): code activity from merge requests, read-only ---
    gitlab_url: str = field(default_factory=lambda: os.getenv("GITLAB_URL", "https://gitlab.com").strip().rstrip("/"))
    gitlab_token: str = field(default_factory=lambda: os.getenv("GITLAB_TOKEN", "").strip())   # needs read_api scope
    gitlab_group: str = field(default_factory=lambda: os.getenv("GITLAB_GROUP", "").strip())   # group id or path
    gitlab_mrs_file: str = field(default_factory=lambda: os.getenv("GITLAB_MRS_FILE", "").strip())  # offline testing
    # How a ticket number looks in an MR title or branch name. Must match BIA's real format.
    ticket_regex: str = field(default_factory=lambda: os.getenv("TICKET_REGEX", r"(?i)(?:\b[a-z]{1,5}-\d+\b|#\d+)"))
    review_wait_hours: int = field(default_factory=lambda: int(os.getenv("REVIEW_WAIT_HOURS", "24")))
    mr_days: int = field(default_factory=lambda: int(os.getenv("MR_DAYS", "14")))               # default activity window
    mr_fetch_days: int = field(default_factory=lambda: int(os.getenv("MR_FETCH_DAYS", "30")))   # longest window allowed

    lead_map_file: Path = field(default_factory=lambda: _path("LEAD_MAP_FILE", "config/lead_map.json"))
    snapshot_db: Path = field(default_factory=lambda: _path("SNAPSHOT_DB", "data/snapshots.db"))

    # HTTP mode only: shared bearer token required on every request except /health.
    service_token: str = field(default_factory=lambda: os.getenv("SERVICE_TOKEN", "").strip())
    # HTTP mode only: Host headers accepted (DNS-rebinding protection), e.g. "tickets-mcp.example.com".
    allowed_hosts: tuple[str, ...] = field(
        default_factory=lambda: tuple(h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip())
    )


def get_settings() -> Settings:
    """Fresh settings each call, so tests can change env vars."""
    return Settings()
