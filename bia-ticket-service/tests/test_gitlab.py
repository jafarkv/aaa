"""GitLab code-activity rules, the API client (against a fake GitLab) and the new tools/routes.

Sample MRs (clock frozen at Mon 16 Nov 2026, 10:00 IST):
  !1 open, 5 days old, no comments, idle 4 days -> review queue + stale
  !2 open draft, no ticket number               -> neither queue nor stale; missing ticket
  !3 open, 1 hour old, no comments              -> too new for the queue
  !4 open, has comments, reviewer Dev Beta      -> healthy
  !5 merged in window, cycle 48h                -> Dev Alpha
  !6 merged in window, cycle 6h, no ticket      -> Dev Beta
  !7 merged 6 weeks ago                         -> outside the window
"""

import json

import anyio
import httpx
import pytest
from starlette.testclient import TestClient

from bia_service import gitlab_metrics as gm
from bia_service.config import Settings
from bia_service.gitlab import GitLabClient, GitLabError
from bia_service.server import build_http_app, build_mcp
from conftest import FIXTURES, NOW


@pytest.fixture
def mrs(service):
    """The sample MRs, parsed the same way the service parses them."""
    from datetime import datetime, timezone

    return anyio.run(service.gitlab.get_mrs, datetime(2026, 10, 1, tzinfo=timezone.utc))


def numbers(rows):
    return [r["mr"].split("!")[1] for r in rows]


def test_utc_times_become_local_time(mrs):
    first = next(m for m in mrs if m.ref.endswith("!1"))
    assert str(first.created_at) == "2026-11-11 10:00:00"      # 04:30Z is 10:00 IST


def test_ticket_number_detected_in_title_or_branch(mrs):
    has = {m.ref.split("!")[1]: m.has_ticket for m in mrs}
    assert has == {"1": True, "2": False, "3": True, "4": True, "5": True, "6": False, "7": True}


def test_review_queue(mrs, lead_map):
    rows = gm.review_queue(mrs, lead_map, NOW, wait_hours=24)
    assert numbers(rows) == ["1"]                              # draft, too-new and commented MRs are excluded
    assert rows[0]["age_hours"] == 120.0


def test_stale(mrs, lead_map):
    assert numbers(gm.stale(mrs, lead_map, NOW, idle_days=3)) == ["1"]
    assert numbers(gm.stale(mrs, lead_map, NOW, idle_days=1)) == ["1", "4"]   # !4 untouched for ~1.2 days


def test_activity(mrs, lead_map):
    result = gm.activity(mrs, lead_map, NOW, days=14)
    people = {p["person"]: p for p in result["people"]}
    alpha, beta = people["Dev Alpha"], people["Dev Beta"]
    assert (alpha["merged"], alpha["open"], alpha["median_cycle_hours"], alpha["without_ticket"]) == (1, 2, 48.0, 0)
    assert (beta["merged"], beta["open"], beta["median_cycle_hours"], beta["without_ticket"]) == (1, 1, 6.0, 2)
    assert beta["reviewing"] == 1                              # reviewer on !4
    assert people["Lead One"]["reviewing"] == 1                # reviewer on !1, writes no MRs
    assert people["QA Gamma"]["median_cycle_hours"] is None
    assert result["totals"] == {"merged": 2, "open": 4, "without_ticket": 2}
    assert numbers(result["without_ticket_number"]) == ["2", "6"]


def test_activity_window_and_lead_filter(mrs, lead_map):
    wide = gm.activity(mrs, lead_map, NOW, days=60)
    assert wide["totals"]["merged"] == 3                       # !7 now falls inside the window
    team = gm.activity(mrs, lead_map, NOW, days=14, lead="Lead Two")
    assert [p["person"] for p in team["people"]] == ["QA Gamma"]
    assert team["totals"] == {"merged": 0, "open": 1, "without_ticket": 0}


def test_username_alias_maps_to_lead(mrs, lead_map):
    """A GitLab username can be mapped through the aliases, for people whose display name differs."""
    from bia_service.lead_map import LeadMap

    aliased = LeadMap(teams={"Lead One": ["Alpha Full Name"]}, aliases={"dalpha": "Alpha Full Name"})
    people = {p["person"]: p for p in gm.activity(mrs, aliased, NOW, days=14)["people"]}
    assert people["Alpha Full Name"]["lead"] == "Lead One"


# ---------------------------------------------------------------- GitLab API client

def fake_gitlab(requests):
    """A fake GitLab: opened MRs come on 2 pages, merged on 1; 401 unless the token is right."""
    records = json.loads((FIXTURES / "mrs_sample.json").read_text())
    opened = [r for r in records if r["state"] == "opened"]
    merged = [r for r in records if r["state"] == "merged"]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.headers.get("private-token") != "glpat-test":
            return httpx.Response(401, json={"message": "401 Unauthorized"})
        q = request.url.params
        if q["state"] == "opened":
            page = q["page"]
            chunk = opened[:2] if page == "1" else opened[2:]
            return httpx.Response(200, json=chunk, headers={"x-next-page": "2" if page == "1" else ""})
        return httpx.Response(200, json=merged, headers={"x-next-page": ""})

    return httpx.MockTransport(handler)


