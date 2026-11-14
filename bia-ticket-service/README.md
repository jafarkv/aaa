# BIA Ticket Service

One metrics engine for engineering and server tickets in BIA, with two ways in:

- **MCP server** for Claude. the PM and leads ask "which of my team's tickets are overdue?" in plain English.
- **REST API** for Make.com automations and the dashboard.

Both read the same numbers, so Claude, Make.com and the dashboard always agree. Version 1 is **read-only** and cannot change anything in BIA.

```
BIA ticket API ──► metrics engine ──► MCP (/mcp or stdio) ──► Claude Desktop / Claude Code
                    + lead map        └► REST (/api/*)    ──► Make.com, dashboard
                    + daily snapshots
```

---

## 1. Set up on your PC (Windows)

You need Python 3.11 or newer ([python.org](https://www.python.org/downloads/); tick "Add to PATH").

```powershell
git clone https://github.com/jafarkv/aaa.git
cd aaa\bia-ticket-service
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"

copy .env.example .env                              # then edit .env: BIA_API_URL + the NEW key
copy config\lead_map.example.json config\lead_map.json   # then fill in the real leads and teams
```

Check that it works:

```powershell
python -m pytest                     # 35 tests on sample data, no BIA or GitLab access needed
python -m bia_service report         # live numbers from BIA
```

If `report` shows statuses that don't match `DONE_STATUSES` / `ACTIVE_STATUSES` in `.env`, update those lists to BIA's real labels.

To try it without BIA, set `BIA_TICKETS_FILE=tests/fixtures/tickets_sample.json` in `.env`.

## 2. Connect it to Claude

**Claude Desktop**: open Settings → Developer → Edit Config, and add the following (use your real path):

```json
{
  "mcpServers": {
    "bia-tickets": {
      "command": "C:\\path\\to\\aaa\\bia-ticket-service\\.venv\\Scripts\\python.exe",
      "args": ["-m", "bia_service", "serve"]
    }
  }
}
```

Restart Claude Desktop. The `bia-tickets` tools then appear in the tools menu.

**Claude Code**:

```powershell
claude mcp add bia-tickets -- C:\path\to\aaa\bia-ticket-service\.venv\Scripts\python.exe -m bia_service serve
```

Try it: *"Run the lead scorecard and draft my Monday lead review."*

## 3. Daily snapshot (for the 12-week trend)

The BIA API only returns today's state, so the service records one snapshot a day. Use Windows Task Scheduler to create a daily task at **6:00 PM IST** that runs:

```
C:\path\to\aaa\bia-ticket-service\.venv\Scripts\python.exe -m bia_service snapshot
```

Once the service is hosted, a Make.com scenario can call `POST /api/snapshot` instead.

## 4. Host it for the team (Week 2–3)

```bash
# .env on the server: BIA_* settings, plus
#   SERVICE_TOKEN=<long random string>
#   ALLOWED_HOSTS=<the domain, e.g. tickets-mcp.yourdomain.com>
python -m bia_service serve --http --host 0.0.0.0 --port 8000
```

- Put it behind HTTPS (a reverse proxy or load balancer). Only `/health` is public; everything else needs `Authorization: Bearer <SERVICE_TOKEN>`.
- The server refuses to start in HTTP mode if `SERVICE_TOKEN` is empty.
- Claude Code: `claude mcp add --transport http bia-tickets https://<domain>/mcp --header "Authorization: Bearer <token>"`
- Make.com: HTTP module → GET `https://<domain>/api/action-list` with the same header.

## What it answers

| MCP tool | REST route | Answers |
|---|---|---|
| `eta_health` | `GET /api/eta-health` | Open tickets by ETA: missing, overdue, due today, this week, this month, future; status and priority breakdown |
| `action_list(lead?)` | `GET /api/action-list?lead=` | Missing ETA, overdue, unassigned, stalled, no progress with a deadline near, idle 3+ days |
| `list_tickets(...)` | — | Tickets filtered by status, assignee, lead, priority or ETA bucket |
| `get_ticket(number)` | — | One ticket in full, with its flags |
| `team_workload(lead?)` | `GET /api/workload?lead=` | Per person: open, in progress, overdue, missing ETA, effort vs estimate % |
| `lead_scorecard` | `GET /api/scorecard` | Per lead's team: open, overdue, missing ETA, due this week, ETA coverage % |
| `person_summary(person)` | — | One person's open tickets and what's at risk this week |
| `trend(metric, weeks)` | — | Weekly trend from daily snapshots |
| — | `GET /api/dashboard` | Everything the dashboard needs, in one call |
| — | `POST /api/snapshot` | Save today's snapshot |

Lead names can be partial (`asha` matches `Asha Menon`). People missing from the lead map show up under **Unmapped**, so gaps in the map are visible.

## Code activity from GitLab (optional)

Tracks how code moves, not how much is typed. It reads **merge requests** (MRs) for one GitLab group, read-only:

| MCP tool | REST route | Answers |
|---|---|---|
| `mr_activity(lead?, days?)` | `GET /api/mr-activity?lead=&days=` | Per person: MRs merged, median hours from open to merge, open MRs, reviews pending on them, MRs missing a ticket number |
| `mr_review_queue(lead?)` | `GET /api/mr-review-queue?lead=` | Open, non-draft MRs nobody has commented on after `REVIEW_WAIT_HOURS` (default 24), longest wait first |
| `mr_stale(lead?)` | `GET /api/mr-stale?lead=` | Open MRs with no activity for `IDLE_DAYS` (default 3) |

Setup: in GitLab create an access token with **only the `read_api` scope** (best from a dedicated service account that is a Reporter on the group), then set `GITLAB_URL` (self-hosted GitLab: your address), `GITLAB_TOKEN` and `GITLAB_GROUP` in `.env`. Check with `python -m bia_service serve` and ask Claude: *"Which merge requests are waiting for review?"*

Three things to get right:

- **Ticket numbers.** The rule "every MR title or branch starts with the BIA ticket number" is what links code to tickets. Set `TICKET_REGEX` to BIA's real format, and add a GitLab merge check or MR template that enforces it.
- **People.** Authors are matched to leads through `config/lead_map.json`. If a GitLab display name differs from the BIA name, add the GitLab **username** as an alias.
- **What it can't see.** Server and IT work (AWS, backups, patching) leaves few MRs, so judge Server/IT on tickets and runbooks. A "waiting for review" MR counts only if nobody commented, so a review done purely by approval click shows as waiting.

Deliberately not measured: commit counts and lines of code. They are easy to inflate and meaningless with AI-written code.

## Before going live

- [ ] **Rotate the BIA API key.** The current key is written in plain text in the BIA team report skill. Put the new key only in `.env`.
- [ ] **Use a private repository** for any fork that holds real config. `jafarkv/aaa` is public, so `.env`, `config/lead_map.json` and `data/` are git-ignored on purpose.
- [ ] Match `DONE_STATUSES` and `ACTIVE_STATUSES` to BIA's real labels.
- [ ] Have the leads fill in `config/lead_map.json`.
- [ ] GitLab: create the `read_api` token, set `TICKET_REGEX` to BIA's real ticket format.

## Known limits (v1)

- **ETA hit rate and cycle time are empty.** The BIA API doesn't return created, completed or status-change dates. Once the BIA API adds them, those two fields in the scorecard can be filled in.
- **Read-only.** Write tools (`set_eta`, `add_comment`, `update_status`) are planned for v2, for leads only and with an audit log.

## Code map

| File | What it does |
|---|---|
| `bia_service/models.py` | Cleans one raw BIA record into a typed `Ticket` (empty ETAs, string numbers, assignee fallback) |
| `bia_service/client.py` | Fetches from the BIA API or a JSON file, with a cache (`CACHE_SECONDS`) |
| `bia_service/metrics.py` | **All metric rules**: ETA buckets, flags, workload, scorecard (pure functions) |
| `bia_service/lead_map.py` | Maps people to leads, with aliases |
| `bia_service/gitlab.py` | Reads merge requests from the GitLab group API (paged, cached, read-only) |
| `bia_service/gitlab_metrics.py` | Code-activity rules: review queue, stale MRs, cycle time, missing ticket numbers |
| `bia_service/snapshots.py` | Daily snapshots in SQLite, weekly trend |
| `bia_service/server.py` | MCP tools, REST routes, bearer-token auth |
| `bia_service/__main__.py` | Command line: `serve`, `snapshot`, `report` |
