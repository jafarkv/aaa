"""The two doors to the metrics engine:

  * MCP tools  -> Claude (the PM and leads ask questions in plain English)
  * REST /api  -> Make.com automations and the dashboard

Both call the same Service methods, so every consumer sees the same numbers.
Version 1 is read-only: nothing here can change a ticket in BIA.
"""

from __future__ import annotations

import functools
import hmac
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from . import metrics, snapshots
from .client import BiaError, TicketClient
from .config import Settings, get_settings
from .lead_map import LeadMap


class Service:
    """Holds settings, the cached ticket client and the lead map; one instance per process."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.client = TicketClient(self.settings)
        self.rules = metrics.Rules(self.settings.done_statuses, self.settings.active_statuses, self.settings.idle_days)
        self.tz = ZoneInfo(self.settings.timezone)

    # The lead map is re-read on each call so edits to the JSON apply without a restart.
    @property
    def lead_map(self) -> LeadMap:
        return LeadMap.load(self.settings.lead_map_file)

    def now(self) -> datetime:
        """Current time in the service time zone, without tzinfo (BIA timestamps are naive)."""
        return datetime.now(self.tz).replace(tzinfo=None)

    def today(self) -> date:
        return self.now().date()

    def _lead(self, name: str | None) -> str | None:
        """Turn a partial name like 'asha' into the full lead name; raise a clear error listing valid leads otherwise."""
        if not name:
            return None
        lead = self.lead_map.resolve_lead(name)
        if lead is None:
            leads = ", ".join(self.lead_map.leads()) or "none configured (check config/lead_map.json)"
            raise ValueError(f"Unknown lead '{name}'. Leads: {leads}")
        return lead

    # ---- one method per question; MCP tools and REST routes both call these ----

    async def eta_health(self) -> dict[str, Any]:
        tickets = await self.client.get_tickets()
        return {**metrics.eta_health(tickets, self.today(), self.rules), **metrics.breakdown(tickets)}

    async def action_list(self, lead: str | None = None) -> dict[str, Any]:
        tickets = await self.client.get_tickets()
        lead_name = self._lead(lead)
        if lead_name:
            tickets = metrics.filter_tickets(tickets, self.today(), self.rules, self.lead_map, lead=lead_name)
        return {"lead": lead_name, **metrics.action_list(tickets, self.today(), self.rules, self.now())}

    async def list_tickets(self, **filters: Any) -> dict[str, Any]:
        limit = int(filters.pop("limit", 50) or 50)
        filters["lead"] = self._lead(filters.get("lead"))
        if filters.get("bucket") and filters["bucket"] not in metrics.BUCKETS:
            raise ValueError(f"eta_bucket must be one of: {', '.join(metrics.BUCKETS)}")
        tickets = await self.client.get_tickets()
        found = metrics.filter_tickets(tickets, self.today(), self.rules, self.lead_map, **filters)
        found.sort(key=lambda t: (t.eta is None, t.eta or date.max))     # earliest ETA first, missing last
        return {"count": len(found), "showing": min(limit, len(found)), "tickets": [t.brief() for t in found[:limit]]}

    async def get_ticket(self, number: str) -> dict[str, Any]:
        tickets = await self.client.get_tickets()
        needle = number.strip().lstrip("#").lower()
        for t in tickets:
            if needle in (t.number.lower(), t.ticket_id.lower()):
                today = self.today()
                return {
                    **t.brief(),
                    "eta_bucket": metrics.eta_bucket(t, today),
                    "flags": metrics.flags(t, today, self.rules, self.now()),
                    "worked_mins": t.worked_mins,
                    "estimated_hours": t.estimated_hours,
                    "type": t.type_value,
                    "requester": t.requester,
                    "last_updated": t.last_updated.isoformat(sep=" ") if t.last_updated else None,
                    "leads": sorted({self.lead_map.lead_of(a) for a in t.assignees}),
                }
        raise ValueError(f"No ticket found with number or id '{number}'.")

    async def workload(self, lead: str | None = None) -> dict[str, Any]:
        tickets = await self.client.get_tickets()
        rows = metrics.workload(tickets, self.today(), self.rules, self.lead_map)
        lead_name = self._lead(lead)
        if lead_name:
            rows = [r for r in rows if r["lead"] == lead_name]
        return {"as_of": self.today().isoformat(), "lead": lead_name, "people": rows}

    async def scorecard(self) -> dict[str, Any]:
        tickets = await self.client.get_tickets()
        return {
            "as_of": self.today().isoformat(),
            "teams": metrics.lead_scorecard(tickets, self.today(), self.rules, self.lead_map),
            "note": "ETA hit rate and cycle time stay empty until the API returns ticket dates. " + metrics.NEEDS_DATES,
        }

    async def person(self, person: str) -> dict[str, Any]:
        tickets = await self.client.get_tickets()
        return metrics.person_summary(tickets, self.today(), self.rules, self.lead_map, person, self.now())

    async def trend(self, metric: str = "overdue", weeks: int = 12) -> dict[str, Any]:
        points = snapshots.trend(self.settings.snapshot_db, metric, weeks, self.today())
        note = None if points else "No snapshots yet. Run `python -m bia_service snapshot` once a day."
        return {"metric": metric, "weeks": weeks, "points": points, "note": note}

    async def take_snapshot(self) -> dict[str, Any]:
        """Record today's numbers for the trend (run daily, e.g. 6:00 PM IST)."""
        tickets = await self.client.get_tickets(refresh=True)
        today = self.today()
        health = metrics.eta_health(tickets, today, self.rules)
        card = metrics.lead_scorecard(tickets, today, self.rules, self.lead_map)
        snapshots.save(self.settings.snapshot_db, today, health, card)
        return {"saved": today.isoformat(), "eta_health": health}

    async def dashboard(self) -> dict[str, Any]:
        """Everything the dashboard's five panels need, in one call."""
        return {
            "eta_health": await self.eta_health(),
            "scorecard": await self.scorecard(),
            "workload": await self.workload(),
            "action_list": await self.action_list(),
            "trend": {m: (await self.trend(m))["points"] for m in ("overdue", "missing_eta", "eta_coverage_pct")},
        }


