"""Code-activity rules on merge requests (pure functions, like metrics.py).

What these measure, and what they deliberately don't:
  * review wait, stale work, cycle time and missing ticket numbers  -> flow problems a lead can fix
  * NOT commit counts or lines of code -> easy to inflate, and meaningless with AI-written code
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median
from typing import Any, Iterable

from .gitlab import MergeRequest
from .lead_map import LeadMap


def author_name(mr: MergeRequest, lead_map: LeadMap) -> str:
    """Name used in the lead map: GitLab username alias first, then display name."""
    by_username = lead_map.canonical(mr.author_username) if mr.author_username else ""
    if by_username and by_username != mr.author_username:
        return by_username
    return lead_map.canonical(mr.author)


def hours_between(start: datetime, end: datetime) -> float:
    return round((end - start).total_seconds() / 3600, 1)


def brief(mr: MergeRequest, lead_map: LeadMap, now: datetime) -> dict[str, Any]:
    """Short form used in tool and API responses."""
    return {
        "mr": mr.ref,
        "title": mr.title,
        "author": author_name(mr, lead_map),
        "state": mr.state,
        "draft": mr.draft,
        "reviewers": list(mr.reviewers),
        "age_hours": hours_between(mr.created_at, now) if mr.created_at else None,
        "idle_hours": hours_between(mr.updated_at, now) if mr.updated_at else None,
        "has_ticket_number": mr.has_ticket,
        "url": mr.web_url,
    }


def by_lead(mrs: Iterable[MergeRequest], lead_map: LeadMap, lead: str | None) -> list[MergeRequest]:
    """Keep MRs written by that lead's team; no lead = keep all."""
    mrs = list(mrs)
    if not lead:
        return mrs
    return [m for m in mrs if lead_map.lead_of(author_name(m, lead_map)) == lead]


def review_queue(mrs: Iterable[MergeRequest], lead_map: LeadMap, now: datetime, wait_hours: int) -> list[dict[str, Any]]:
    """Open, non-draft MRs with no human comment yet after `wait_hours`: nobody has looked at them."""
    rows = [
        brief(m, lead_map, now)
        for m in mrs
        if m.state == "opened" and not m.draft and m.user_notes_count == 0
        and m.created_at and hours_between(m.created_at, now) >= wait_hours
    ]
    rows.sort(key=lambda r: -r["age_hours"])           # longest wait first
    return rows


def stale(mrs: Iterable[MergeRequest], lead_map: LeadMap, now: datetime, idle_days: int) -> list[dict[str, Any]]:
    """Open MRs (drafts included) with no activity for `idle_days` or more."""
    rows = [
        brief(m, lead_map, now)
        for m in mrs
        if m.state == "opened" and m.updated_at and (now - m.updated_at).days >= idle_days
    ]
    rows.sort(key=lambda r: -r["idle_hours"])
    return rows


def activity(mrs: Iterable[MergeRequest], lead_map: LeadMap, now: datetime, days: int, lead: str | None = None) -> dict[str, Any]:
    """Per person: MRs merged, median cycle time, open MRs, reviews pending, MRs missing a ticket number."""
    mrs = list(mrs)
    start = now - timedelta(days=days)
    rows: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "merged": 0, "open": 0, "reviewing": 0, "without_ticket": 0, "_cycles": [],
    })
    missing: list[MergeRequest] = []

    for m in mrs:
        person = author_name(m, lead_map)
        merged_in_window = m.state == "merged" and m.merged_at is not None and m.merged_at >= start
        if merged_in_window:
            rows[person]["merged"] += 1
            if m.created_at:
                rows[person]["_cycles"].append(hours_between(m.created_at, m.merged_at))
        elif m.state == "opened":
            rows[person]["open"] += 1
            for reviewer in m.reviewers:                # open MRs waiting on this person's review
                rows[lead_map.canonical(reviewer)]["reviewing"] += 1
        if (merged_in_window or m.state == "opened") and not m.has_ticket:
            rows[person]["without_ticket"] += 1
            missing.append(m)

    people = []
    for person, r in rows.items():
        cycles = r.pop("_cycles")
        people.append({
            "person": person,
            "lead": lead_map.lead_of(person),
            **r,
            # Hours from MR opened to merged. Long = oversized MR or a stuck review.
            "median_cycle_hours": round(median(cycles), 1) if cycles else None,
        })
    if lead:
        people = [p for p in people if p["lead"] == lead]
        missing = by_lead(missing, lead_map, lead)
    people.sort(key=lambda p: (-p["merged"], p["person"]))

    return {
        "window_days": days,
        "totals": {
            "merged": sum(p["merged"] for p in people),
            "open": sum(p["open"] for p in people),
            "without_ticket": sum(p["without_ticket"] for p in people),
        },
        "people": people,
        "without_ticket_number": [brief(m, lead_map, now) for m in missing],
    }
