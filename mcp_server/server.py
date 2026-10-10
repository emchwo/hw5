"""Campus Customs MCP server.

Shared tool server for every agent on the team (Boss, Inventory, Accounting,
Facilities, Customer Service). All data comes from the working database
data/campus_customs_new.db; nothing is invented. If a value is not in the
database the tool says so instead of guessing.

Read tools:   get_tickets, check_restock, manage_payables(action="list"),
              quote_bulk_order
Write tools:  manage_payables(action="pay"), place_purchase_order,
              record_discount  -> each needs a human name in approved_by
              save_draft, update_ticket -> notes only, no money moves

Run:  python mcp_server/server.py          (stdio transport)
"""

from __future__ import annotations

import calendar
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

DB_PATH = Path(
    os.environ.get(
        "CAMPUS_DB",
        Path(__file__).resolve().parent.parent / "data" / "campus_customs_new.db",
    )
)

# Lowest margin the shop accepts on a sale, as a fraction of the selling price.
# Shop policy set by the owner (not stored in the database): keep at least 40%.
MIN_MARGIN_PCT = 0.40

# SKU product code -> keyword to match in vendors.specialty. Used only when no
# past invoice ties the SKU to a vendor.
SPECIALTY_KEYWORDS = {
    "HOOD": "apparel",
    "TEE": "apparel",
    "HAT": "apparel",
    "MUG": "mug",
}

# approved_by must name a human. These values are rejected so an agent can't
# "approve" its own payment.
NON_HUMAN_APPROVERS = {
    "", "boss", "inventory", "accounting", "facilities", "customer service",
    "customer_service", "agent", "ai", "assistant", "system", "bot", "auto",
    "gpt", "gpt-6-luna", "model",
}

TICKET_STATUSES = {"open", "in_progress", "waiting_approval", "blocked", "resolved"}

