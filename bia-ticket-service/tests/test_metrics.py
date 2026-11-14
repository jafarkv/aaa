"""Metric rules, checked against the 10 sample tickets (8 open, 2 done)."""

from datetime import date

from bia_service import metrics
from bia_service.models import Ticket, parse_date
from conftest import NOW, TODAY


def by_number(tickets, number):
    return next(t for t in tickets if t.number == number)


def test_parse_date_handles_bia_empty_values():
    assert parse_date(None) is None
    assert parse_date("") is None
    assert parse_date("0000-00-00") is None
    assert parse_date("not a date") is None
    assert parse_date("2026-11-20 00:00:00") == date(2026, 11, 20)


def test_assignee_falls_back_to_summary_string():
    t = Ticket.from_api({"ticket_number": "X", "assignees": [], "assignees_summary": "A One, B Two"})
    assert t.assignees == ("A One", "B Two")


def test_eta_buckets(tickets):
    expected = {
        "T-1001": "missing_eta", "T-1002": "overdue", "T-1003": "due_today",
        "T-1004": "due_this_week", "T-1005": "due_this_month", "T-1006": "future",
        "T-1008": "missing_eta", "T-1010": "due_this_week",
    }
    for number, bucket in expected.items():
        assert metrics.eta_bucket(by_number(tickets, number), TODAY) == bucket, number


def test_eta_health_counts_open_tickets_only(tickets, rules):
    h = metrics.eta_health(tickets, TODAY, rules)
    assert (h["total"], h["open"], h["done"]) == (10, 8, 2)
    assert h["missing_eta"] == 2
    assert h["overdue"] == 1                      # T-1009 is overdue by date but closed, so not counted
    assert h["due_today"] == 1
    assert h["due_this_week"] == 2
    assert h["due_this_month"] == 1
    assert h["future"] == 1
    assert h["eta_coverage_pct"] == 75.0          # 6 of 8 open tickets have an ETA


def test_action_list(tickets, rules):
    a = metrics.action_list(tickets, TODAY, rules, NOW)
    assert a["counts"] == {
        "missing_eta": 2, "overdue": 1, "unassigned": 1,
        "stalled": 1, "no_progress_deadline_near": 2, "idle": 1,
    }
    assert a["stalled"][0]["number"] == "T-1004"
    assert a["idle"][0]["number"] == "T-1004"     # active, last touched 6 days ago
    assert a["unassigned"][0]["assignees"] == ["UNASSIGNED"]


def test_lead_scorecard_counts_shared_ticket_once_per_team(tickets, rules, lead_map):
    rows = {r["lead"]: r for r in metrics.lead_scorecard(tickets, TODAY, rules, lead_map)}
    one, two = rows["Lead One"], rows["Lead Two"]
    # T-1002 has two Lead One people but counts once for the team.
    assert (one["open"], one["overdue"], one["missing_eta"], one["due_this_week"]) == (5, 1, 2, 1)
    assert one["eta_coverage_pct"] == 60.0
    # T-1010 is assigned to the alias "QA G", which resolves to QA Gamma.
    assert (two["open"], two["overdue"], two["missing_eta"], two["due_this_week"]) == (2, 0, 0, 2)
    assert "Unmapped" not in rows                 # every assignee is mapped
    assert one["eta_hit_rate_pct"] is None        # needs dates the API doesn't return yet


def test_workload_effort_and_alias(tickets, rules, lead_map):
    rows = {r["person"]: r for r in metrics.workload(tickets, TODAY, rules, lead_map)}
    alpha = rows["Dev Alpha"]
    assert (alpha["open"], alpha["done"], alpha["overdue"], alpha["missing_eta"]) == (2, 1, 1, 1)
    assert alpha["effort_vs_estimate_pct"] == 88  # 420 worked / 480 estimated minutes
    assert alpha["lead"] == "Lead One"
    assert "QA G" not in rows and rows["QA Gamma"]["open"] == 2
    assert rows["Unassigned"]["open"] == 1


def test_unmapped_people_are_visible(tickets, rules):
    from bia_service.lead_map import LeadMap

    rows = {r["lead"]: r for r in metrics.lead_scorecard(tickets, TODAY, rules, LeadMap())}
    assert rows["Unmapped"]["open"] == 7          # every assigned open ticket, until the map is filled


def test_filters(tickets, rules, lead_map):
    def numbers(**kw):
        return sorted(t.number for t in metrics.filter_tickets(tickets, TODAY, rules, lead_map, **kw))

    assert numbers(assignee="beta") == ["T-1002", "T-1003", "T-1008"]
    assert numbers(assignee="unassigned") == ["T-1006"]
    assert numbers(lead="Lead Two") == ["T-1004", "T-1010"]
    assert numbers(bucket="overdue", include_done=True) == ["T-1002", "T-1009"]
    assert numbers(priority="high") == ["T-1001", "T-1006", "T-1010"]
