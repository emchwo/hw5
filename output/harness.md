# HW 5 — Campus Customs Multi-Agent Harness

## System at a glance

| Layer | What it is | Details |
|---|---|---|
| **Data** | SQLite: `data/campus_customs_new.db` (working copy); `data/campus_customs.db` is never changed and is the reset source | 9 tables: `desk`, `tickets`, `inventory`, `pricing`, `vendors`, `invoices`, `leases`, `cash_accounts`, `payments` (Problem 2) |
| **MCP server** | `mcp_server/server.py` (FastMCP, stdio), the only path to shop data | 8 tools: `get_tickets`, `check_restock`, `manage_payables` (`list` / `pay`), `quote_bulk_order`, `place_purchase_order`, `record_discount`, `save_draft`, `update_ticket` (Problems 3 and 5) |
| **Agents** | 5 PydanticAI agents on **gpt-6-luna** via Portkey, in `backend/` | Boss, Inventory, Accounting, Facilities, Customer Service; any agent can `hand_off` to any other (Problem 5) |
| **API** | FastAPI, `backend/main.py`, `uvicorn main:app --reload --port 8000` | 9 routes for tickets, runs, events, approvals, cash, and reset (Problem 7) |
| **Dashboard** | React + Vite, `frontend/`, `npm run dev`, http://localhost:5173 | Club Penguin–style Secret Agent HQ: one screen per agent, live feed, approval pop-up, coin-vault balance (Problem 8, `output/design.md`) |
| **Safety** | Human approval gate, 40% margin floor, drafts only, token and hand-off limits, append-only audit trail | See **Safety** below |

## Problem 2: Study the Campus Customs database

The agents read and update the working copy `data/campus_customs_new.db`. The original `data/campus_customs.db` is never modified, so it can be used to reset the working copy.

### `desk`
- `date_today`: the shop's "today" (`2026-08-31`)
- `notes`

**Why it matters:** Every agent uses `date_today` to decide what is overdue or coming due.

### `tickets`
- `id`
- `type`: `customer_order`, `rent_notice`, or `price_override`
- `requester`
- `subject`
- `sku`, `size`, `qty`
- `lease_id` → `leases.id`
- `invoice_id` → `invoices.id`
- `status`
- `notes`
- `created_at`

**Why it matters:** This is the Boss's work queue, and each ticket's links tell the Boss which agents to involve.

### `inventory`
- `sku`, `size`: primary key
- `name`
- `qty`
- `location`

**Why it matters:** Inventory checks stock here by SKU and size to spot shortfalls before an order is promised.

### `pricing`
- `sku`: primary key
- `unit_cost`
- `list_price`

**Why it matters:** Accounting uses cost and price to check margins before approving a discount or an order.

### `vendors`
- `id`: primary key
- `name`
- `specialty`
- `lead_days`

**Why it matters:** Inventory picks a restock vendor by specialty and uses `lead_days` to estimate when stock arrives.

### `invoices`
- `id`: primary key
- `vendor_id` → `vendors.id`
- `amount`
- `due_date`
- `status`
- `description`

**Why it matters:** A vendor won't ship while it has an open unpaid invoice, so Accounting must check here before any restock.

### `leases`
- `id`: primary key
- `space_name`
- `landlord`
- `monthly_rent`
- `next_due`
- `notes`

**Why it matters:** Facilities uses this table to track rent amounts and due dates for the shop space.

### `cash_accounts`
- `name`: primary key
- `balance`
- `date`

**Why it matters:** Accounting checks this balance before any payment, since the pay tool must refuse anything that would make it negative.

### `payments`
- `id`: primary key
- `kind`
- `ref_id`: the invoice or lease being paid
- `amount`
- `account` → `cash_accounts.name`
- `paid_at`
- `approved_by`

**Why it matters:** This is the record of human-approved payments that the agents add to, and it starts empty.

## Problem 3: Build the MCP server

`mcp_server/server.py` is a FastMCP server that every agent shares. It reads `data/campus_customs_new.db` in read-only mode, and every number it returns comes from the database.

