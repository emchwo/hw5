"""Campus Customs desk API (FastAPI).

Run from the backend/ folder:
    uvicorn main:app --reload --port 8000

Routes (interactive docs at http://localhost:8000/docs):
    GET  /api/tickets                  tickets + open/resolved
    POST /api/tickets/{ticket_id}/run  start the agent team on one ticket
    GET  /api/run                      is a run going, and how did the last one end
    GET  /api/events?after=N           recent agent events for the board to refresh
    GET  /api/approvals                approvals waiting for a human
    POST /api/approvals/{approval_id}  human clicks Approve / Deny
    GET  /api/cash                     current checking balance
    POST /api/reset                    reset the working DB to the original values

All shop data goes through the MCP server (mcp_server/server.py) over
data/campus_customs_new.db. Agents: gpt-6-luna only.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from agents.approvals import WebApprover
from agents.audit import AuditTrail
from agents.config import (
    AUDIT_PATH, DB_ORIGINAL, DB_WORKING, MAX_HANDOFF_DEPTH, MAX_HANDOFFS_PER_TICKET, MODEL_NAME,
    TICKET_REQUEST_LIMIT, TICKET_TOKEN_LIMIT, TICKET_TOOL_CALL_LIMIT, require_api_key,
)
from agents.runner import work_ticket
from agents.team import build_mcp
from models import (
    ApprovalDecision, ApprovalDecisionIn, CashBalance, EventItem, EventsResponse,
    PendingApprovalOut, RunState, TicketsResponse, TicketSummary,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Desk:
    """Server state: one MCP connection, one run at a time, pending approvals."""

    def __init__(self) -> None:
        self.mcp = build_mcp()
        self.approver = WebApprover()
        self.audit: AuditTrail | None = None  # most recent trail; its event list is live
        self.lock = asyncio.Lock()
        self.task: asyncio.Task | None = None
        self.run = RunState(state="idle")

    @property
    def busy(self) -> bool:
        return self.task is not None and not self.task.done()

    async def call(self, tool: str, args: dict[str, Any]) -> Any:
        try:
            return await self.mcp.direct_call_tool(tool, args)
        except Exception as exc:  # MCP tool errors carry a readable message
            raise HTTPException(status_code=400, detail=str(exc)) from exc


desk: Desk


@asynccontextmanager
async def lifespan(app: FastAPI):
    global desk
    desk = Desk()
    async with desk.mcp:  # one MCP server process for the whole API
        yield
    desk.approver.cancel_all("Server shut down.")


app = FastAPI(title="Campus Customs desk API", version="1.0", lifespan=lifespan)
# Browsers may call the API from the Vite board (npm run dev -> http://localhost:5173),
# any other local dev port, or desk_tickets.html opened from disk (origin "null").
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "null"],
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Tickets
# --------------------------------------------------------------------------- #
@app.get("/api/tickets", response_model=TicketsResponse)
async def list_tickets() -> TicketsResponse:
    """All tickets on the board and whether each is open or resolved."""
    board = await desk.call("get_tickets", {"status": "all"})
    return TicketsResponse(
        date_today=board["date_today"],
        tickets=[
            TicketSummary(
                id=t["id"], type=t["type"], requester=t["requester"], subject=t["subject"],
                status=t["status"], resolved=t["status"] == "resolved",
                sku=t["sku"], size=t["size"], qty=t["qty"], notes=t["notes"],
            )
            for t in board["tickets"]
        ],
    )


@app.post("/api/tickets/{ticket_id}/run", response_model=RunState, status_code=202)
async def run_ticket_route(ticket_id: int) -> RunState:
    """Start the agent team on one ticket in the background. Poll /api/events and /api/run."""
    try:
        require_api_key()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    async with desk.lock:
        if desk.busy:
            raise HTTPException(status_code=409, detail=f"Ticket {desk.run.ticket_id} is already running ({desk.run.run_id}).")
        try:
            board = await desk.mcp.direct_call_tool("get_tickets", {"ticket_id": ticket_id})
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        ticket = board["tickets"][0]

        audit = AuditTrail()
        audit.shop_date = board["date_today"]
        audit.log(
            "run_start", source="api", model=MODEL_NAME, approval_mode="web", tickets=[ticket_id],
            limits={"ticket_tokens": TICKET_TOKEN_LIMIT, "ticket_requests": TICKET_REQUEST_LIMIT,
                    "ticket_tool_calls": TICKET_TOOL_CALL_LIMIT, "handoff_depth": MAX_HANDOFF_DEPTH,
                    "handoffs_per_ticket": MAX_HANDOFFS_PER_TICKET},
        )
        desk.audit = audit
        desk.run = RunState(state="running", run_id=audit.run_id, ticket_id=ticket_id, started_at=_now())

        async def go() -> None:
            try:
                result = await work_ticket(ticket, desk.mcp, audit, desk.approver)
                desk.run.state, desk.run.result = "done", result
                audit.log("run_end", results=[(ticket_id, result["status"], result["usage"]["total_tokens"])], usage=result["usage"])
            except Exception as exc:
                desk.run.state, desk.run.result = "error", {"error": f"{type(exc).__name__}: {exc}"}
                audit.log("error", ticket_id=ticket_id, where="api run", error=desk.run.result["error"])
            finally:
                desk.run.finished_at = _now()

        desk.task = asyncio.create_task(go())
        return desk.run


@app.get("/api/run", response_model=RunState)
async def run_status() -> RunState:
    """Whether a run is going, which ticket, and the result of the last run."""
    return desk.run.model_copy(update={"pending_approvals": len(desk.approver.pending)})


@app.get("/api/runs/{run_id}", response_model=RunState)
async def past_run(run_id: str) -> RunState:
    """Rebuild a finished run from the audit trail (lets the board replay any past ticket run)."""
    recs = [r for r in _records() if r.get("run_id") == run_id]
    end = next((r for r in reversed(recs) if r["event"] == "ticket_end"), None)
    if not recs or end is None:
        raise HTTPException(status_code=404, detail=f"No finished ticket run {run_id!r} in the audit trail.")
    boss = next((r for r in reversed(recs) if r["event"] == "agent_end" and r.get("depth") == 0), None)
    resolution = boss["data"]["output"] if boss else None
    note = ((end["data"].get("ticket_update") or {}).get("note")) or (resolution or {}).get("decision", "")
    return RunState(
        state="done", run_id=run_id, ticket_id=end.get("ticket_id"),
        started_at=recs[0]["ts"], finished_at=end["ts"],
        result={"ticket_id": end.get("ticket_id"), "status": end["data"].get("status"), "note": note,
                "resolution": resolution, "usage": end["data"].get("usage")},
    )


# --------------------------------------------------------------------------- #
# Events (board refresh)
# --------------------------------------------------------------------------- #
def _short(value: Any, n: int = 500) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= n else text[:n] + "…"


def _summarize(i: int, rec: dict[str, Any]) -> list[EventItem]:
    """Turn one audit record into readable board lines."""
    ev, d = rec["event"], rec.get("data", {})
    base = dict(index=i, ts=rec["ts"], run_id=rec["run_id"], ticket_id=rec.get("ticket_id"),
                agent=rec.get("agent"), depth=rec.get("depth"))
    items: list[EventItem] = []

    def add(kind: str, text: str, **kw: Any) -> None:
        items.append(EventItem(**base, kind=kind, text=text, **kw))

    if ev == "agent_step" and d.get("step") == "model_response":
        for part in d.get("parts", []):
            if part.get("kind") == "text" and part.get("content"):
                add("said", _short(part["content"]))
            elif part.get("kind") == "tool-call" and part.get("tool_name") not in (None, "final_result"):
                add("tool_call", f"{part['tool_name']}({_short(part.get('args', {}), 300)})", tool=part["tool_name"])
    elif ev == "tool_result":
        if d.get("tool") == "hand_off":
            return items
        body = d.get("error") or d.get("result")
        add("tool_result", _short(body, 400), tool=d.get("tool"))
    elif ev == "handoff_start":
        add("handoff", f"→ {d.get('to_agent')}: {_short(d.get('task', ''), 400)}")
    elif ev == "handoff_end":
        if d.get("status") == "refused":
            add("handoff", f"hand-off to {d.get('to_agent')} refused: {d.get('reason')}")
        else:
            add("handoff", f"← {d.get('to_agent')} reported back: {_short((d.get('report') or {}).get('summary', ''), 400)}")
    elif ev == "approval_requested":
        r = d.get("request", {})
        add("approval_requested", r.get("summary", ""), tool=r.get("tool"), approval_id=r.get("id"))
    elif ev == "approval_decision":
        dec = d.get("decision", {})
        text = f"approved by {dec.get('approver')}" if dec.get("approved") else f"denied: {dec.get('reason')}"
        add("approval_decision", text, tool=d.get("tool"))
    elif ev == "agent_start":
        add("agent_start", f"{rec.get('agent')} started")
    elif ev == "agent_end":
        out = d.get("output", {})
        if rec.get("agent") == "boss":
            add("final", f"[{out.get('status')}] {out.get('decision', '')}")
        else:
            add("report", _short(out.get("summary", ""), 400))
    elif ev in ("ticket_start", "ticket_end"):
        add(ev, f"ticket {rec.get('ticket_id')} " + ("started" if ev == "ticket_start" else f"ended: {d.get('status')}"))
    elif ev in ("run_start", "run_end", "db_reset", "limit_hit", "error"):
        add(ev, _short({k: v for k, v in d.items() if k not in ("limits",)}, 300))
    return items


def _records() -> list[dict[str, Any]]:
    if desk.audit is not None:
        return desk.audit._events  # live list for the current run
    if AUDIT_PATH.exists() and AUDIT_PATH.stat().st_size:
        return json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    return []


@app.get("/api/events", response_model=EventsResponse)
async def events(
    after: int = Query(-1, description="Only events after this index (use last_index from the previous call)."),
    limit: int = Query(100, ge=1, le=1000),
    ticket_id: int | None = None,
    run_id: str | None = None,
) -> EventsResponse:
    """Recent agent events (what each agent said, tools used, hand-offs, approvals)."""
    recs = _records()
    start = max(after + 1, 0)
    out: list[EventItem] = []
    for i in range(start, len(recs)):
        r = recs[i]
        if ticket_id is not None and r.get("ticket_id") != ticket_id:
            continue
        if run_id is not None and r.get("run_id") != run_id:
            continue
        out.extend(_summarize(i, r))
    return EventsResponse(last_index=len(recs) - 1, events=out[-limit:])


# --------------------------------------------------------------------------- #
# Approvals
# --------------------------------------------------------------------------- #
@app.get("/api/approvals", response_model=list[PendingApprovalOut])
async def pending_approvals() -> list[PendingApprovalOut]:
    """Payments, purchase orders, and discounts waiting for a human."""
    return [
        PendingApprovalOut(id=k, created_at=v["created_at"], request=v["request"])
        for k, v in desk.approver.pending.items()
    ]


@app.post("/api/approvals/{approval_id}")
async def decide_approval(approval_id: str, body: ApprovalDecisionIn) -> dict[str, Any]:
    """A human clicks Approve or Deny. Approve needs the human's name (saved as approved_by)."""
    if body.approved and not (body.approver or "").strip():
        raise HTTPException(status_code=422, detail="Approving needs your name (approver).")
    decision = ApprovalDecision(
        approved=body.approved,
        approver=(body.approver or "").strip() or None,
        reason=body.reason or (None if body.approved else "Denied by human on the board."),
    )
    if not desk.approver.decide(approval_id, decision):
        raise HTTPException(status_code=404, detail=f"No pending approval {approval_id!r}.")
    return {"approval_id": approval_id, "approved": decision.approved, "approver": decision.approver}


