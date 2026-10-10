"""The Campus Customs agent team: Boss + four specialists, all on gpt-6-luna.

- One MCP connection (mcp_server/server.py over data/campus_customs_new.db)
  is shared by every agent. Each agent sees only the tools in TOOL_ACCESS.
- Every MCP call goes through `_process_tool_call`, which writes the audit
  trail and holds money / discount calls until a human approves them.
- `hand_off(to_agent, task)` lets any agent ask any other agent for help.
  Usage is shared, so one ticket's token budget covers every agent on it.
- Every agent-loop step (prompt, model request, model response, end) is
  appended to output/audit_trail.json.
"""

from __future__ import annotations

import asyncio
import copy
import json
import sys
from dataclasses import dataclass, field, replace
from typing import Any

from fastmcp.client.transports import PythonStdioTransport
from pydantic_ai import Agent, RunContext
from pydantic_ai.mcp import CallToolFunc, MCPToolset
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import RunUsage

from models import AgentName, AgentReport, ApprovalRequest, TicketResolution

from .approvals import Approver
from .audit import AuditTrail
from .config import (
    AGENT_RETRIES,
    DB_WORKING,
    GATED_TOOLS,
    MAX_HANDOFF_DEPTH,
    MAX_HANDOFFS_PER_TICKET,
    MCP_SERVER,
    MODEL_NAME,
    MONEY_AGENTS,
    TOOL_ACCESS,
    build_model,
    load_prompt,
    ticket_usage_limits,
)


# --------------------------------------------------------------------------- #
# Shared state
# --------------------------------------------------------------------------- #
@dataclass
class TicketState:
    """Shared by every agent working one ticket."""

    ticket: dict[str, Any]
    audit: AuditTrail
    approver: Approver
    handoffs: int = 0
    denied: dict[str, str] = field(default_factory=dict)  # approval key -> reason
    done: dict[str, Any] = field(default_factory=dict)  # approval key -> result of the approved call
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)  # approval key -> one request at a time

    def lock_for(self, key: str) -> asyncio.Lock:
        return self.locks.setdefault(key, asyncio.Lock())

    @property
    def ticket_id(self) -> int:
        return self.ticket["id"]


@dataclass
class TeamDeps:
    agent: AgentName
    depth: int
    chain: tuple[AgentName, ...]
    state: TicketState

    def log(self, event: str, **data: Any) -> None:
        self.state.audit.log(event, ticket_id=self.state.ticket_id, agent=self.agent, depth=self.depth, **data)


# --------------------------------------------------------------------------- #
# MCP: one connection, approval gate, audit
# --------------------------------------------------------------------------- #
def _is_gated(name: str, args: dict[str, Any]) -> bool:
    if name == "manage_payables":
        return str(args.get("action", "list")).strip().lower() == "pay"
    return name in GATED_TOOLS


def _approval_key(name: str, args: dict[str, Any]) -> str:
    """Identify a gated action by what it does, not by how the model spelled the arguments.

    Two agents asking for the same payment / order / discount (e.g. 10 vs 10.0,
    lowercase SKU, with or without `amount`) map to the same key, so the human
    is only asked once.
    """
    def up(v: Any) -> str:
        return str(v or "").strip().upper()

    def num(v: Any) -> float | None:
        try:
            return round(float(v), 2)
        except (TypeError, ValueError):
            return None

    if name == "manage_payables":
        what = {"kind": str(args.get("kind", "")).strip().lower(), "ref_id": num(args.get("ref_id"))}
    elif name == "place_purchase_order":
        what = {"vendor_id": num(args.get("vendor_id")), "sku": up(args.get("sku")),
                "size": up(args.get("size")), "qty": num(args.get("qty"))}
    elif name == "record_discount":
        what = {"ticket_id": num(args.get("ticket_id")), "sku": up(args.get("sku")),
                "discount_pct": num(args.get("discount_pct"))}
    else:
        what = args
    return f"{name}:{json.dumps(what, sort_keys=True, default=str)}"


