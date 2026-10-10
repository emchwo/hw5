# Campus Customs: Multi-Agent Ticket Desk (HW 5)

A five-agent team runs the Campus Customs shop's ticket desk: the **Boss**, **Inventory**, **Accounting**, **Facilities**, and **Customer Service**.
- **Model:** every agent runs on **gpt-6-luna** through Portkey.
- **Shop data:** all reads and writes go through an **MCP server** over a SQLite database.
- **Backend:** a **FastAPI** app runs the agents.
- **Board:** a Club Penguin–style **React** "Secret Agent HQ" shows each agent working.
- **Approvals:** a human must approve every payment, purchase order, and discount.

Full design notes: [`output/harness.md`](output/harness.md) (system, tables, tools, agents, routes, safety) and [`output/design.md`](output/design.md) (dashboard).

```
hw5/
├── AI_prompts.md            # prompts used for each problem
├── requirements.txt         # Python deps (MCP server + backend)
├── .env.example             # copy to .env and add PORTKEY_API_KEY
├── .mcp.json                # lets Claude Code call the MCP tools
├── data/
│   ├── campus_customs.db       # ORIGINAL, never modified (reset source)
│   └── campus_customs_new.db   # WORKING COPY the agents read and write
├── mcp_server/              # FastMCP server: the only path to shop data
├── backend/                 # FastAPI (main.py), agents/, models.py, prompts/ (one per agent), run_tickets.py (CLI)
├── frontend/                # React + Vite board (npm run dev)
└── output/                  # harness, design, smoke test, desk tickets, resolved tickets/board, audit trail, github_url
```

---

## 1. Setup (one time)

You need Python 3.12+ and Node 20+.

```bash
# Python environment (from the repo root)
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate
pip install -r requirements.txt

# API key
cp .env.example .env        # then put your PORTKEY_API_KEY in .env

# React board
cd frontend
npm install
cd ..
```

## 2. The two databases: copy the original for a clean run

| File | Role |
|---|---|
| `data/campus_customs.db` | The **original** shop data. Never changed by anything. |
| `data/campus_customs_new.db` | The **working copy**. The MCP server, backend, and agents read and write only this file. |

As committed, the working copy holds the results of my real run (Problem 9): tickets 101 `in_progress`, 102 `resolved`, 103 `blocked`, and checking at $152. **To start clean, copy the original over the working copy:**

```bash
# macOS / Linux / Git Bash
cp data/campus_customs.db data/campus_customs_new.db
# Windows PowerShell
Copy-Item data\campus_customs.db data\campus_customs_new.db -Force
```

The same reset is also available as the **Reset DB** button on the board, `POST http://localhost:8000/api/reset`, or the `--reset` flag on the CLI runner. Never edit or delete `campus_customs.db`.

## 3. Start the MCP server

The shop's tools live in `mcp_server/server.py` (FastMCP, stdio transport). It serves 8 tools: `get_tickets`, `check_restock`, `manage_payables` (`list` / `pay`), `quote_bulk_order`, `place_purchase_order`, `record_discount`, `save_draft`, and `update_ticket`.

```bash
python mcp_server/server.py
```

- It talks over stdio, so on its own it simply waits for a client. Press Ctrl+C to stop it.
- **You don't need to keep it running in a terminal.** The FastAPI backend starts its own MCP server process automatically (one shared connection for all agents).
- Claude Code starts it through `.mcp.json`. On macOS/Linux, change `"command"` in `.mcp.json` to `.venv/bin/python`.

## 4. Start the FastAPI backend

```bash
cd backend
uvicorn main:app --reload --port 8000
```

- API docs: http://localhost:8000/docs
- Routes: `GET /api/tickets`, `POST /api/tickets/{id}/run`, `GET /api/run`, `GET /api/runs/{run_id}`, `GET /api/events`, `GET /api/approvals`, `POST /api/approvals/{id}`, `GET /api/cash`, `POST /api/reset`
- After changing backend code, restart uvicorn if `--reload` doesn't pick it up.

## 5. Start the React board

In a second terminal:

```bash
cd frontend
npm run dev
```

Open **http://localhost:5173**. The board calls the backend at http://localhost:8000; the backend's CORS settings allow the Vite origin.

## 6. Full 3-ticket run (reset first!)

1. **Reset the database** so the run starts from the original values: click **Reset DB** on the board, or run `cp data/campus_customs.db data/campus_customs_new.db` before starting the backend. Checking should read **$3,400.00**.
2. On the **Mission Board**, click ticket **#101**, then **Start mission**.
3. When an **Incoming Transmission** pops up, type your name and click **Approve** or **Deny**. Agents can't move money or give discounts without this, and unanswered requests are denied after 15 minutes.
4. When the debrief appears, repeat for **#102** and **#103**.

Watch each agent's screen, the Mission Debrief, and the coin vault (checking balance) as payments go through.

**Command-line alternative** (approvals are asked in the terminal):

```bash
python backend/run_tickets.py --reset                  # all open tickets
python backend/run_tickets.py --reset --approval deny  # dry run, every approval denied
```

Every run is appended to `output/audit_trail.json`, which is never wiped.

## Safety, in short

- **Approvals:** a human approves every payment, purchase order, and discount, and the approver's name is saved in `payments.approved_by`. Only Accounting can request these.
- **Margin:** a 40% minimum margin is enforced on discounts.
- **No sending:** messages to customers, vendors, and landlords are saved as drafts on the ticket and never sent.
- **Cash:** cash can't go negative, and every payment updates all affected tables in one transaction.
- **Limits:** 100k tokens, 40 model calls, and 40 tool calls per ticket; 300k tokens per run; hand-off depth 2.

Details are in [`output/harness.md`](output/harness.md).
