"""Run the Campus Customs agent team over the open tickets (command line).

    python backend/run_tickets.py --reset                 # fresh DB, all open tickets, ask a human for approvals
    python backend/run_tickets.py --ticket 102            # one ticket on the current DB
    python backend/run_tickets.py --reset --approval deny # dry run: every approval is denied

Shop data is read and written only through the MCP server
(mcp_server/server.py) over data/campus_customs_new.db.
The web board uses the same team through backend/main.py.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

from pydantic_ai.usage import RunUsage  # noqa: E402

from agents.approvals import DenyAllApprover, TerminalApprover  # noqa: E402
from agents.audit import AuditTrail  # noqa: E402
from agents.config import (  # noqa: E402
    DB_ORIGINAL, DB_WORKING, MAX_HANDOFF_DEPTH, MAX_HANDOFFS_PER_TICKET, MODEL_NAME,
    RUN_TOKEN_LIMIT, TICKET_REQUEST_LIMIT, TICKET_TOKEN_LIMIT, TICKET_TOOL_CALL_LIMIT,
    require_api_key,
)
from agents.runner import work_ticket  # noqa: E402
from agents.team import build_mcp, usage_dict  # noqa: E402

LIMITS = {
    "ticket_tokens": TICKET_TOKEN_LIMIT, "ticket_requests": TICKET_REQUEST_LIMIT,
    "ticket_tool_calls": TICKET_TOOL_CALL_LIMIT, "run_tokens": RUN_TOKEN_LIMIT,
    "handoff_depth": MAX_HANDOFF_DEPTH, "handoffs_per_ticket": MAX_HANDOFFS_PER_TICKET,
}


def reset_db(audit: AuditTrail) -> None:
    shutil.copyfile(DB_ORIGINAL, DB_WORKING)
    audit.log("db_reset", source=DB_ORIGINAL.name, target=DB_WORKING.name)
    print(f"Reset {DB_WORKING.name} from {DB_ORIGINAL.name}.")


def print_result(out: dict) -> None:
    print(f"Status: {out['status']}")
    res = out["resolution"]
    if not res:
        print(out["note"])
    else:
        print(f"Decision: {res['decision']}")
        for a in res["actions_taken"]:
            print(f"  done: {a}")
        for a in res["pending_approvals"]:
            print(f"  approval ({a['status']}): {a['summary']}")
        for s in res["next_steps"]:
            print(f"  next: {s}")
    u = out["usage"]
    print(f"Tokens: {u['total_tokens']:,} ({u['requests']} model calls, {u['tool_calls']} tool calls)")


async def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--reset", action="store_true", help="copy campus_customs.db over campus_customs_new.db first")
    p.add_argument("--ticket", type=int, action="append", help="only these ticket ids (repeatable)")
    p.add_argument("--approval", choices=["ask", "deny"], default="ask", help="ask a human (default) or deny everything")
    args = p.parse_args()

    require_api_key()
    audit = AuditTrail()
    if args.reset:
        reset_db(audit)
    approver = TerminalApprover() if args.approval == "ask" else DenyAllApprover()

    mcp = build_mcp()
    run_usage = RunUsage()
    results = []
    async with mcp:
        board = await mcp.direct_call_tool("get_tickets", {"status": "all" if args.ticket else "open"})
        audit.shop_date = board["date_today"]
        tickets = [t for t in board["tickets"] if not args.ticket or t["id"] in args.ticket]
        audit.log("run_start", source="cli", model=MODEL_NAME, approval_mode=args.approval,
                  reset=args.reset, tickets=[t["id"] for t in tickets], limits=LIMITS)
        print(f"Shop date {board['date_today']} | {len(tickets)} ticket(s) | model {MODEL_NAME} | approvals: {args.approval}")

        for ticket in tickets:
            tid = ticket["id"]
            if run_usage.total_tokens >= RUN_TOKEN_LIMIT:
                audit.log("limit_hit", ticket_id=tid, limit="run_tokens", used=run_usage.total_tokens)
                print(f"\nTicket {tid}: skipped, run token limit ({RUN_TOKEN_LIMIT:,}) reached.")
                results.append((tid, "skipped", 0))
                continue

            print(f"\n--- Ticket {tid}: {ticket['subject']} ({ticket['type']}, {ticket['requester']}) ---")
            out = await work_ticket(ticket, mcp, audit, approver)
            print_result(out)
            u = out["usage"]
            run_usage.incr(RunUsage(requests=u["requests"], tool_calls=u["tool_calls"],
                                    input_tokens=u["input_tokens"], output_tokens=u["output_tokens"]))
            results.append((tid, out["status"], u["total_tokens"]))

    audit.log("run_end", results=results, usage=usage_dict(run_usage))
    print(f"\nRun {audit.run_id} done. Total tokens: {run_usage.total_tokens:,}. Audit: {audit.path}")


if __name__ == "__main__":
    asyncio.run(main())