async def _build_approval_request(
    deps: TeamDeps, call_tool: CallToolFunc, name: str, args: dict[str, Any]
) -> ApprovalRequest:
    """Describe the request in plain words, with amounts read from MCP (not the model)."""
    amount = payee = None
    if name == "manage_payables":
        kind, ref = args.get("kind"), args.get("ref_id")
        bills = (await call_tool("manage_payables", {"action": "list"}))["bills"]
        bill = next((b for b in bills if b["kind"] == kind and b["ref_id"] == ref), None)
        if bill:
            amount, payee = bill["amount"], bill["payee"]
            summary = f"Pay {kind} {ref}: ${amount:,.2f} to {payee} (due {bill['due_date']}, {bill['urgency']})"
        else:
            summary = f"Pay {kind} {ref} (not found in unpaid bills; the tool will refuse)"
        kind_label = "payment"
    elif name == "place_purchase_order":
        stock = await call_tool(
            "check_restock", {"sku": args["sku"], "size": args["size"], "qty_needed": 1}
        )
        unit = (stock.get("restock") or {}).get("unit_cost")
        if unit is None:
            quote = await call_tool("quote_bulk_order", {"sku": args["sku"], "size": args["size"], "qty": 1})
            unit = quote["pricing"]["unit_cost"]
        amount = round(unit * int(args["qty"]), 2)
        payee = (stock.get("supplier") or {}).get("name")
        summary = (
            f"Prepaid restock order: {args['qty']} x {args['sku']} size {args['size']} "
            f"from vendor {args['vendor_id']} ({payee}) at ${unit:.2f} each"
        )
        kind_label = "purchase_order"
    else:  # record_discount
        summary = (
            f"Approve a {args.get('discount_pct')}% discount on {args.get('sku')} "
            f"for ticket {args.get('ticket_id')}"
        )
        kind_label = "discount"
    return ApprovalRequest(
        kind=kind_label, tool=name, requested_by=deps.agent, ticket_id=deps.state.ticket_id,
        amount=amount, payee=payee, summary=summary, args=args,
    )


async def _process_tool_call(
    ctx: RunContext[TeamDeps], call_tool: CallToolFunc, name: str, args: dict[str, Any]
) -> Any:
    deps = ctx.deps
    args = {k: v for k, v in args.items() if k != "approved_by"}  # only a human sets this
    deps.log("tool_call", tool=name, args=args)

    if _is_gated(name, args):
        if deps.agent not in MONEY_AGENTS:
            result = {
                "status": "refused",
                "reason": f"Only {sorted(MONEY_AGENTS)} can request payments, orders, or discounts. Hand off to accounting.",
            }
            deps.log("tool_result", tool=name, result=result)
            return result

        key = _approval_key(name, args)
        async with deps.state.lock_for(key):  # a duplicate waits here until the first is answered
            if key in deps.state.done:
                result = {"status": "already_done", "note": "This exact action was already approved and carried out on this ticket. Not asking or doing it again.", "result": deps.state.done[key]}
                deps.log("tool_result", tool=name, result=result)
                return result
            if key in deps.state.denied:
                result = {"status": "denied_by_human", "reason": deps.state.denied[key], "note": "Already denied on this ticket; not asking again."}
                deps.log("tool_result", tool=name, result=result)
                return result

            request = await _build_approval_request(deps, call_tool, name, args)
            deps.log("approval_requested", request=request.model_dump())
            decision = await deps.state.approver(request)
            deps.log("approval_decision", tool=name, decision=decision.model_dump())
            if not decision.approved:
                deps.state.denied[key] = decision.reason or "Denied by human."
                result = {"status": "denied_by_human", "reason": deps.state.denied[key], "note": "Nothing was paid or changed."}
                deps.log("tool_result", tool=name, result=result)
                return result

            try:
                result = await _call_and_log(deps, call_tool, name, {**args, "approved_by": decision.approver})
            except Exception as exc:
                # Approved but the tool refused (e.g. not enough cash): don't ask the human again for it.
                deps.state.denied[key] = f"Approved by {decision.approver}, but the tool refused: {exc}"
                raise
            deps.state.done[key] = result
            return result

    return await _call_and_log(deps, call_tool, name, args)


