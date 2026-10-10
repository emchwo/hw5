"""Human approval for payments, purchase orders, and discounts.

Agents never approve anything. When an agent calls a gated MCP tool, the
harness (team.py) builds an ApprovalRequest and calls an Approver:

- TerminalApprover: asks the human at the keyboard, y/N plus their name.
  The name becomes approved_by in the database.
- DenyAllApprover: says no to everything (for dry runs and tests).
- WebApprover: waits for a human to click Approve / Deny on the web board.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Protocol

from models import ApprovalDecision, ApprovalRequest


class Approver(Protocol):
    async def __call__(self, request: ApprovalRequest) -> ApprovalDecision: ...


class DenyAllApprover:
    async def __call__(self, request: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision(approved=False, reason="Dry run: approvals are switched off (--approval deny).")


class TerminalApprover:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()  # one question on screen at a time

    async def __call__(self, request: ApprovalRequest) -> ApprovalDecision:
        async with self._lock:
            return await asyncio.to_thread(self._ask, request)

    @staticmethod
    def _ask(request: ApprovalRequest) -> ApprovalDecision:
        bar = "=" * 64
        print(f"\n{bar}\nHUMAN APPROVAL NEEDED ({request.kind})")
        print(f"  Ticket:       {request.ticket_id}")
        print(f"  Requested by: {request.requested_by}")
        print(f"  Request:      {request.summary}")
        if request.amount is not None:
            print(f"  Amount:       ${request.amount:,.2f}" + (f" to {request.payee}" if request.payee else ""))
        print(bar)
        answer = input("Approve? [y/N]: ").strip().lower()
        if answer not in {"y", "yes"}:
            reason = input("Reason (optional): ").strip() or "Denied by human."
            return ApprovalDecision(approved=False, reason=reason)
        name = input("Your name (recorded as approved_by): ").strip()
        if not name:
            return ApprovalDecision(approved=False, reason="No approver name given, so it was treated as a no.")
        return ApprovalDecision(approved=True, approver=name)


class WebApprover:
    """Holds each request until a human clicks Approve / Deny in the web board
    (POST /api/approvals/{id}). No answer within `timeout` seconds counts as a no."""

    def __init__(self, timeout: float = 900) -> None:
        self.timeout = timeout
        self.pending: dict[str, dict] = {}

    async def __call__(self, request: ApprovalRequest) -> ApprovalDecision:
        future: asyncio.Future[ApprovalDecision] = asyncio.get_running_loop().create_future()
        self.pending[request.id] = {
            "request": request,
            "future": future,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        try:
            return await asyncio.wait_for(future, self.timeout)
        except asyncio.TimeoutError:
            return ApprovalDecision(approved=False, reason=f"No human answer within {int(self.timeout // 60)} minutes.")
        finally:
            self.pending.pop(request.id, None)

    def decide(self, approval_id: str, decision: ApprovalDecision) -> bool:
        item = self.pending.get(approval_id)
        if item is None or item["future"].done():
            return False
        item["future"].set_result(decision)
        return True

    def cancel_all(self, reason: str) -> None:
        for item in list(self.pending.values()):
            if not item["future"].done():
                item["future"].set_result(ApprovalDecision(approved=False, reason=reason))
