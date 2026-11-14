"""Lead map: which person belongs to which lead's team.

BIA only knows assignees, not reporting lines, so the scorecard needs this
file to group people under leads. Leads keep config/lead_map.json up to date.

File format (see config/lead_map.example.json):
    {
      "teams":   {"Lead Name": ["Lead Name", "Member One", "Member Two"]},
      "aliases": {"Short Name": "Full Name"}      # optional: BIA spelling -> map spelling
    }
"""

from __future__ import annotations

import json
from pathlib import Path

UNMAPPED = "Unmapped"


class LeadMap:
    def __init__(self, teams: dict[str, list[str]] | None = None, aliases: dict[str, str] | None = None):
        self.teams = teams or {}
        # Case-insensitive lookups: person -> lead, alias -> canonical name.
        self._aliases = {k.strip().lower(): v.strip() for k, v in (aliases or {}).items()}
        self._lead_of: dict[str, str] = {}
        for lead, members in self.teams.items():
            self._lead_of[lead.strip().lower()] = lead          # a lead belongs to their own team
            for member in members:
                self._lead_of[member.strip().lower()] = lead

    @classmethod
    def load(cls, path: Path) -> "LeadMap":
        """Load from JSON; a missing file gives an empty map (everyone shows as Unmapped)."""
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(teams=data.get("teams", {}), aliases=data.get("aliases", {}))

    def canonical(self, person: str) -> str:
        """Resolve an alias (e.g. BIA's short spelling) to the name used in the map."""
        return self._aliases.get(person.strip().lower(), person.strip())

    def lead_of(self, person: str) -> str:
        """The person's lead, or 'Unmapped' so gaps in the map are visible, not hidden."""
        return self._lead_of.get(self.canonical(person).lower(), UNMAPPED)

    def leads(self) -> list[str]:
        return list(self.teams.keys())

    def resolve_lead(self, name: str) -> str | None:
        """Match a lead by full or partial name ('asha' -> 'Asha Menon'); None if no single match."""
        needle = name.strip().lower()
        exact = [lead for lead in self.teams if lead.lower() == needle]
        if exact:
            return exact[0]
        partial = [lead for lead in self.teams if needle in lead.lower()]
        return partial[0] if len(partial) == 1 else None