### `check_restock(sku, size, qty_needed)`
- **Reads:** `inventory`, `vendors`, `invoices`, `desk`
- **Helps ticket:** 101 (Bulldog tee, size S)
- **Why:** It shows the tee is out of stock in size S (0 on hand). The supplier, Bulldog Print Co, won't restock until overdue invoice 501 ($840) is paid, so the team knows what to clear before promising the order.

### `manage_payables(action="list", as_of)`
- **Reads:** `invoices`, `vendors`, `leases`, `cash_accounts`, `desk`
- **Helps ticket:** 102 (rent due)
- **Why:** It lists the $2,400 rent due 9/2 next to the overdue $840 invoice and the $3,400 cash balance, so Facilities and Accounting can see that both bills can be paid with $160 left over.

### `quote_bulk_order(sku, size, qty, discount_pct)`
- **Reads:** `pricing`, `inventory`, `vendors`, `invoices`, `desk`
- **Helps ticket:** 103 (Yale AI Club, 20 hoodies in size M)
- **Why:** It prices the club's request, shows the largest discount that stays within the margin floor, and flags any discount for human approval. It also shows that only 8 hoodies can ship now and the other 12 depend on Bulldog Print Co, who is blocked by invoice 501.

### Design notes
- **Supplier lookup:** No table links a SKU to a vendor. The server first looks for a past invoice that names the SKU, then falls back to matching the product type to `vendors.specialty`. The response reports which method it used.
- **Margin floor:** The database has no margin policy, so `MIN_MARGIN_PCT` in `server.py` sets it. The owner set it to 40%, so a discount can't push profit below 40% of the selling price. For the hoodie that means at most 36.78% off ($36.67 each).
- **Unpaid bills:** These are invoices whose status isn't `paid`, plus each lease's `next_due` rent. A negative `days_overdue` means the bill is due in that many days.

## Problem 5: Build the agent team and grow the MCP tools

All five agents run on **gpt-6-luna** through Portkey (`PORTKEY_API_KEY`), using PydanticAI and the Responses API. The model name is hard-coded in `backend/agents/config.py` and is not read from the environment. The agents share **one** MCP connection to `mcp_server/server.py`, which runs over `data/campus_customs_new.db`. There is no other shop-tools layer: every read and write goes through MCP.

```
backend/
├── models.py              # data types (tickets, hand-offs, approvals, reports, audit events)
├── run_tickets.py         # runner: optional DB reset, open tickets -> Boss -> update_ticket
├── prompts/               # one prompt per agent
│   ├── boss.md
│   ├── inventory.md
│   ├── accounting.md
│   ├── facilities.md
│   └── customer_service.md
└── agents/
    ├── config.py          # model, tool access, safety limits
    ├── team.py            # agents, hand_off, approval gate, traced agent loop
    ├── approvals.py       # human approval (terminal y/N + name)
    └── audit.py           # append-only output/audit_trail.json
```

Run it with: `python backend/run_tickets.py --reset`. The `--reset` flag copies `campus_customs.db` over the working copy first. To try it without approving anything, add `--approval deny`.

### Agents

| Agent | Job | Output type | MCP tools it can see |
|---|---|---|---|
| **Boss** | Reads each ticket, hands work to the right teammates, checks results against the shop rules, and makes the final call | `TicketResolution` | `get_tickets`, `check_restock`, `manage_payables`, `quote_bulk_order` |
| **Inventory** | Checks stock by SKU and size, finds shortfalls, finds the restock vendor and lead time | `AgentReport` | `get_tickets`, `check_restock`, `quote_bulk_order`, `save_draft` |
| **Accounting** | Watches cash and invoices, checks margins, and asks for human approval on payments, purchase orders, and discounts, then carries them out | `AgentReport` | `get_tickets`, `check_restock`, `manage_payables`, `quote_bulk_order`, `place_purchase_order`, `record_discount` |
| **Facilities** | Handles the lease, rent, and landlord, and hands rent payments to Accounting | `AgentReport` | `get_tickets`, `manage_payables`, `save_draft` |
| **Customer Service** | Drafts customer messages (never sent), and only promises what the tools show | `AgentReport` | `get_tickets`, `check_restock`, `quote_bulk_order`, `save_draft` |