def api_settings(monkeypatch, token="glpat-test"):
    for key in ("GITLAB_MRS_FILE",):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GITLAB_TOKEN", token)
    monkeypatch.setenv("GITLAB_GROUP", "web/team")
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com/")
    return Settings()


def test_client_pages_and_sends_token(monkeypatch):
    from datetime import datetime, timezone

    requests = []
    client = GitLabClient(api_settings(monkeypatch), transport=fake_gitlab(requests))
    found = anyio.run(client.get_mrs, datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert len(found) == 7                                     # 4 opened over two pages + 3 merged
    first = requests[0]
    assert str(first.url).startswith("https://gitlab.example.com/api/v4/groups/web%2Fteam/merge_requests")
    assert any(r.url.params.get("updated_after") == "2026-11-01T00:00:00Z" for r in requests)


def test_client_uses_cache(monkeypatch):
    from datetime import datetime, timezone

    requests = []
    client = GitLabClient(api_settings(monkeypatch), transport=fake_gitlab(requests))
    since = datetime(2026, 11, 1, tzinfo=timezone.utc)
    anyio.run(client.get_mrs, since)
    seen = len(requests)
    anyio.run(client.get_mrs, since)
    assert len(requests) == seen                               # second call served from cache


def test_bad_token_gives_a_clear_error_without_leaking_it(monkeypatch):
    from datetime import datetime, timezone

    client = GitLabClient(api_settings(monkeypatch, token="glpat-secret-wrong"), transport=fake_gitlab([]))
    with pytest.raises(GitLabError, match="read_api") as caught:
        anyio.run(client.get_mrs, datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert "glpat-secret-wrong" not in str(caught.value)


def test_not_configured_is_a_clear_error(monkeypatch):
    from datetime import datetime, timezone

    for key in ("GITLAB_TOKEN", "GITLAB_GROUP", "GITLAB_MRS_FILE"):
        monkeypatch.delenv(key, raising=False)
    client = GitLabClient(Settings())
    assert not client.configured
    with pytest.raises(GitLabError, match="GITLAB_TOKEN"):
        anyio.run(client.get_mrs, datetime(2026, 11, 1, tzinfo=timezone.utc))


# ---------------------------------------------------------------- tools and routes

def call(mcp, name, args=None):
    result = anyio.run(mcp.call_tool, name, args or {})
    assert not result.is_error, result
    return result.structured_content


def test_mcp_tools(service):
    mcp = build_mcp(service)
    assert call(mcp, "mr_activity")["totals"] == {"merged": 2, "open": 4, "without_ticket": 2}
    assert call(mcp, "mr_activity", {"lead": "two"})["totals"]["open"] == 1
    assert numbers(call(mcp, "mr_review_queue")["merge_requests"]) == ["1"]
    assert numbers(call(mcp, "mr_stale")["merge_requests"]) == ["1"]


def test_days_beyond_fetch_window_is_a_clear_error(service):
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError, match="between 1 and 30"):
        anyio.run(build_mcp(service).call_tool, "mr_activity", {"days": 90})


def test_rest_routes(service, monkeypatch):
    monkeypatch.setattr(service, "settings", type(service.settings)(allowed_hosts=("testserver",)))
    auth = {"Authorization": "Bearer test-token"}
    with TestClient(build_http_app(service)) as http:
        assert http.get("/api/mr-activity?days=7", headers=auth).json()["window_days"] == 7
        assert http.get("/api/mr-activity?days=abc", headers=auth).status_code == 400
        assert http.get("/api/mr-review-queue", headers=auth).json()["count"] == 1
        assert http.get("/api/mr-stale?lead=Lead%20One", headers=auth).json()["count"] == 1
        assert http.get("/api/mr-stale", headers={}).status_code == 401      # token still required


def test_dashboard_survives_a_gitlab_outage(service, monkeypatch):
    """A GitLab problem must not blank the ticket panels."""
    monkeypatch.setenv("GITLAB_MRS_FILE", "")
    monkeypatch.setenv("GITLAB_TOKEN", "x")
    monkeypatch.setenv("GITLAB_GROUP", "g")
    from bia_service.server import Service

    svc = Service()
    monkeypatch.setattr(svc, "now", lambda: NOW)

    async def broken(*args, **kwargs):
        raise GitLabError("Could not reach GitLab: ConnectError")

    monkeypatch.setattr(svc.gitlab, "get_mrs", broken)
    board = anyio.run(svc.dashboard)
    assert board["code_activity"] == {"error": "Could not reach GitLab: ConnectError"}
    assert board["eta_health"]["open"] == 8