mcp = FastMCP(
    "campus-customs",
    instructions=(
        "Tools for the Campus Customs shop team. Every number comes from "
        "data/campus_customs_new.db. Read tools only report. Tools that move "
        "money or approve discounts require a human name in approved_by and "
        "refuse anything that would make cash negative. Messages are saved as "
        "drafts on the ticket and are never sent."
    ),
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
@contextmanager
def _connect_ro() -> Iterator[sqlite3.Connection]:
    if not DB_PATH.exists():
        raise ToolError(f"Database not found: {DB_PATH}")
    conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def _connect_rw() -> Iterator[sqlite3.Connection]:
    """One write transaction: commits on success, rolls back on any error."""
    if not DB_PATH.exists():
        raise ToolError(f"Database not found: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _today(conn: sqlite3.Connection) -> date:
    row = conn.execute("SELECT date_today FROM desk LIMIT 1").fetchone()
    if row is None:
        raise ToolError("desk.date_today is missing; cannot tell what 'today' is.")
    return date.fromisoformat(row["date_today"])


def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ToolError(f"{field} must be YYYY-MM-DD, got {value!r}") from exc


def _add_month(d: date) -> date:
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _require_human(approved_by: str | None) -> str:
    name = (approved_by or "").strip()
    if name.lower() in NON_HUMAN_APPROVERS:
        raise ToolError(
            "Refused: this action needs human approval. approved_by must be the "
            "name of the human who approved it."
        )
    return name


def _max_discount_pct(unit_cost: float, list_price: float) -> float:
    # Biggest d with (price*(1-d) - cost) / (price*(1-d)) >= MIN_MARGIN_PCT
    d = max(0.0, 1 - unit_cost / ((1 - MIN_MARGIN_PCT) * list_price))
    return int(d * 10000) / 100  # percent, rounded down to 0.01


def _get_ticket(conn: sqlite3.Connection, ticket_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if row is None:
        raise ToolError(f"Ticket {ticket_id} does not exist.")
    return row


def _append_note(conn: sqlite3.Connection, ticket_id: int, note: str) -> str:
    old = _get_ticket(conn, ticket_id)["notes"] or ""
    new = f"{old}\n\n{note}".strip()
    conn.execute("UPDATE tickets SET notes = ? WHERE id = ?", (new, ticket_id))
    return new


def _cash_account(conn: sqlite3.Connection, account: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM cash_accounts WHERE name = ?", (account,)).fetchone()
    if row is None:
        names = [r["name"] for r in conn.execute("SELECT name FROM cash_accounts")]
        raise ToolError(f"No cash account {account!r}. Accounts on file: {names}")
    return row


def _withdraw(
    conn: sqlite3.Connection, account: str, amount: float, today: date
) -> tuple[float, float]:
    """Take money out of an account, or refuse if it would go negative."""
    acct = _cash_account(conn, account)
    before = acct["balance"]
    if amount <= 0:
        raise ToolError("Payment amount must be positive.")
    if amount > before:
        raise ToolError(
            f"Refused: not enough cash. {account} has ${before:.2f} but this payment "
            f"is ${amount:.2f}. Balances may not go negative."
        )
    after = round(before - amount, 2)
    conn.execute(
        "UPDATE cash_accounts SET balance = ?, date = ? WHERE name = ?",
        (after, today.isoformat(), account),
    )
    return before, after


def _record_payment(
    conn: sqlite3.Connection, kind: str, ref_id: int, amount: float,
    account: str, today: date, approved_by: str,
) -> int:
    cur = conn.execute(
        """INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (kind, ref_id, amount, account, today.isoformat(), approved_by),
    )
    return cur.lastrowid


def _find_supplier(conn: sqlite3.Connection, sku: str) -> dict | None:
    """Find the vendor for a SKU, using only what the database shows."""
    # 1) Strongest evidence: a past invoice that names this SKU.
    row = conn.execute(
        """SELECT v.* FROM invoices i JOIN vendors v ON v.id = i.vendor_id
           WHERE i.description LIKE ? ORDER BY i.due_date DESC LIMIT 1""",
        (f"%{sku}%",),
    ).fetchone()
    if row:
        return {**dict(row), "match_basis": "past invoice names this SKU"}

    # 2) Otherwise match the product type against vendors.specialty.
    parts = sku.split("-")
    keyword = SPECIALTY_KEYWORDS.get(parts[1]) if len(parts) > 1 else None
    if keyword:
        row = conn.execute(
            "SELECT * FROM vendors WHERE lower(specialty) LIKE ? ORDER BY id LIMIT 1",
            (f"%{keyword}%",),
        ).fetchone()
        if row:
            return {**dict(row), "match_basis": f"vendor specialty matches '{keyword}'"}
    return None


def _open_invoices_for_vendor(
    conn: sqlite3.Connection, vendor_id: int, today: date
) -> list[dict]:
    rows = conn.execute(
        """SELECT id, amount, due_date, status, description FROM invoices
           WHERE vendor_id = ? AND lower(status) != 'paid' ORDER BY due_date""",
        (vendor_id,),
    ).fetchall()
    out = []
    for r in rows:
        days = (today - date.fromisoformat(r["due_date"])).days
        out.append(
            {
                "invoice_id": r["id"],
                "amount": r["amount"],
                "due_date": r["due_date"],
                "status": r["status"],
                "days_overdue": max(days, 0),
                "overdue": days > 0,
                "description": r["description"],
            }
        )
    return out


def _restock_report(conn: sqlite3.Connection, sku: str, size: str, qty_needed: int) -> dict:
    if qty_needed < 1:
        raise ToolError("qty_needed must be at least 1.")
    item = conn.execute(
        "SELECT * FROM inventory WHERE sku = ? AND size = ?", (sku, size)
    ).fetchone()
    if item is None:
        sizes = [
            r["size"]
            for r in conn.execute("SELECT size FROM inventory WHERE sku = ?", (sku,))
        ]
        if not sizes:
            skus = [r["sku"] for r in conn.execute("SELECT DISTINCT sku FROM inventory")]
            raise ToolError(f"SKU {sku!r} is not in inventory. SKUs on file: {skus}")
        raise ToolError(f"{sku} has no size {size!r}. Sizes on file: {sizes}")

    today = _today(conn)
    in_stock = item["qty"]
    short_by = max(qty_needed - in_stock, 0)

    supplier = _find_supplier(conn, sku)
    blockers: list[dict] = []
    if supplier:
        for inv in _open_invoices_for_vendor(conn, supplier["id"], today):
            blockers.append(
                {
                    "type": "unpaid_invoice",
                    **inv,
                    "reason": (
                        f"{supplier['name']} will not ship new product while invoice "
                        f"{inv['invoice_id']} (${inv['amount']:.2f}) is unpaid"
                        + (f"; it is {inv['days_overdue']} days overdue." if inv["overdue"] else ".")
                    ),
                }
            )
    elif short_by:
        blockers.append({"type": "no_supplier", "reason": f"No vendor on file can supply {sku}."})

    restock = None
    if short_by and supplier:
        unit_cost = conn.execute(
            "SELECT unit_cost FROM pricing WHERE sku = ?", (sku,)
        ).fetchone()
        restock = {
            "qty_to_order": short_by,
            "unit_cost": unit_cost["unit_cost"] if unit_cost else None,
            "order_cost": round(unit_cost["unit_cost"] * short_by, 2) if unit_cost else None,
            "lead_days": supplier["lead_days"],
            "earliest_arrival_if_ordered_today": (
                today + timedelta(days=supplier["lead_days"])
            ).isoformat(),
            "can_order_now": not blockers,
        }

    return {
        "as_of": today.isoformat(),
        "sku": sku,
        "name": item["name"],
        "size": size,
        "location": item["location"],
        "qty_needed": qty_needed,
        "in_stock": in_stock,
        "short_by": short_by,
        "restock_needed": short_by > 0,
        "supplier": (
            {
                "vendor_id": supplier["id"],
                "name": supplier["name"],
                "specialty": supplier["specialty"],
                "lead_days": supplier["lead_days"],
                "match_basis": supplier["match_basis"],
            }
            if supplier
            else None
        ),
        "restock": restock,
        "blockers": blockers,
        "note": "Report only. No order was placed.",
    }


def _list_payables(conn: sqlite3.Connection, as_of_date: date) -> dict:
    bills: list[dict] = []
    for r in conn.execute(
        """SELECT i.id, i.amount, i.due_date, i.status, i.description,
                  v.id AS vendor_id, v.name AS vendor
           FROM invoices i JOIN vendors v ON v.id = i.vendor_id
           WHERE lower(i.status) != 'paid'"""
    ):
        bills.append(
            {
                "kind": "invoice",
                "ref_id": r["id"],
                "payee": r["vendor"],
                "vendor_id": r["vendor_id"],
                "amount": r["amount"],
                "due_date": r["due_date"],
                "status": r["status"],
                "description": r["description"],
            }
        )
    for r in conn.execute("SELECT * FROM leases"):
        bills.append(
            {
                "kind": "rent",
                "ref_id": r["id"],
                "payee": r["landlord"],
                "amount": r["monthly_rent"],
                "due_date": r["next_due"],
                "status": "due",
                "description": f"Monthly rent: {r['space_name']}",
            }
        )

    for b in bills:
        days = (as_of_date - date.fromisoformat(b["due_date"])).days
        b["days_overdue"] = days
        b["urgency"] = (
            "overdue" if days > 0 else "due today" if days == 0 else f"due in {-days} days"
        )
    bills.sort(key=lambda b: (-b["days_overdue"], -b["amount"]))

    cash = [dict(r) for r in conn.execute("SELECT name, balance, date FROM cash_accounts")]
    total_due = round(sum(b["amount"] for b in bills), 2)
    total_cash = round(sum(c["balance"] for c in cash), 2)
    return {
        "as_of": as_of_date.isoformat(),
        "bills": bills,
        "bill_count": len(bills),
        "total_due": total_due,
        "cash_accounts": cash,
        "total_cash": total_cash,
        "cash_after_paying_all": round(total_cash - total_due, 2),
        "can_cover_all": total_cash >= total_due,
        "note": "Listing only. Any payment needs human approval first.",
    }


def _pay_bill(
    kind: str | None, ref_id: int | None, amount: float | None,
    account: str, approved_by: str | None,
) -> dict:
    approver = _require_human(approved_by)
    kind = (kind or "").strip().lower()
    if kind not in {"invoice", "rent"} or ref_id is None:
        raise ToolError("action 'pay' needs kind ('invoice' or 'rent') and ref_id.")

    with _connect_rw() as conn:
        today = _today(conn)
        if kind == "invoice":
            inv = conn.execute(
                """SELECT i.*, v.name AS vendor FROM invoices i
                   JOIN vendors v ON v.id = i.vendor_id WHERE i.id = ?""",
                (ref_id,),
            ).fetchone()
            if inv is None:
                raise ToolError(f"Invoice {ref_id} does not exist.")
            if inv["status"].lower() == "paid":
                raise ToolError(f"Invoice {ref_id} is already paid.")
            due, payee = inv["amount"], inv["vendor"]
        else:
            lease = conn.execute("SELECT * FROM leases WHERE id = ?", (ref_id,)).fetchone()
            if lease is None:
                raise ToolError(f"Lease {ref_id} does not exist.")
            due, payee = lease["monthly_rent"], lease["landlord"]

        if amount is not None and round(amount, 2) != round(due, 2):
            raise ToolError(
                f"Amount ${amount:.2f} does not match the ${due:.2f} owed on {kind} {ref_id}."
            )

        before, after = _withdraw(conn, account, due, today)
        payment_id = _record_payment(conn, kind, ref_id, due, account, today, approver)

        updated: dict = {"payments": f"row {payment_id} added", "cash_accounts": f"{account}: ${before:.2f} -> ${after:.2f}"}
        if kind == "invoice":
            conn.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (ref_id,))
            updated["invoices"] = f"invoice {ref_id} status open -> paid"
        else:
            old_due = date.fromisoformat(lease["next_due"])
            new_due = _add_month(old_due)
            conn.execute(
                "UPDATE leases SET next_due = ? WHERE id = ?", (new_due.isoformat(), ref_id)
            )
            updated["leases"] = f"lease {ref_id} next_due {old_due} -> {new_due}"

    return {
        "status": "paid",
        "payment_id": payment_id,
        "kind": kind,
        "ref_id": ref_id,
        "payee": payee,
        "amount": due,
        "account": account,
        "paid_at": today.isoformat(),
        "approved_by": approver,
        "balance_before": before,
        "balance_after": after,
        "tables_updated": updated,
    }


# --------------------------------------------------------------------------- #
# Tool: get_tickets
# --------------------------------------------------------------------------- #
@mcp.tool(annotations={"readOnlyHint": True})
def get_tickets(status: str = "open", ticket_id: int | None = None) -> dict:
    """Read tickets from the board, plus the shop's 'today' (desk.date_today).

    status: "open" (default), "all", or any ticket status. ticket_id returns
    just that ticket. Linked lease / invoice rows are included for context.
    """
    with _connect_ro() as conn:
        today = _today(conn)
        if ticket_id is not None:
            rows = [_get_ticket(conn, ticket_id)]
        elif status.strip().lower() == "all":
            rows = conn.execute("SELECT * FROM tickets ORDER BY created_at").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tickets WHERE status = ? ORDER BY created_at",
                (status.strip().lower(),),
            ).fetchall()

        tickets = []
        for r in rows:
            t = dict(r)
            if r["lease_id"] is not None:
                lease = conn.execute("SELECT * FROM leases WHERE id = ?", (r["lease_id"],)).fetchone()
                t["lease"] = dict(lease) if lease else None
            if r["invoice_id"] is not None:
                inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (r["invoice_id"],)).fetchone()
                t["invoice"] = dict(inv) if inv else None
            tickets.append(t)
        notes = conn.execute("SELECT notes FROM desk LIMIT 1").fetchone()["notes"]

    return {"date_today": today.isoformat(), "desk_notes": notes, "count": len(tickets), "tickets": tickets}


# --------------------------------------------------------------------------- #
# Tool: check_restock
# --------------------------------------------------------------------------- #
@mcp.tool(annotations={"readOnlyHint": True})
def check_restock(sku: str, size: str, qty_needed: int) -> dict:
    """Check stock for a SKU and size against the quantity needed.

    Returns how many are in stock, how many we are short, the supplier and its
    lead time, the restock cost, and anything blocking a restock (e.g. an
    unpaid or overdue invoice with that vendor). Does NOT place an order.
    """
    with _connect_ro() as conn:
        return _restock_report(conn, sku.strip().upper(), size.strip().upper(), qty_needed)


# --------------------------------------------------------------------------- #
# Tool: manage_payables
# --------------------------------------------------------------------------- #
@mcp.tool(annotations={"destructiveHint": True})
def manage_payables(
    action: str = "list",
    as_of: str | None = None,
    kind: str | None = None,
    ref_id: int | None = None,
    amount: float | None = None,
    account: str = "checking",
    approved_by: str | None = None,
) -> dict:
    """Work with the shop's unpaid bills (vendor invoices and lease rent).

    action "list": every unpaid bill with amount, due date, and days overdue
    as of `as_of` (YYYY-MM-DD, default desk.date_today), most urgent first.
    Negative days_overdue means the bill is due in that many days. Also shows
    the cash balance.

    action "pay": pay ONE bill. Needs kind ("invoice" or "rent"), ref_id
    (invoice id or lease id), and approved_by = the HUMAN who approved it.
    Pays the full amount owed (amount, if given, must match). Refuses if cash
    would go negative. Updates payments, cash_accounts, and the invoice status
    (-> paid) or the lease next_due (-> next month).
    """
    action = action.strip().lower()
    if action == "list":
        with _connect_ro() as conn:
            as_of_date = _parse_date(as_of, "as_of") if as_of else _today(conn)
            return _list_payables(conn, as_of_date)
    if action == "pay":
        return _pay_bill(kind, ref_id, amount, account, approved_by)
    raise ToolError(f"Unsupported action {action!r}. Supported: 'list', 'pay'.")


# --------------------------------------------------------------------------- #
# Tool: quote_bulk_order
# --------------------------------------------------------------------------- #
@mcp.tool(annotations={"readOnlyHint": True})
def quote_bulk_order(sku: str, size: str, qty: int, discount_pct: float | None = None) -> dict:
    """Quote a bulk order: profit per item and in total, the biggest discount
    allowed without going under the shop's lowest margin (40%), and how many
    can ship now vs. need a restock (with restock blockers from check_restock).

    discount_pct is optional, as a percent (e.g. 10 for 10%). Any discount is
    only a proposal: a human must approve it (record_discount) before it is offered.
    """
    sku, size = sku.strip().upper(), size.strip().upper()
    if qty < 1:
        raise ToolError("qty must be at least 1.")
    if discount_pct is not None and not 0 <= discount_pct < 100:
        raise ToolError("discount_pct must be between 0 and 100.")

    with _connect_ro() as conn:
        price_row = conn.execute("SELECT * FROM pricing WHERE sku = ?", (sku,)).fetchone()
        if price_row is None:
            raise ToolError(f"No pricing on file for {sku!r}.")
        stock = _restock_report(conn, sku, size, qty)

    cost, list_price = price_row["unit_cost"], price_row["list_price"]
    d = (discount_pct or 0) / 100
    unit_price = round(list_price * (1 - d), 2)
    unit_profit = round(unit_price - cost, 2)
    margin = unit_profit / unit_price if unit_price else 0.0
    max_discount_pct = _max_discount_pct(cost, list_price)

    if not discount_pct:
        approval = {"required": False, "status": "no_discount_requested"}
    elif discount_pct > max_discount_pct:
        approval = {
            "required": True,
            "status": "not_allowed",
            "reason": (
                f"{discount_pct}% goes under the {MIN_MARGIN_PCT:.0%} minimum margin; "
                f"the most we can give is {max_discount_pct}%."
            ),
        }
    else:
        approval = {
            "required": True,
            "status": "pending_human_approval",
            "reason": "Discount is within margin but a human must approve it before it is offered.",
        }

    return {
        "sku": sku,
        "name": stock["name"],
        "size": size,
        "qty": qty,
        "pricing": {
            "unit_cost": cost,
            "list_price": list_price,
            "discount_pct": discount_pct or 0,
            "unit_price": unit_price,
            "profit_per_item": unit_profit,
            "margin_pct": round(margin * 100, 2),
            "order_total": round(unit_price * qty, 2),
            "total_profit": round(unit_profit * qty, 2),
        },
        "max_discount": {
            "max_discount_pct": max_discount_pct,
            "min_margin_pct": MIN_MARGIN_PCT * 100,
            "unit_price_at_max": round(list_price * (1 - max_discount_pct / 100), 2),
        },
        "discount_approval": approval,
        "fulfillment": {
            "in_stock": stock["in_stock"],
            "can_ship_now": min(stock["in_stock"], qty),
            "needs_restock": stock["short_by"],
            "supplier": stock["supplier"],
            "restock": stock["restock"],
            "blockers": stock["blockers"],
        },
        "note": "Quote only. No discount applied and no order placed.",
    }


# --------------------------------------------------------------------------- #
# Tool: place_purchase_order  (needs human approval)
# --------------------------------------------------------------------------- #
@mcp.tool(annotations={"destructiveHint": True})
def place_purchase_order(
    vendor_id: int, sku: str, size: str, qty: int,
    approved_by: str | None = None, account: str = "checking",
) -> dict:
    """Prepay a restock purchase order with a vendor. NEEDS HUMAN APPROVAL.

    Cost = pricing.unit_cost x qty. Refuses if the vendor still has an open
    unpaid invoice (they won't ship) or if cash would go negative. Records a
    paid invoice + a payment row and lowers the cash balance. Stock is NOT
    added now; it arrives after vendors.lead_days. The vendor is not contacted:
    any message to them stays a draft (save_draft).
    """
    approver = _require_human(approved_by)
    sku, size = sku.strip().upper(), size.strip().upper()
    if qty < 1:
        raise ToolError("qty must be at least 1.")

    with _connect_rw() as conn:
        today = _today(conn)
        vendor = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if vendor is None:
            raise ToolError(f"Vendor {vendor_id} does not exist.")
        if conn.execute(
            "SELECT 1 FROM inventory WHERE sku = ? AND size = ?", (sku, size)
        ).fetchone() is None:
            raise ToolError(f"{sku} size {size} is not in inventory.")
        price = conn.execute("SELECT unit_cost FROM pricing WHERE sku = ?", (sku,)).fetchone()
        if price is None:
            raise ToolError(f"No unit cost on file for {sku}.")
        open_inv = _open_invoices_for_vendor(conn, vendor_id, today)
        if open_inv:
            ids = [i["invoice_id"] for i in open_inv]
            raise ToolError(
                f"Refused: {vendor['name']} has open unpaid invoice(s) {ids} and will not "
                "ship new product until they are paid."
            )

        cost = round(price["unit_cost"] * qty, 2)
        eta = today + timedelta(days=vendor["lead_days"])
        before, after = _withdraw(conn, account, cost, today)
        cur = conn.execute(
            """INSERT INTO invoices (vendor_id, amount, due_date, status, description)
               VALUES (?, ?, ?, 'paid', ?)""",
            (vendor_id, cost, today.isoformat(),
             f"PO restock {sku} {size} x{qty} (prepaid, ETA {eta.isoformat()})"),
        )
        invoice_id = cur.lastrowid
        payment_id = _record_payment(
            conn, "purchase_order", invoice_id, cost, account, today, approver
        )

    return {
        "status": "ordered",
        "vendor": vendor["name"],
        "sku": sku,
        "size": size,
        "qty": qty,
        "unit_cost": price["unit_cost"],
        "total_cost": cost,
        "expected_arrival": eta.isoformat(),
        "approved_by": approver,
        "balance_before": before,
        "balance_after": after,
        "tables_updated": {
            "invoices": f"row {invoice_id} added (status paid)",
            "payments": f"row {payment_id} added",
            "cash_accounts": f"{account}: ${before:.2f} -> ${after:.2f}",
        },
        "note": "Inventory is unchanged until the stock arrives. Vendor was not contacted.",
    }


# --------------------------------------------------------------------------- #
# Tool: record_discount  (needs human approval)
# --------------------------------------------------------------------------- #
@mcp.tool(annotations={"destructiveHint": False})
def record_discount(
    ticket_id: int, sku: str, discount_pct: float, approved_by: str | None = None
) -> dict:
    """Record a human-approved discount on a ticket. NEEDS HUMAN APPROVAL.

    Refuses any discount that would push the margin under 40%. No money moves;
    the approved price is written to the ticket notes.
    """
    approver = _require_human(approved_by)
    sku = sku.strip().upper()
    if not 0 < discount_pct < 100:
        raise ToolError("discount_pct must be between 0 and 100.")

    with _connect_rw() as conn:
        _get_ticket(conn, ticket_id)
        price = conn.execute("SELECT * FROM pricing WHERE sku = ?", (sku,)).fetchone()
        if price is None:
            raise ToolError(f"No pricing on file for {sku!r}.")
        max_pct = _max_discount_pct(price["unit_cost"], price["list_price"])
        if discount_pct > max_pct:
            raise ToolError(
                f"Refused: {discount_pct}% would go under the {MIN_MARGIN_PCT:.0%} minimum "
                f"margin. The most allowed on {sku} is {max_pct}%."
            )
        unit_price = round(price["list_price"] * (1 - discount_pct / 100), 2)
        margin = round((unit_price - price["unit_cost"]) / unit_price * 100, 2)
        today = _today(conn)
        _append_note(
            conn, ticket_id,
            f"[{today}] APPROVED DISCOUNT: {discount_pct}% off {sku} -> ${unit_price:.2f}/unit "
            f"(margin {margin}%), approved by {approver}.",
        )

    return {
        "status": "discount_recorded",
        "ticket_id": ticket_id,
        "sku": sku,
        "discount_pct": discount_pct,
        "unit_price": unit_price,
        "margin_pct": margin,
        "approved_by": approver,
        "tables_updated": {"tickets": f"ticket {ticket_id} notes"},
    }


# --------------------------------------------------------------------------- #
# Tool: save_draft
# --------------------------------------------------------------------------- #
@mcp.tool(annotations={"destructiveHint": False})
def save_draft(ticket_id: int, recipient: str, subject: str, body: str) -> dict:
    """Save a draft message (to a customer, vendor, or landlord) on a ticket.

    Drafts stay on the board for a human to review. Nothing is ever sent.
    """
    if not body.strip():
        raise ToolError("Draft body is empty.")
    with _connect_rw() as conn:
        today = _today(conn)
        _append_note(
            conn, ticket_id,
            f"[{today}] DRAFT (not sent) to {recipient.strip()} | Subject: {subject.strip()}\n"
            f"{body.strip()}",
        )
    return {
        "status": "draft_saved",
        "ticket_id": ticket_id,
        "recipient": recipient,
        "subject": subject,
        "sent": False,
        "tables_updated": {"tickets": f"ticket {ticket_id} notes"},
    }


# --------------------------------------------------------------------------- #
# Tool: update_ticket
# --------------------------------------------------------------------------- #
@mcp.tool(annotations={"destructiveHint": False})
def update_ticket(ticket_id: int, status: str, note: str) -> dict:
    """Set a ticket's status and append a dated note to it.

    status: open, in_progress, waiting_approval, blocked, or resolved.
    """
    status = status.strip().lower()
    if status not in TICKET_STATUSES:
        raise ToolError(f"status must be one of {sorted(TICKET_STATUSES)}.")
    with _connect_rw() as conn:
        today = _today(conn)
        old = _get_ticket(conn, ticket_id)["status"]
        conn.execute("UPDATE tickets SET status = ? WHERE id = ?", (status, ticket_id))
        _append_note(conn, ticket_id, f"[{today}] {status.upper()}: {note.strip()}")
    return {
        "ticket_id": ticket_id,
        "status_before": old,
        "status_after": status,
        "tables_updated": {"tickets": f"ticket {ticket_id} status + notes"},
    }


if __name__ == "__main__":
    mcp.run(show_banner=False)
