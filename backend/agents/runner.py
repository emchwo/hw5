"""Work one ticket end to end. Shared by the CLI (run_tickets.py) and the API (main.py).

Boss + team work the ticket, then the result is written back to the board
through the MCP update_ticket tool. Safety-limit stops and crashes are
recorded on the ticket and in the audit trail instead of being lost.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.usage import RunUsage

from .approvals import Approver
from .audit import AuditTrail
from .team import run_ticket, usage_dict


async def work_ticket(
    ticket: dict[str, Any], mcp: MCPToolset, audit: AuditTrail, approver: Approver
) -> dict[str, Any]:
    tid = ticket["id"]
    audit.log("ticket_start", ticket_id=tid, ticket=ticket)
    usage = RunUsage()
    resolution = None
    try:
        resolution = await run_ticket(ticket, mcp, audit, approver, usage)
        status = resolution.status
        note = f"{resolution.decision} {resolution.ticket_note}".strip()
    except UsageLimitExceeded as exc:
        status, note = "blocked", f"Stopped by the team's safety limit: {exc}. A human should review."
        audit.log("limit_hit", ticket_id=tid, limit="ticket", error=str(exc), usage=usage_dict(usage))
    except Exception as exc:
        status, note = "open", f"Agent run failed ({type(exc).__name__}: {exc}). Left open for a human."
        audit.log("error", ticket_id=tid, where="work_ticket", error=f"{type(exc).__name__}: {exc}")

    update = await mcp.direct_call_tool("update_ticket", {"ticket_id": tid, "status": status, "note": note})
    result = {
        "ticket_id": tid,
        "status": status,
        "note": note,
        "resolution": resolution.model_dump() if resolution else None,
        "usage": usage_dict(usage),
    }
    audit.log("ticket_end", ticket_id=tid, status=status, ticket_update=update, usage=result["usage"])
    return result