**Hand-offs:** every agent has a `hand_off(to_agent, task)` tool, so any agent can ask any other for help. The other agent runs its own loop and returns an `AgentReport`. Hand-offs can't go to yourself or to an agent already in the chain (which prevents A → B → A loops). They can go at most 2 levels deep, with at most 8 per ticket. All agents on a ticket share one token budget.

### MCP tools and the tables they use

| Tool | Reads | Writes | Human approval |
|---|---|---|---|
| `get_tickets(status, ticket_id)` | `tickets`, `desk`, `leases`, `invoices` | none | no |
| `check_restock(sku, size, qty_needed)` | `inventory`, `vendors`, `invoices`, `pricing`, `desk` | none | no |
| `manage_payables(action="list")` | `invoices`, `vendors`, `leases`, `cash_accounts`, `desk` | none | no |
| `manage_payables(action="pay", kind, ref_id)` | `invoices`, `leases`, `cash_accounts`, `desk` | `payments` (new row), `cash_accounts.balance`, `invoices.status` → `paid` **or** `leases.next_due` → next month | **yes** |
| `quote_bulk_order(sku, size, qty, discount_pct)` | `pricing`, `inventory`, `vendors`, `invoices`, `desk` | none | no |
| `place_purchase_order(vendor_id, sku, size, qty)` *(new)* | `vendors`, `inventory`, `pricing`, `invoices`, `cash_accounts`, `desk` | `invoices` (prepaid PO row), `payments`, `cash_accounts.balance` | **yes** |
| `record_discount(ticket_id, sku, discount_pct)` *(new)* | `tickets`, `pricing`, `desk` | `tickets.notes` | **yes** |
| `save_draft(ticket_id, recipient, subject, body)` *(new)* | `tickets`, `desk` | `tickets.notes` (marked "DRAFT (not sent)") | no |
| `update_ticket(ticket_id, status, note)` *(new, runner only)* | `tickets`, `desk` | `tickets.status`, `tickets.notes` | no |

**Why the new tools:** the original 3 tools could only report. Working a ticket also needs:
- reading the board (`get_tickets`)
- paying the overdue invoice that blocks restocks and paying rent (`manage_payables` `pay`)
- reordering stock once the vendor is unblocked (`place_purchase_order`)
- locking in an approved discount (`record_discount`)
- leaving unsent messages on the board (`save_draft`)
- closing the ticket out (`update_ticket`)

### Audit trail

`output/audit_trail.json` is a JSON array that only ever grows. Each run appends to it with a new `run_id`, and nothing is wiped. Every record has a UTC time, `run_id`, `seq`, the shop date, the ticket, the agent, and the hand-off depth. These steps are logged:

- **Run:** `run_start` (model and limits), `db_reset`, `run_end` (total usage)
- **Ticket:** `ticket_start`, and `ticket_end` (status and usage)
- **Agent loop:** `agent_start`, then each `agent_step` (user prompt, model request, model response with the tool calls, `finish_reason`, model name, and token counts), then `agent_end` (stop reason and structured output)
- **Tools:** each `tool_call` with its full arguments, and each `tool_result` with the full result or the error
- **Hand-offs and approvals:** `handoff_start`/`handoff_end`, and `approval_requested`/`approval_decision`
- **Problems:** `limit_hit` and `error`

## Safety

### Guardrails
1. **Ask permission for every discount, and keep a 40% minimum margin.**
   - `record_discount` is gated, so a human must say yes before any discount is recorded.
   - `quote_bulk_order` and `record_discount` both refuse a discount above the most the 40% margin allows (36.78% on the hoodie).
   - The prompts treat that maximum as a ceiling, not a target.
2. **Never send messages directly to real customers or vendors.**
   - There is no send or email tool at all.
   - `save_draft` only writes to the ticket notes, marked "DRAFT (not sent)", for a human to review.
   - Customer drafts may not mention internal cash, invoice, or vendor problems.
