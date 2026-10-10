# Campus Customs MCP server

The shared tool server for the Campus Customs agent team (Boss, Inventory, Accounting, Facilities, Customer Service). Every agent calls these tools instead of guessing, so every number they use comes from the database.

**Database:** `data/campus_customs_new.db` is the working copy. The original `data/campus_customs.db` is never touched. To point the server at another file, set the `CAMPUS_DB` environment variable. "Today" is read from `desk.date_today`.

## Tools

| Tool | What it does |
|---|---|
| `get_tickets(status="open", ticket_id=None)` | Reads tickets from the board, with their linked lease and invoice, plus the shop's "today". |
| `check_restock(sku, size, qty_needed)` | Shows stock on hand, how many we're short, the supplier, lead time, restock cost, and anything blocking a restock, such as an unpaid invoice. |
| `manage_payables(action="list", as_of=None)` | Lists every unpaid bill (vendor invoices and lease rent) with days overdue, most urgent first, plus the cash balance. |
| `manage_payables(action="pay", kind, ref_id, amount=None, approved_by)` | Pays one invoice or rent bill. **Needs a human approver.** Refuses if cash would go negative. Updates `payments`, `cash_accounts`, and `invoices` or `leases`. |
| `quote_bulk_order(sku, size, qty, discount_pct=None)` | Shows profit per item and in total, the biggest discount that keeps a 40% margin, and how many can ship now versus need a restock. |
| `place_purchase_order(vendor_id, sku, size, qty, approved_by)` | Prepays a restock order. **Needs a human approver.** Refused while the vendor has an unpaid invoice or if cash would go negative. |
| `record_discount(ticket_id, sku, discount_pct, approved_by)` | Records a discount on a ticket. **Needs a human approver.** Refused if it would go under the 40% margin. |
| `save_draft(ticket_id, recipient, subject, body)` | Saves a message on the ticket as a draft. Nothing is ever sent. |
| `update_ticket(ticket_id, status, note)` | Sets the ticket status and adds a dated note. |

`approved_by` must name a human; agent names are rejected. In the agent harness, a human is asked y/N before any of the gated calls run, and their name is filled in for them.

## Run

```bash
pip install -r requirements.txt
python mcp_server/server.py
```

The server uses stdio transport. Claude Code connects to it through `.mcp.json`.