# ------------------------------------------------------------------ MCP door

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


def _friendly(fn):
    """Expected problems (bad lead name, BIA unreachable) reach Claude as readable errors.

    The SDK hides the text of any other exception, so these are re-raised as ToolError.
    """
    @functools.wraps(fn)                      # keeps the signature the SDK reads for the tool schema
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except (ValueError, BiaError) as exc:
            raise ToolError(str(exc)) from exc
    return wrapper


def build_mcp(service: Service) -> MCPServer:
    mcp = MCPServer(
        name="bia-tickets",
        title="BIA Tickets",
        instructions=(
            "Read-only access to BIA engineering and server tickets. Use eta_health for the overall picture, "
            "action_list for what needs chasing today, lead_scorecard for the Monday lead review, "
            "team_workload or person_summary for individuals. Dates are judged in IST."
        ),
    )

    @mcp.tool(annotations=READ_ONLY)
    @_friendly
    async def eta_health() -> dict[str, Any]:
        """Counts of open tickets by ETA: missing, overdue, due today, this week, this month, future; plus status and priority breakdown."""
        return await service.eta_health()

    @mcp.tool(annotations=READ_ONLY)
    @_friendly
    async def action_list(lead: str | None = None) -> dict[str, Any]:
        """Open tickets needing action today: missing ETA, overdue, unassigned, stalled, no progress with deadline near, idle. Optional lead name narrows it to that lead's team."""
        return await service.action_list(lead)

    @mcp.tool(annotations=READ_ONLY)
    @_friendly
    async def list_tickets(
        status: str | None = None,
        assignee: str | None = None,
        lead: str | None = None,
        priority: str | None = None,
        eta_bucket: str | None = None,
        include_done: bool = False,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List tickets, earliest ETA first. eta_bucket: missing_eta, overdue, due_today, due_this_week, due_this_month, future. assignee matches part of a name, or 'unassigned'."""
        return await service.list_tickets(
            status=status, assignee=assignee, lead=lead, priority=priority,
            bucket=eta_bucket, include_done=include_done, limit=limit,
        )

    @mcp.tool(annotations=READ_ONLY)
    @_friendly
    async def get_ticket(number: str) -> dict[str, Any]:
        """Full detail for one ticket by ticket number or id: ETA, status, progress, assignees, time worked vs estimate, flags."""
        return await service.get_ticket(number)

    @mcp.tool(annotations=READ_ONLY)
    @_friendly
    async def team_workload(lead: str | None = None) -> dict[str, Any]:
        """Per-person load: open, in progress, overdue, missing ETA, due this week, effort vs estimate %. Optional lead name narrows it to that team."""
        return await service.workload(lead)

    @mcp.tool(annotations=READ_ONLY)
    @_friendly
    async def lead_scorecard() -> dict[str, Any]:
        """One row per lead's team: open, overdue, missing ETA, due this week, ETA coverage %. Use for the Monday lead review."""
        return await service.scorecard()

    @mcp.tool(annotations=READ_ONLY)
    @_friendly
    async def person_summary(person: str) -> dict[str, Any]:
        """One person's open tickets and what is at risk this week."""
        return await service.person(person)

    @mcp.tool(annotations=READ_ONLY)
    @_friendly
    async def trend(metric: str = "overdue", weeks: int = 12) -> dict[str, Any]:
        """Weekly trend from daily snapshots. metric: open, overdue, missing_eta, due_this_week, eta_coverage_pct."""
        return await service.trend(metric, weeks)

    # -------------------------------------------------------------- REST door

    def _json(handler):
        """Wrap a Service call as a JSON route; known errors become 4xx/502 instead of 500s."""
        async def route(request: Request) -> Response:
            try:
                return JSONResponse(await handler(request))
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            except BiaError as exc:
                return JSONResponse({"error": str(exc)}, status_code=502)
        return route

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> Response:
        # Public on purpose (load balancers); reveals nothing sensitive.
        return JSONResponse({"status": "ok", "source": service.client.source})

    mcp.custom_route("/api/eta-health", methods=["GET"])(_json(lambda r: service.eta_health()))
    mcp.custom_route("/api/action-list", methods=["GET"])(_json(lambda r: service.action_list(r.query_params.get("lead"))))
    mcp.custom_route("/api/workload", methods=["GET"])(_json(lambda r: service.workload(r.query_params.get("lead"))))
    mcp.custom_route("/api/scorecard", methods=["GET"])(_json(lambda r: service.scorecard()))
    mcp.custom_route("/api/dashboard", methods=["GET"])(_json(lambda r: service.dashboard()))
    mcp.custom_route("/api/snapshot", methods=["POST"])(_json(lambda r: service.take_snapshot()))

    return mcp


# ------------------------------------------------------------------ HTTP auth

class BearerAuth:
    """Require `Authorization: Bearer <SERVICE_TOKEN>` on every HTTP request except /health.

    Covers both doors (/mcp and /api/*). The SDK's custom routes are public by
    default, so this wrapper is what keeps ticket data private.
    """

    PUBLIC_PATHS = {"/health"}

    def __init__(self, app: ASGIApp, token: str):
        if not token:
            raise ValueError("SERVICE_TOKEN must be set to run the HTTP server.")
        self.app = app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] not in self.PUBLIC_PATHS:
            supplied = dict(scope.get("headers") or []).get(b"authorization", b"")
            if not hmac.compare_digest(supplied, self.expected):     # constant-time compare
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def build_http_app(service: Service, host: str = "127.0.0.1") -> ASGIApp:
    """The MCP endpoint (/mcp) and REST routes in one app, behind the bearer token."""
    from mcp.server.transport_security import TransportSecuritySettings

    mcp = build_mcp(service)
    security = None
    if service.settings.allowed_hosts:
        # Deployed behind a domain: accept only these Host headers.
        security = TransportSecuritySettings(allowed_hosts=list(service.settings.allowed_hosts))
    app = mcp.streamable_http_app(host=host, transport_security=security, stateless_http=True, json_response=True)
    return BearerAuth(app, service.settings.service_token)