async def _call_and_log(deps: TeamDeps, call_tool: CallToolFunc, name: str, args: dict[str, Any]) -> Any:
    try:
        result = await call_tool(name, args)
    except Exception as exc:
        deps.log("tool_result", tool=name, error=f"{type(exc).__name__}: {exc}")
        raise
    deps.log("tool_result", tool=name, result=result)
    return result


def build_mcp() -> MCPToolset:
    """The single MCP connection. The runner opens it once with `async with`."""
    transport = PythonStdioTransport(
        MCP_SERVER,
        python_cmd=sys.executable,
        env={"CAMPUS_DB": str(DB_WORKING), "FASTMCP_LOG_LEVEL": "WARNING", "PYTHONIOENCODING": "utf-8"},
    )
    return MCPToolset(transport, process_tool_call=_process_tool_call, max_retries=AGENT_RETRIES)


def _hide_approved_by(ctx: RunContext[TeamDeps], defs: list[ToolDefinition]) -> list[ToolDefinition]:
    """Remove approved_by from every schema so a model can't even try to fill it in."""
    out = []
    for d in defs:
        schema = copy.deepcopy(d.parameters_json_schema)
        schema.get("properties", {}).pop("approved_by", None)
        if "required" in schema:
            schema["required"] = [r for r in schema["required"] if r != "approved_by"]
        out.append(replace(d, parameters_json_schema=schema))
    return out


def toolset_for(mcp: MCPToolset, agent: AgentName):
    allowed = TOOL_ACCESS[agent]
    return mcp.filtered(lambda ctx, td: td.name in allowed).prepared(_hide_approved_by)


# --------------------------------------------------------------------------- #
# Hand-offs
# --------------------------------------------------------------------------- #
async def hand_off(ctx: RunContext[TeamDeps], to_agent: AgentName, task: str) -> dict[str, Any]:
    """Hand part of the work to a teammate and get their report back.

    Args:
        to_agent: inventory, accounting, facilities, customer_service, or boss.
        task: A self-contained request with the ticket id, SKU, size, qty, amounts, etc.
    """
    deps = ctx.deps
    state = deps.state

    refusal = None
    if to_agent == deps.agent:
        refusal = "You cannot hand off to yourself."
    elif to_agent in deps.chain:
        refusal = f"{to_agent} is already working on this request (chain: {' -> '.join(deps.chain)}). Put it in your report instead."
    elif deps.depth + 1 > MAX_HANDOFF_DEPTH:
        refusal = f"Hand-off depth limit ({MAX_HANDOFF_DEPTH}) reached. Do the work yourself or report back."
    elif state.handoffs >= MAX_HANDOFFS_PER_TICKET:
        refusal = f"Hand-off limit ({MAX_HANDOFFS_PER_TICKET} per ticket) reached. Report back with what you have."
    if refusal:
        deps.log("handoff_end", to_agent=to_agent, task=task, status="refused", reason=refusal)
        return {"status": "refused", "reason": refusal}

    state.handoffs += 1
    child = TeamDeps(agent=to_agent, depth=deps.depth + 1, chain=(*deps.chain, to_agent), state=state)
    deps.log("handoff_start", to_agent=to_agent, task=task, handoff_number=state.handoffs)
    prompt = (
        f"TICKET (from the board):\n{json.dumps(state.ticket, indent=1, default=str)}\n\n"
        f"TASK FROM {deps.agent.upper()}:\n{task}"
    )
    output = await run_agent(to_agent, prompt, child, usage=ctx.usage)
    report = output.model_dump()
    deps.log("handoff_end", to_agent=to_agent, status="done", report=report)
    return report


