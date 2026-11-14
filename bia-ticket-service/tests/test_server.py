"""MCP tools, REST routes, bearer-token auth and snapshots, end to end on the sample data."""

import anyio
import pytest
from starlette.testclient import TestClient

from bia_service.server import build_http_app, build_mcp

TOOLS = {"eta_health", "action_list", "list_tickets", "get_ticket", "team_workload",
         "lead_scorecard", "person_summary", "trend"}


def call(mcp, name, args=None):
    """Call an MCP tool and return its structured result."""
    result = anyio.run(mcp.call_tool, name, args or {})
    assert not result.is_error, result
    return result.structured_content


def test_all_tools_registered_and_read_only(service):
    mcp = build_mcp(service)
    tools = anyio.run(mcp.list_tools)
    assert {t.name for t in tools} == TOOLS
    assert all(t.annotations and t.annotations.read_only_hint for t in tools)


def test_tools_return_engine_numbers(service):
    mcp = build_mcp(service)
    assert call(mcp, "eta_health")["overdue"] == 1
    assert call(mcp, "action_list", {"lead": "two"})["counts"]["stalled"] == 1   # partial lead name
    listed = call(mcp, "list_tickets", {"eta_bucket": "missing_eta"})
    assert [t["number"] for t in listed["tickets"]] == ["T-1001", "T-1008"]
    assert call(mcp, "get_ticket", {"number": "#T-1004"})["flags"] == [
        "stalled", "no_progress_deadline_near", "idle"]
    assert call(mcp, "person_summary", {"person": "Dev Beta"})["open"] == 3


def test_unknown_lead_is_a_clear_error(service):
    """Claude gets a readable message listing the valid leads, not a hidden crash."""
    from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

    with pytest.raises(ToolError, match="Lead One") as caught:
        anyio.run(build_mcp(service).call_tool, "action_list", {"lead": "nobody"})
    assert not isinstance(caught.value, UnexpectedToolError)


def test_snapshot_then_trend(service):
    anyio.run(service.take_snapshot)
    points = anyio.run(service.trend, "overdue", 12)["points"]
    assert points == [{"week_of": "2026-11-16", "snapshot_day": "2026-11-16", "overdue": 1}]


@pytest.fixture
def http(service, monkeypatch):
    # The test client sends Host: testserver; production sets ALLOWED_HOSTS to the real domain.
    monkeypatch.setattr(service, "settings", type(service.settings)(allowed_hosts=("testserver",)))
    with TestClient(build_http_app(service)) as client:
        yield client


AUTH = {"Authorization": "Bearer test-token"}


def test_health_is_public(http):
    assert http.get("/health").json() == {"status": "ok", "source": "file"}


@pytest.mark.parametrize("path", ["/api/eta-health", "/api/dashboard", "/mcp"])
def test_everything_else_needs_the_token(http, path):
    assert http.get(path).status_code == 401
    assert http.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_rest_routes(http):
    assert http.get("/api/eta-health", headers=AUTH).json()["open"] == 8
    assert http.get("/api/action-list?lead=Lead%20One", headers=AUTH).json()["lead"] == "Lead One"
    assert http.get("/api/action-list?lead=nobody", headers=AUTH).status_code == 400
    board = http.get("/api/dashboard", headers=AUTH).json()
    assert set(board) == {"eta_health", "scorecard", "workload", "action_list", "trend"}
    assert http.post("/api/snapshot", headers=AUTH).json()["saved"] == "2026-11-16"


def test_mcp_over_http(http):
    """A real MCP initialize + tools/call round trip through the HTTP door."""
    headers = {**AUTH, "Accept": "application/json, text/event-stream"}
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"}}}
    assert http.post("/mcp", json=init, headers=headers).status_code == 200
    call_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "eta_health", "arguments": {}}}
    body = http.post("/mcp", json=call_req, headers=headers).json()
    assert body["result"]["structuredContent"]["missing_eta"] == 2


def test_http_refuses_to_start_without_token(service, monkeypatch):
    """Fail closed: no token configured means no HTTP server, never an open one."""
    from bia_service.server import Service

    monkeypatch.setenv("SERVICE_TOKEN", "")
    with pytest.raises(ValueError, match="SERVICE_TOKEN"):
        build_http_app(Service())
