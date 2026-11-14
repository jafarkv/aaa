"""Daily snapshots in SQLite, so the dashboard can show a 12-week trend.

The BIA API only returns the current state of tickets, so history has to be
recorded by us: one row per day (re-running the same day overwrites it).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    day        TEXT PRIMARY KEY,   -- YYYY-MM-DD in the service time zone
    eta_health TEXT NOT NULL,      -- JSON from metrics.eta_health
    scorecard  TEXT NOT NULL       -- JSON from metrics.lead_scorecard
)
"""

# Metrics the trend tool can chart, all read from the stored eta_health JSON.
TREND_METRICS = ("open", "overdue", "missing_eta", "due_this_week", "eta_coverage_pct")


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(_SCHEMA)
    return conn


def save(db_path: Path, day: date, eta_health: dict[str, Any], scorecard: list[dict[str, Any]]) -> None:
    """Store (or replace) the snapshot for one day."""
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO snapshots (day, eta_health, scorecard) VALUES (?, ?, ?)",
            (day.isoformat(), json.dumps(eta_health), json.dumps(scorecard)),
        )


def trend(db_path: Path, metric: str, weeks: int, today: date) -> list[dict[str, Any]]:
    """One value per week (the last snapshot in each week), oldest first."""
    if metric not in TREND_METRICS:
        raise ValueError(f"Unknown metric '{metric}'. Choose one of: {', '.join(TREND_METRICS)}")
    since = today - timedelta(weeks=weeks)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT day, eta_health FROM snapshots WHERE day > ? ORDER BY day", (since.isoformat(),)
        ).fetchall()

    by_week: dict[str, dict[str, Any]] = {}
    for day_text, health_json in rows:
        day = date.fromisoformat(day_text)
        week_start = day - timedelta(days=day.weekday())          # Monday of that week
        # Later days overwrite earlier ones, so each week keeps its last snapshot.
        by_week[week_start.isoformat()] = {
            "week_of": week_start.isoformat(),
            "snapshot_day": day_text,
            metric: json.loads(health_json).get(metric),
        }
    return list(by_week.values())