3. **Every transaction involving real money needs human approval first.**
   - Paying a bill, placing a purchase order, and recording a discount are gated in the harness (`team.py`, `_process_tool_call`). The MCP call is held until a human types `y` and their name.
   - That name is written to `payments.approved_by`.
   - Only Accounting may request these calls.
   - `approved_by` is removed from the tool schemas, so a model can't fill it in. The server also rejects agent names such as "accounting" or "ai".
   - A request that's denied once is not asked again on that ticket, and an approved one is never repeated.
   - The pay tools refuse any payment that would make cash negative. Each payment updates every affected table in one transaction.
   - **On the dashboard**, the request shows up as an "Incoming Transmission" pop-up with the amount and payee. **Approve** needs the human's name (the API rejects an approval without one), and **Deny** takes an optional reason. If nobody answers within 15 minutes, it counts as a deny.
4. **Other protections.**
   - **Model:** only `gpt-6-luna` is used for every agent. It's hard-coded and can't be changed with an environment variable.
   - **Least privilege:** each agent sees only the MCP tools its job needs. Read tools open the database read-only, and `update_ticket` is used only by the runner.
   - **One ticket at a time:** two runs can't spend the same cash. Reset is refused while a ticket is running.
   - **Browser access:** CORS only allows the local Vite board (`http://localhost:5173`, other localhost ports) and the `desk_tickets.html` page opened from disk.
   - **Audit trail:** `output/audit_trail.json` is append-only and records every agent-loop step, tool call, hand-off, and approval decision.
   - **Known issue (found in the Problem 9 run):** when two agents hand the same discount to Accounting at the same moment, the human can be asked twice. On ticket 103 the 10% discount was approved twice, which added a duplicate note to the ticket. No money moved. The fix would be to lock each approval request while it's waiting, so a matching request can't be asked again until the first is answered.

### Token usage limits (recommended)

I measured real runs on a scratch copy of the database. A single ticket used **20k to 60k tokens** (8 to 19 model calls, 8 to 22 tool calls), and a full run of all three tickets used **84k to 110k tokens**. I recommend these limits, which are set in `backend/agents/config.py`:

| Limit | Value | Why |
|---|---|---|
| Tokens per ticket (all agents together) | **100,000** | About 1.7× the worst ticket observed (60k), so normal work never hits it but a hand-off loop or retry spiral gets cut off |
| Model calls per ticket | **40** | About 2× the most observed (19) |
| Tool calls per ticket (MCP + hand-offs) | **40** | About 2× the most observed (22) |
| Tokens per full run | **300,000** | About 3× a full 3-ticket run (110k). No new ticket starts once it's reached |
| Hand-off depth / hand-offs per ticket | **2 / 8** | Boss → specialist → specialist covers every ticket we have |

If a limit is hit, PydanticAI stops the agent loop. The ticket is then marked `blocked` with a note saying a human should review it, and a `limit_hit` event goes in the audit trail. Spending stays bounded even if an agent misbehaves.

## Problem 7: Backend routes

`backend/main.py` is a FastAPI app. Start it from the `backend/` folder with `uvicorn main:app --reload --port 8000`; interactive docs are at `http://localhost:8000/docs`.

- **MCP connection:** the API opens one connection to the MCP server when it starts. Every route reads or writes shop data through it.
- **Running tickets:** only one ticket runs at a time, so two runs can't spend the same cash.
- **Approvals:** when an agent asks to pay, order, or discount, the run pauses until a human answers through the approval route. If nobody answers within 15 minutes, it counts as a no.

