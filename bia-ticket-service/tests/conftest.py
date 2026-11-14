"""Shared test setup: sample tickets, a sample lead map and a fixed 'today' (Mon 16 Nov 2026, 10:00 IST)."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from bia_service.lead_map import LeadMap
from bia_service.metrics import Rules
from bia_service.models import Ticket

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 16)
NOW = datetime(2026, 11, 16, 10, 0)


@pytest.fixture
def tickets() -> list[Ticket]:
    records = json.loads((FIXTURES / "tickets_sample.json").read_text(encoding="utf-8"))
    return [Ticket.from_api(r) for r in records]


@pytest.fixture
def lead_map() -> LeadMap:
    return LeadMap.load(FIXTURES / "lead_map_sample.json")


@pytest.fixture
def rules() -> Rules:
    return Rules(
        done_statuses=("completed", "closed", "resolved", "done", "cancelled"),
        active_statuses=("in progress", "working", "started", "in-progress"),
        idle_days=3,
    )


@pytest.fixture
def service(monkeypatch, tmp_path):
    """A Service reading the sample files, with the clock frozen at NOW."""
    monkeypatch.setenv("BIA_TICKETS_FILE", str(FIXTURES / "tickets_sample.json"))
    monkeypatch.setenv("LEAD_MAP_FILE", str(FIXTURES / "lead_map_sample.json"))
    monkeypatch.setenv("SNAPSHOT_DB", str(tmp_path / "snapshots.db"))
    monkeypatch.setenv("GITLAB_MRS_FILE", str(FIXTURES / "mrs_sample.json"))
    monkeypatch.setenv("SERVICE_TOKEN", "test-token")
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)

    from bia_service.server import Service

    svc = Service()
    monkeypatch.setattr(svc, "now", lambda: NOW)
    return svc