# --------------------------------------------------------------------------- #
# Cash
# --------------------------------------------------------------------------- #
@app.get("/api/cash", response_model=CashBalance)
async def cash() -> CashBalance:
    """Current checking balance from cash_accounts (read through MCP)."""
    payables = await desk.call("manage_payables", {"action": "list"})
    acct = next((a for a in payables["cash_accounts"] if a["name"] == "checking"), None)
    if acct is None:
        raise HTTPException(status_code=404, detail="No checking account in cash_accounts.")
    return CashBalance(account=acct["name"], balance=acct["balance"], date=acct["date"])


# --------------------------------------------------------------------------- #
# Reset
# --------------------------------------------------------------------------- #
@app.post("/api/reset")
async def reset() -> dict[str, Any]:
    """Copy campus_customs.db over campus_customs_new.db so a new run starts clean."""
    async with desk.lock:
        if desk.busy:
            raise HTTPException(status_code=409, detail="A ticket is running. Wait for it to finish before resetting.")
        shutil.copyfile(DB_ORIGINAL, DB_WORKING)
        audit = AuditTrail()
        audit.log("db_reset", source="api", from_file=DB_ORIGINAL.name, to_file=DB_WORKING.name)
        desk.audit = audit
        desk.run = RunState(state="idle")
    board = await desk.call("get_tickets", {"status": "all"})
    cash_now = await cash()
    return {
        "reset": True,
        "database": DB_WORKING.name,
        "tickets": {t["id"]: t["status"] for t in board["tickets"]},
        "checking_balance": cash_now.balance,
    }
