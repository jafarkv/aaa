"""Ticket model: turns one raw BIA API record into a clean, typed Ticket.

The BIA API is loose about types (ETA can be null, "", or "0000-00-00";
numbers can arrive as strings), so every field is normalised here once and
the rest of the code can trust what it gets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

# Values BIA uses to mean "no ETA set".
_EMPTY_DATES = {"", "0000-00-00", "0000-00-00 00:00:00"}


def parse_date(value: Any) -> date | None:
    """Parse 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS' into a date; anything empty or invalid -> None."""
    if value is None:
        return None
    text = str(value).strip()
    if text in _EMPTY_DATES:
        return None
    try:
        # Only the date part matters for ETA comparisons.
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_datetime(value: Any) -> datetime | None:
    """Parse a BIA timestamp; returns None when missing or malformed."""
    if value is None:
        return None
    text = str(value).strip()
    if text in _EMPTY_DATES:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _to_float(value: Any) -> float:
    """BIA sometimes sends numbers as strings; treat anything unparseable as 0."""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True)
class Ticket:
    """One BIA ticket, normalised."""

    ticket_id: str
    number: str
    name: str
    status: str
    priority: str
    progress: float              # 0-100
    eta: date | None             # None = no ETA set
    assignees: tuple[str, ...]   # empty = unassigned
    worked_mins: float
    estimated_hours: float
    type_value: str
    requester: str
    last_updated: datetime | None
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def is_unassigned(self) -> bool:
        return not self.assignees

    @classmethod
    def from_api(cls, record: dict[str, Any]) -> "Ticket":
        """Build a Ticket from one record of the get_tickets_statuses response."""
        # Assignees arrive as [{id, name}, ...]; fall back to the summary string.
        names: list[str] = []
        for person in record.get("assignees") or []:
            name = (person.get("name") if isinstance(person, dict) else str(person)) or ""
            if name.strip():
                names.append(name.strip())
        if not names and record.get("assignees_summary"):
            names = [n.strip() for n in str(record["assignees_summary"]).split(",") if n.strip()]

        return cls(
            ticket_id=str(record.get("ticket_id", "")),
            number=str(record.get("ticket_number") or record.get("ticket_id", "")),
            name=str(record.get("ticket_name") or "").strip(),
            status=str(record.get("ticket_status") or "Unknown").strip(),
            priority=str(record.get("priority_name") or "None").strip(),
            progress=_to_float(record.get("progress")),
            eta=parse_date(record.get("agent_eta")),
            assignees=tuple(names),
            worked_mins=_to_float(record.get("total_worked_mins")),
            estimated_hours=_to_float(record.get("working_hours")),
            type_value=str(record.get("type_value") or "").strip(),
            requester=str(record.get("requester_name") or "").strip(),
            last_updated=parse_datetime(record.get("last_updated")),
            raw=record,
        )

    def brief(self) -> dict[str, Any]:
        """Short form used in tool and API responses."""
        return {
            "number": self.number,
            "name": self.name,
            "status": self.status,
            "priority": self.priority,
            "eta": self.eta.isoformat() if self.eta else None,
            "progress": self.progress,
            "assignees": list(self.assignees) or ["UNASSIGNED"],
        }