| Route | URL | What it does |
|---|---|---|
| List tickets | `GET /api/tickets` | Returns every ticket on the board with its status and a `resolved` true/false flag. |
| Run a ticket | `POST /api/tickets/{ticket_id}/run` | Starts the agent team on that ticket in the background and returns the `run_id`. Returns 409 if another run is going and 404 if the ticket doesn't exist. |
| Run status | `GET /api/run` | Shows whether a run is going, which ticket, how many approvals are waiting, and the last run's result. |
| Agent events | `GET /api/events?after={index}` | Returns recent agent events (what each agent said, tool calls and results, hand-offs, approvals, the Boss's final call) so the board can refresh by polling with the last index it saw. You can filter with `ticket_id` and `run_id`. |
| Pending approvals | `GET /api/approvals` | Lists the payments, purchase orders, and discounts waiting for a human, with amount, payee, and approval id. |
| Approve / deny | `POST /api/approvals/{approval_id}` | Records the human's click. The body is `{"approved": true, "approver": "<name>"}` or `{"approved": false, "reason": "..."}`, and the name becomes `payments.approved_by`. |
| Cash | `GET /api/cash` | Returns the current checking balance from `cash_accounts`. |
| Past run | `GET /api/runs/{run_id}` | Rebuilds a finished run (status, the Boss's resolution, usage) from the audit trail, so the board can replay it at `http://localhost:5173/?run={run_id}`. |
| Reset | `POST /api/reset` | Copies `campus_customs.db` over `campus_customs_new.db` so a new run starts from the original values. Refused while a ticket is running. |

## Problem 8: Agent dashboard

`frontend/` is a React + Vite + TypeScript app styled as a Club Penguin Secret Agent HQ (full write-up in `output/design.md`). Start it with `npm run dev` (http://localhost:5173). It calls the API at `http://localhost:8000`.

- **Mission Board:** the three tickets as cards with status stamps (OPEN, IN THE FIELD, IN PROGRESS, BLOCKED, RESOLVED). Pick one, then **Start mission** calls `POST /api/tickets/{id}/run`.
- **Agent screens:** the Boss gets a large monitor and the four specialists get one each. Every agent is a spy penguin in its own color with its own prop. A speech bubble shows its latest message, and a live feed shows tool calls, hand-offs, and approvals (polled from `GET /api/events`). The penguin's motion and LED show standby, on mission, awaiting HQ, or reported.
- **Approvals:** `GET /api/approvals` drives the "Incoming Transmission" spy-phone pop-up, and Approve or Deny calls `POST /api/approvals/{id}`.
- **Cash:** the coin vault shows `GET /api/cash`. It refreshes during runs and right after an approval, and flashes red when the balance drops.
- **Mission Debrief:** after a run, the Boss's decision, one card per agent (report, hand-offs, tools used), approvals and next steps, and the token count.
- **Other screens:** a radar, an island map, a Puffle Cam, and a decoder loop as filler. The board also joins runs started outside it, and can replay a past run with `?run={run_id}`.

## Problem 9: Real run over the three tickets

The working database was reset (`POST /api/reset`), so the starting checking balance was **$3,400.00**. Each ticket was then run from the API with the real database, and Emily approved every request on the dashboard.

| Ticket | Final status | Agents | Human approvals | Cash change | Tokens |
|---|---|---|---|---|---|
| 101 Bulldog tee | `in_progress` (tee arrives 2026-09-05) | Boss → Inventory → Accounting; Boss → Customer Service | Pay invoice 501, $840 ✅; restock PO for 1 tee, $8 ✅ | −$848 | 38,180 |
| 102 Rent due | `resolved` | Boss → Facilities + Accounting (in parallel) | Pay rent, $2,400 ✅ | −$2,400 | 20,029 |
| 103 Bulk hoodie discount | `blocked` (the $264 restock is more than the $152 left) | Boss → Inventory → Accounting; Boss → Accounting; Boss → Customer Service | 10% discount ✅ (asked twice; see Known issue) | $0 | 56,524 |

**Ending checking balance: $152.00**, which matches `cash_accounts`. The `payments` table has three rows totaling $3,248, all `approved_by` Emily.

Every bill together (invoice $840 + tee $8 + rent $2,400 + hoodie restock $264 = $3,512) is more than the $3,400 starting cash. No revenue is modeled, so 103 can't be fully resolved without more money, and 101 stays in progress until the shop date passes 9/5.

**Outputs:**
- `output/desk_tickets.html`: Expected vs. Actual for each ticket, plus the cash ledger
- `output/resolved_tickets.json`: each ticket's status, outcome, agent contributions, and approvals
- `output/resolved_board.html`: dashboard screenshots for each ticket
- `output/audit_trail.json`: the three real runs (`run-20261008T195312Z-5cf7d5`, `run-20261008T200529Z-81ef24`, `run-20261008T200557Z-e52fb3`), appended after the earlier records