# --------------------------------------------------------------------------- #
# Agents and the traced agent loop
# --------------------------------------------------------------------------- #
_agents: dict[str, Agent] = {}


def get_agent(name: AgentName, mcp: MCPToolset) -> Agent[TeamDeps, Any]:
    if name not in _agents:
        agent = Agent(
            build_model(),
            deps_type=TeamDeps,
            output_type=TicketResolution if name == "boss" else AgentReport,
            instructions=load_prompt(name),
            toolsets=[toolset_for(mcp, name)],
            retries=AGENT_RETRIES,
            name=name,
        )
        agent.tool(hand_off)
        _agents[name] = agent
    return _agents[name]


_mcp_ref: dict[str, MCPToolset] = {}


def _parts(parts: list[Any]) -> list[dict[str, Any]]:
    out = []
    for p in parts:
        kind = getattr(p, "part_kind", type(p).__name__)
        if kind in ("system-prompt",):
            continue
        item: dict[str, Any] = {"kind": kind}
        for attr in ("tool_name", "tool_call_id", "args", "content"):
            v = getattr(p, attr, None)
            if v not in (None, ""):
                if attr == "args" and isinstance(v, str):
                    try:
                        v = json.loads(v)
                    except json.JSONDecodeError:
                        pass
                item[attr] = v if isinstance(v, (str, int, float, dict, list, bool)) else str(v)
        out.append(item)
    return out


def _describe(node: Any) -> dict[str, Any]:
    if Agent.is_user_prompt_node(node):
        return {"step": "user_prompt", "prompt": node.user_prompt}
    if Agent.is_model_request_node(node):
        return {"step": "model_request", "parts": _parts(node.request.parts)}
    if Agent.is_call_tools_node(node):
        r = node.model_response
        u = r.usage
        return {
            "step": "model_response",
            "model": r.model_name,
            "finish_reason": r.finish_reason,
            "parts": _parts(r.parts),
            "usage": {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens},
        }
    if Agent.is_end_node(node):
        out = node.data.output
        return {"step": "end", "stop_reason": "final_output", "output": out.model_dump() if hasattr(out, "model_dump") else out}
    return {"step": type(node).__name__}


def usage_dict(u: RunUsage) -> dict[str, int]:
    return {
        "requests": u.requests,
        "tool_calls": u.tool_calls,
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "total_tokens": u.total_tokens,
    }


async def run_agent(name: AgentName, prompt: str, deps: TeamDeps, usage: RunUsage) -> Any:
    """Run one agent loop node by node, logging every step to the audit trail."""
    agent = get_agent(name, _mcp_ref["mcp"])
    deps.log("agent_start", model=MODEL_NAME, chain=list(deps.chain), prompt=prompt)
    try:
        async with agent.iter(prompt, deps=deps, usage=usage, usage_limits=ticket_usage_limits()) as run:
            async for node in run:
                deps.log("agent_step", **_describe(node))
    except Exception as exc:
        deps.log("error", where=f"{name} agent loop", error=f"{type(exc).__name__}: {exc}", usage_so_far=usage_dict(usage))
        raise
    output = run.result.output
    deps.log("agent_end", stop_reason="final_output", output=output.model_dump(), usage_so_far=usage_dict(usage))
    return output


async def run_ticket(
    ticket: dict[str, Any], mcp: MCPToolset, audit: AuditTrail, approver: Approver, usage: RunUsage
) -> TicketResolution:
    """Boss works one ticket (handing off as needed) and returns the final call."""
    _mcp_ref["mcp"] = mcp
    state = TicketState(ticket=ticket, audit=audit, approver=approver)
    deps = TeamDeps(agent="boss", depth=0, chain=("boss",), state=state)
    prompt = (
        f"Work this ticket and make the final call.\n\n"
        f"TICKET (from the board):\n{json.dumps(ticket, indent=1, default=str)}"
    )
    return await run_agent("boss", prompt, deps, usage=usage)
