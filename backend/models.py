"""Data types for the Campus Customs agent team.

- AgentName: the five team members
- Ticket: one row from the board (read through the MCP get_tickets tool)
- Handoff: one agent handing work to another
- ApprovalRequest / ApprovalDecision: the human-in-the-loop gate for money and discounts
- DraftMessage: a message saved on a ticket, never sent
- AgentReport: structured output of every specialist (Inventory, Accounting, Facilities, Customer Service)
- TicketResolution: structured output of the Boss, the final call on a ticket
- AuditEvent: one line in output/audit_trail.json
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

AgentName = Literal["boss", "inventory", "accounting", "facilities", "customer_service"]
SPECIALISTS: tuple[AgentName, ...] = ("inventory", "accounting", "facilities", "customer_service")

TicketStatus = Literal["open", "in_progress", "waiting_approval", "blocked", "resolved"]
TicketType = Literal["customer_order", "rent_notice", "price_override"] | str


# --------------------------------------------------------------------------- #
# Board
# --------------------------------------------------------------------------- #
class Ticket(BaseModel):
    """A ticket as stored in the tickets table."""

    id: int
    type: TicketType
    requester: str
    subject: str
    sku: str | None = None
    size: str | None = None
    qty: int | None = None
    lease_id: int | None = None
    invoice_id: int | None = None
    status: TicketStatus | str
    notes: str | None = None
    created_at: str


# --------------------------------------------------------------------------- #
# Teamwork
# --------------------------------------------------------------------------- #
class Handoff(BaseModel):
    """One agent asking another for help. Any agent can hand off to any other."""

    from_agent: AgentName
    to_agent: AgentName
    task: str = Field(description="A self-contained request the other agent can act on.")
    depth: int = Field(description="0 = asked by the Boss, 1 = a specialist asked another, ...")
    status: Literal["done", "refused", "error"] = "done"
    summary: str | None = None


# --------------------------------------------------------------------------- #
# Human-in-the-loop
# --------------------------------------------------------------------------- #
ApprovalKind = Literal["payment", "purchase_order", "discount"]


class ApprovalRequest(BaseModel):
    """Something only a human can approve. Created by the harness when an agent
    calls a gated MCP tool (manage_payables pay, place_purchase_order, record_discount)."""

    id: str = Field(default_factory=lambda: uuid4().hex[:8], description="Used by POST /api/approvals/{id}.")
    kind: ApprovalKind
    tool: str
    requested_by: AgentName
    ticket_id: int | None = None
    amount: float | None = Field(default=None, description="Dollars leaving the shop, if any.")
    payee: str | None = None
    summary: str = Field(description="One line a human can say yes or no to.")
    args: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecision(BaseModel):
    approved: bool
    approver: str | None = Field(default=None, description="Human's name; written to payments.approved_by.")
    reason: str | None = None


class PendingApproval(BaseModel):
    """An action the team recommends but that still needs a human yes."""

    kind: ApprovalKind
    summary: str
    amount: float | None = None
    status: Literal["approved", "denied", "not_yet_requested"] = "not_yet_requested"


# --------------------------------------------------------------------------- #
# Agent outputs
# --------------------------------------------------------------------------- #
class DraftMessage(BaseModel):
    """A message for a customer, vendor, or landlord. Saved on the ticket, never sent."""

    recipient: str
    subject: str
    body: str
    saved: bool = Field(description="True once save_draft stored it on the ticket.")


class AgentReport(BaseModel):
    """What a specialist hands back to whoever asked it."""

    agent: AgentName
    summary: str = Field(description="2-4 sentences: what you found and what you did.")
    facts: list[str] = Field(
        default_factory=list,
        description="Numbers and facts used, each traceable to an MCP tool result (no guesses).",
    )
    actions_taken: list[str] = Field(
        default_factory=list, description="Database changes actually made through MCP tools."
    )
    needs_approval: list[PendingApproval] = Field(default_factory=list)
    drafts: list[DraftMessage] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    recommendation: str = Field(description="What you think the Boss should decide.")


class TicketResolution(BaseModel):
    """The Boss's final call on one ticket."""

    ticket_id: int
    status: Literal["resolved", "waiting_approval", "blocked", "in_progress"] = Field(
        description=(
            "resolved = nothing left for the shop to do now; waiting_approval = a human "
            "still has to approve something; blocked = cannot move until something "
            "outside the team changes (e.g. cash, vendor); in_progress = work continues."
        )
    )
    decision: str = Field(description="The final call, 1-3 sentences.")
    assigned_to: list[AgentName] = Field(description="Which agents worked the ticket.")
    actions_taken: list[str] = Field(default_factory=list)
    pending_approvals: list[PendingApproval] = Field(default_factory=list)
    drafts: list[DraftMessage] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    ticket_note: str = Field(description="One-paragraph note to write on the ticket.")


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #
AuditEventType = Literal[
    "run_start", "run_end", "db_reset",
    "ticket_start", "ticket_end",
    "agent_start", "agent_step", "agent_end",
    "tool_call", "tool_result",
    "approval_requested", "approval_decision",
    "handoff_start", "handoff_end",
    "limit_hit", "error",
]


class AuditEvent(BaseModel):
    """One record appended to output/audit_trail.json."""

    ts: str = Field(description="Wall-clock UTC time, ISO 8601.")
    run_id: str
    seq: int
    event: AuditEventType
    shop_date: str | None = Field(default=None, description="desk.date_today at run time.")
    ticket_id: int | None = None
    agent: AgentName | None = None
    depth: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# API (backend/main.py)
# --------------------------------------------------------------------------- #
class TicketSummary(BaseModel):
    id: int
    type: str
    requester: str
    subject: str
    status: str
    resolved: bool
    sku: str | None = None
    size: str | None = None
    qty: int | None = None
    notes: str | None = None


class TicketsResponse(BaseModel):
    date_today: str
    tickets: list[TicketSummary]


class RunState(BaseModel):
    state: Literal["idle", "running", "done", "error"]
    run_id: str | None = None
    ticket_id: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    result: dict[str, Any] | None = None
    pending_approvals: int = 0


class EventItem(BaseModel):
    """One readable line for the board, built from an audit record."""

    index: int = Field(description="Position in output/audit_trail.json; poll with ?after=<last index>.")
    ts: str
    run_id: str
    ticket_id: int | None = None
    agent: str | None = None
    depth: int | None = None
    kind: str = Field(description="e.g. said, tool_call, tool_result, handoff, approval_requested, final")
    text: str
    tool: str | None = None
    approval_id: str | None = None


class EventsResponse(BaseModel):
    last_index: int
    events: list[EventItem]


class ApprovalDecisionIn(BaseModel):
    approved: bool
    approver: str | None = Field(default=None, description="Required when approved; written to payments.approved_by.")
    reason: str | None = None


class PendingApprovalOut(BaseModel):
    id: str
    created_at: str
    request: ApprovalRequest


class CashBalance(BaseModel):
    account: str
    balance: float
    date: str
