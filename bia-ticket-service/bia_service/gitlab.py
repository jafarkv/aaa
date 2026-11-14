"""GitLab client: reads merge requests (MRs) for one GitLab group, read-only.

Why merge requests and not commits: MRs show the whole life of a change
(opened, reviewed, merged), carry a title and branch name that can hold the
BIA ticket number, and can't be inflated the way commit counts can.

Needs a GitLab token with the `read_api` scope. Nothing here writes to GitLab.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from .client import BiaError, _extract_records
from .config import Settings

import json
from pathlib import Path

MAX_PAGES = 10          # 10 pages x 100 MRs; stops a runaway group from hammering GitLab


class GitLabError(BiaError):
    """Raised when MRs can't be loaded; the message is safe to show to a user."""


def parse_gl_time(value: Any, tz: tzinfo) -> datetime | None:
    """GitLab sends UTC timestamps like 2026-11-10T08:30:00.000Z; convert to naive local time."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(tz).replace(tzinfo=None)


@dataclass(frozen=True)
class MergeRequest:
    """One GitLab merge request, normalised."""

    ref: str                      # e.g. "web/shop!42"
    title: str
    source_branch: str
    author: str
    author_username: str
    state: str                    # opened | merged | closed
    draft: bool
    created_at: datetime | None
    updated_at: datetime | None
    merged_at: datetime | None
    reviewers: tuple[str, ...]
    user_notes_count: int         # human comments (system notes excluded by GitLab)
    web_url: str
    has_ticket: bool              # title or branch carries a ticket number

    @classmethod
    def from_api(cls, record: dict[str, Any], tz: tzinfo, ticket_re: "re.Pattern[str]") -> "MergeRequest":
        title = str(record.get("title") or "").strip()
        branch = str(record.get("source_branch") or "").strip()
        author = record.get("author") or {}
        iid = record.get("iid", "")
        return cls(
            ref=str((record.get("references") or {}).get("full") or f"!{iid}"),
            title=title,
            source_branch=branch,
            author=str(author.get("name") or author.get("username") or "Unknown").strip(),
            author_username=str(author.get("username") or "").strip(),
            state=str(record.get("state") or "opened").lower(),
            draft=bool(record.get("draft") or record.get("work_in_progress") or title.lower().startswith("draft:")),
            created_at=parse_gl_time(record.get("created_at"), tz),
            updated_at=parse_gl_time(record.get("updated_at"), tz),
            merged_at=parse_gl_time(record.get("merged_at"), tz),
            reviewers=tuple(str(r.get("name") or r.get("username")) for r in (record.get("reviewers") or []) if r),
            user_notes_count=int(record.get("user_notes_count") or 0),
            web_url=str(record.get("web_url") or ""),
            has_ticket=bool(ticket_re.search(f"{title} {branch}")),
        )


class GitLabClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self._transport = transport                 # tests inject a fake transport
        self._tz = ZoneInfo(settings.timezone)
        self._mrs: list[MergeRequest] = []
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        s = self.settings
        return bool(s.gitlab_mrs_file or (s.gitlab_token and s.gitlab_group))

    async def get_mrs(self, since_utc: datetime, refresh: bool = False) -> list[MergeRequest]:
        """All open MRs, plus MRs merged since `since_utc`. Cached for CACHE_SECONDS."""
        if not self.configured:
            raise GitLabError("GitLab isn't configured: set GITLAB_TOKEN and GITLAB_GROUP in .env.")
        try:
            ticket_re = re.compile(self.settings.ticket_regex)
        except re.error as exc:
            raise GitLabError(f"TICKET_REGEX is not a valid regular expression: {exc}") from exc

        async with self._lock:
            fresh = (time.monotonic() - self._fetched_at) < self.settings.cache_seconds
            if self._mrs and fresh and not refresh:
                return self._mrs
            if self.settings.gitlab_mrs_file:       # offline mode: raw GitLab records from a JSON file
                records = self._load_file(Path(self.settings.gitlab_mrs_file))
            else:
                records = await self._fetch(since_utc)
            self._mrs = [MergeRequest.from_api(r, self._tz, ticket_re) for r in records if isinstance(r, dict)]
            self._fetched_at = time.monotonic()
            return self._mrs

    @staticmethod
    def _load_file(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            raise GitLabError(f"GitLab MR file not found: {path}")
        return _extract_records(json.loads(path.read_text(encoding="utf-8")))

    async def _fetch(self, since_utc: datetime) -> list[dict[str, Any]]:
        s = self.settings
        # Group endpoint covers every project in the group and its subgroups.
        base = f"{s.gitlab_url}/api/v4/groups/{quote(s.gitlab_group, safe='')}/merge_requests"
        since = since_utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            async with httpx.AsyncClient(
                timeout=s.request_timeout, transport=self._transport, headers={"PRIVATE-TOKEN": s.gitlab_token}
            ) as http:
                opened = await self._pages(http, base, {"state": "opened", "scope": "all"})
                merged = await self._pages(http, base, {"state": "merged", "scope": "all", "updated_after": since})
        except httpx.HTTPError as exc:
            # Never include request headers (the token) in the message.
            raise GitLabError(f"Could not reach GitLab: {type(exc).__name__}") from exc
        return opened + merged

    async def _pages(self, http: httpx.AsyncClient, url: str, params: dict[str, str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page = "1"
        for _ in range(MAX_PAGES):
            response = await http.get(url, params={**params, "per_page": "100", "page": page})
            if response.status_code in (401, 403):
                raise GitLabError("GitLab rejected the token (check GITLAB_TOKEN; it needs the read_api scope).")
            if response.status_code == 404:
                raise GitLabError("GitLab group not found, or the token can't see it (check GITLAB_GROUP).")
            if response.status_code >= 400:
                raise GitLabError(f"GitLab returned HTTP {response.status_code}.")
            try:
                out.extend(_extract_records(response.json()))
            except ValueError as exc:
                raise GitLabError("GitLab returned a non-JSON response.") from exc
            page = response.headers.get("x-next-page", "")
            if not page:                              # GitLab sends an empty header on the last page
                break
        return out
