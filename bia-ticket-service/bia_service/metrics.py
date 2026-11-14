"""Metrics engine: every engineering number is computed here, once.

All functions are pure (tickets + today in, plain dicts out), so the MCP
tools, the REST endpoint and the dashboard can never disagree, and each rule
is easy to unit-test.

Bucket rules match the existing BIA team report skill, so numbers line up
with what the team has seen before.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from .lead_map import UNMAPPED, LeadMap
from .models import Ticket

BUCKETS = ("missing_eta", "overdue", "due_today", "due_this_week", "due_this_month", "future")

# Shown wherever a metric needs data the BIA API doesn't return yet.
NEEDS_DATES = (
    "Needs ticket created/completed/status-change dates from the BIA API "
    "(open question for the BIA team)."
)


@dataclass(frozen=True)
class Rules:
    """Status labels and thresholds that decide what counts as done, active or idle."""

    done_statuses: tuple[str, ...]
    active_statuses: tuple[str, ...]
    idle_days: int = 3

    def is_done(self, t: Ticket) -> bool:
        return t.status.lower() in self.done_statuses

    def is_active(self, t: Ticket) -> bool:
        return t.status.lower() in self.active_statuses


# ---------------------------------------------------------------- classification

def eta_bucket(t: Ticket, today: date) -> str:
    """Place a ticket in exactly one ETA bucket (same rules as the BIA team report)."""
    if t.eta is None:
        return "missing_eta"
    if t.eta < today:
        return "overdue"
    if t.eta == today:
        return "due_today"
    if t.eta <= today + timedelta(days=7):
        return "due_this_week"
    if (t.eta.year, t.eta.month) == (today.year, today.month):
        return "due_this_month"
    return "future"


def flags(t: Ticket, today: date, rules: Rules, now: datetime | None = None) -> list[str]:
    """Problem flags for one open ticket; empty list = nothing to chase."""
    if rules.is_done(t):
        return []
    found: list[str] = []
    bucket = eta_bucket(t, today)
    if bucket in ("missing_eta", "overdue"):
        found.append(bucket)
    if t.is_unassigned:
        found.append("unassigned")
    if rules.is_active(t) and t.progress == 0 and t.worked_mins == 0:
        found.append("stalled")                       # marked active, but nothing done
    if t.progress == 0 and bucket in ("due_today", "due_this_week"):
        found.append("no_progress_deadline_near")
    if now and rules.is_active(t) and t.last_updated and (now - t.last_updated).days >= rules.idle_days:
        found.append("idle")                          # active but untouched for idle_days+
    return found


def open_tickets(tickets: Iterable[Ticket], rules: Rules) -> list[Ticket]:
    return [t for t in tickets if not rules.is_done(t)]


# ---------------------------------------------------------------- filters

def filter_tickets(
    tickets: Iterable[Ticket],
    today: date,
    rules: Rules,
    lead_map: LeadMap,
    *,
    status: str | None = None,
    assignee: str | None = None,
    lead: str | None = None,
    priority: str | None = None,
    bucket: str | None = None,
    include_done: bool = False,
) -> list[Ticket]:
    """Filter tickets; text filters are case-insensitive and 'assignee' matches part of a name."""
    out: list[Ticket] = []
    for t in tickets:
        if not include_done and rules.is_done(t):
            continue
        if status and t.status.lower() != status.lower():
            continue
        if priority and t.priority.lower() != priority.lower():
            continue
        if bucket and eta_bucket(t, today) != bucket:
            continue
        if assignee:
            needle = assignee.lower()
            if needle == "unassigned":
                if not t.is_unassigned:
                    continue
            elif not any(needle in lead_map.canonical(a).lower() for a in t.assignees):
                continue
        if lead and not any(lead_map.lead_of(a) == lead for a in t.assignees):
            continue
        out.append(t)
    return out


# ---------------------------------------------------------------- summaries

def eta_health(tickets: Iterable[Ticket], today: date, rules: Rules) -> dict[str, Any]:
    """Counts per ETA bucket for open tickets, plus totals."""
    tickets = list(tickets)
    open_ = open_tickets(tickets, rules)
    counts = Counter(eta_bucket(t, today) for t in open_)
    with_eta = len(open_) - counts["missing_eta"]
    return {
        "as_of": today.isoformat(),
        "total": len(tickets),
        "open": len(open_),
        "done": len(tickets) - len(open_),
        **{b: counts.get(b, 0) for b in BUCKETS},
        # Share of open tickets that have an ETA: the Phase 1 target is 95%.
        "eta_coverage_pct": round(100 * with_eta / len(open_), 1) if open_ else None,
    }


def breakdown(tickets: Iterable[Ticket]) -> dict[str, dict[str, int]]:
    """Ticket counts by status and by priority (all tickets, done included)."""
    tickets = list(tickets)
    return {
        "by_status": dict(Counter(t.status for t in tickets).most_common()),
        "by_priority": dict(Counter(t.priority for t in tickets).most_common()),
    }


def action_list(tickets: Iterable[Ticket], today: date, rules: Rules, now: datetime | None = None) -> dict[str, Any]:
    """Every open ticket that needs someone to act today, grouped by problem."""
    groups: dict[str, list[dict[str, Any]]] = {
        "missing_eta": [], "overdue": [], "unassigned": [],
        "stalled": [], "no_progress_deadline_near": [], "idle": [],
    }
    for t in open_tickets(tickets, rules):
        for flag in flags(t, today, rules, now):
            groups[flag].append(t.brief())
    # Oldest ETA first inside "overdue", so the worst slip is at the top.
    groups["overdue"].sort(key=lambda b: b["eta"] or "")
    return {"as_of": today.isoformat(), "counts": {k: len(v) for k, v in groups.items()}, **groups}


def workload(tickets: Iterable[Ticket], today: date, rules: Rules, lead_map: LeadMap) -> list[dict[str, Any]]:
    """One row per person. A shared ticket counts once for each of its assignees."""
    rows: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "open": 0, "in_progress": 0, "done": 0, "overdue": 0, "missing_eta": 0,
        "due_this_week": 0, "worked_mins": 0.0, "_est_mins": 0.0, "_worked_on_est": 0.0,
    })
    for t in tickets:
        people = [lead_map.canonical(a) for a in t.assignees] or ["Unassigned"]
        for person in people:
            r = rows[person]
            r["worked_mins"] += t.worked_mins
            if rules.is_done(t):
                r["done"] += 1
                continue
            r["open"] += 1
            r["in_progress"] += int(rules.is_active(t))
            bucket = eta_bucket(t, today)
            r["overdue"] += int(bucket == "overdue")
            r["missing_eta"] += int(bucket == "missing_eta")
            r["due_this_week"] += int(bucket in ("due_today", "due_this_week"))
            if t.estimated_hours > 0:                 # effort % only where an estimate exists
                r["_est_mins"] += t.estimated_hours * 60
                r["_worked_on_est"] += t.worked_mins

    result = []
    for person, r in rows.items():
        est, worked = r.pop("_est_mins"), r.pop("_worked_on_est")
        result.append({
            "person": person,
            "lead": lead_map.lead_of(person) if person != "Unassigned" else None,
            **r,
            "worked_mins": round(r["worked_mins"]),
            # >100% = taking longer than estimated.
            "effort_vs_estimate_pct": round(100 * worked / est) if est else None,
        })
    # Most at-risk people first.
    result.sort(key=lambda r: (-r["overdue"], -r["missing_eta"], -r["open"], r["person"]))
    return result


def lead_scorecard(tickets: Iterable[Ticket], today: date, rules: Rules, lead_map: LeadMap) -> list[dict[str, Any]]:
    """One row per lead's team. A ticket shared across teams counts once per team."""
    tickets = list(tickets)
    teams = lead_map.leads() + [UNMAPPED]
    rows = {lead: {"open": 0, "overdue": 0, "missing_eta": 0, "due_this_week": 0, "people": set()} for lead in teams}

    for t in open_tickets(tickets, rules):
        bucket = eta_bucket(t, today)
        team_set = {lead_map.lead_of(a) for a in t.assignees}
        for lead in team_set:
            r = rows.setdefault(lead, {"open": 0, "overdue": 0, "missing_eta": 0, "due_this_week": 0, "people": set()})
            r["open"] += 1
            r["overdue"] += int(bucket == "overdue")
            r["missing_eta"] += int(bucket == "missing_eta")
            r["due_this_week"] += int(bucket in ("due_today", "due_this_week"))
        for a in t.assignees:
            rows[lead_map.lead_of(a)]["people"].add(lead_map.canonical(a))

    out = []
    for lead, r in rows.items():
        if lead == UNMAPPED and r["open"] == 0:
            continue                                  # hide the Unmapped row when the map is complete
        out.append({
            "lead": lead,
            "people_with_open_tickets": sorted(r["people"]),
            "open": r["open"],
            "overdue": r["overdue"],
            "missing_eta": r["missing_eta"],
            "due_this_week": r["due_this_week"],
            "eta_coverage_pct": round(100 * (r["open"] - r["missing_eta"]) / r["open"], 1) if r["open"] else None,
            # Not computable from today's API fields; kept in the shape so the dashboard has a slot.
            "eta_hit_rate_pct": None,
            "median_cycle_time_days": None,
        })
    return out


def person_summary(tickets: Iterable[Ticket], today: date, rules: Rules, lead_map: LeadMap, person: str,
                   now: datetime | None = None) -> dict[str, Any]:
    """One person's open tickets and what's at risk this week."""
    mine = filter_tickets(tickets, today, rules, lead_map, assignee=person)
    at_risk = [
        {**t.brief(), "flags": f}
        for t in mine
        if (f := flags(t, today, rules, now)) or eta_bucket(t, today) in ("due_today", "due_this_week")
    ]
    return {
        "person": person,
        "lead": lead_map.lead_of(person),
        "open": len(mine),
        "eta_health": {b: sum(eta_bucket(t, today) == b for t in mine) for b in BUCKETS},
        "at_risk_this_week": at_risk,
        "all_open": [t.brief() for t in mine],
    }
