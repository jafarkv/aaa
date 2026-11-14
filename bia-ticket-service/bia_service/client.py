"""BIA ticket client: fetches tickets from the BIA API (or a local JSON file) and caches them.

One fetch serves every tool call for CACHE_SECONDS, so Claude asking five
questions in a row costs one BIA request, not five.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx

from .config import Settings
from .models import Ticket


class BiaError(RuntimeError):
    """Raised when tickets can't be loaded; the message is safe to show to a user."""


def _extract_records(payload: Any) -> list[dict[str, Any]]:
    """Accept the common response shapes: a bare list, or a dict wrapping the list."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("tickets", "data", "result", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    raise BiaError("BIA returned an unexpected response shape; expected a list of tickets.")


class TicketClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._tickets: list[Ticket] = []
        self._fetched_at: float = 0.0          # monotonic time of the last successful fetch
        self._lock = asyncio.Lock()            # one fetch at a time, even under parallel tool calls

    @property
    def source(self) -> str:
        """Human-readable data source, for /health and tool output (never includes the key)."""
        return "file" if self.settings.tickets_file else "api"

    async def get_tickets(self, refresh: bool = False) -> list[Ticket]:
        """Return cached tickets, re-fetching when the cache is older than CACHE_SECONDS."""
        async with self._lock:
            fresh = (time.monotonic() - self._fetched_at) < self.settings.cache_seconds
            if self._tickets and fresh and not refresh:
                return self._tickets
            records = await self._load_records()
            self._tickets = [Ticket.from_api(r) for r in records if isinstance(r, dict)]
            self._fetched_at = time.monotonic()
            return self._tickets

    async def _load_records(self) -> list[dict[str, Any]]:
        if self.settings.tickets_file:
            return self._load_file(Path(self.settings.tickets_file))
        return await self._load_api()

    @staticmethod
    def _load_file(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            raise BiaError(f"Ticket file not found: {path}")
        return _extract_records(json.loads(path.read_text(encoding="utf-8")))

    async def _load_api(self) -> list[dict[str, Any]]:
        s = self.settings
        if not s.api_url or not s.api_key:
            raise BiaError("BIA_API_URL and BIA_API_KEY must be set (or BIA_TICKETS_FILE for offline mode).")

        # Same request body the BIA team report uses; empty strings = no filter.
        body = {"requester": "", "tag": s.filter_tag, "country": "", "status": "", "sort": ""}
        headers = {"Authorization": s.api_key, "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=s.request_timeout) as http:
                response = await http.post(s.api_url, json=body, headers=headers)
        except httpx.HTTPError as exc:
            # Don't leak headers (the key) into the error message.
            raise BiaError(f"Could not reach BIA: {type(exc).__name__}") from exc

        if response.status_code in (401, 403):
            raise BiaError("BIA rejected the API key (check BIA_API_KEY).")
        if response.status_code >= 400:
            raise BiaError(f"BIA returned HTTP {response.status_code}.")
        try:
            return _extract_records(response.json())
        except ValueError as exc:
            raise BiaError("BIA returned a non-JSON response.") from exc
