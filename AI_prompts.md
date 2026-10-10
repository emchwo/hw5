# HW 5 — AI Prompts

<!--
Section format:

## Problem N: Title

**Initial prompt:**
> ...

**Follow-up prompt:**
> ...

**What the initial prompt lacked:** One sentence.
-->

## Problem 1: Vibe coder prompts

**Initial prompt:**
> create AI_prompts.md similar to the previous HW projects. each problem will have its own section, labeled with the problem number and title, the prompt that was typed in, and then one follow up prompt if needed and one sentence on what was lacking in the initial prompt

**Follow-up prompt:**
_None._

**What the initial prompt lacked:** Nothing critical, since it pointed to the earlier HW logs for the format, so no follow-up was needed.

## Problem 2: Study the Campus Customs database

**Initial prompt:**
> open data/campus_customs.db and then copy it to data/campus_customs_new.db, which we'll update in later problems.
>
> then start output/harness.md, create a Problem 2 section and then list out the tables and its fields in the db and put in a one short sentence on why that table matters for the agents

**Follow-up prompt:**
_None yet._

**What the initial prompt lacked:** _TBD after any follow-up._

## Problem 3: Build the MCP server

**Initial prompt:**
> build an MCP server in mcp_server/ using fastMCP. it will talk to data/campus_customs_new.db. every agent will use the tools in this server so create these 3 tools for now. remember to never invent or hallucinate data, always use the info in the database.
>
> tool 1: check_restock(sku, size, qty_needed)
> - show how many are in stock, how many we're short, who the supplier is, and anything blocking a restock like an unpaid overdue invoice. don't place orders. just report what's needed.
>
> tool 2: manage_payables
> - action "list": show all unpaid bills with amount, due date, and how many days overdue. use an as_of date (default is today). sort most urgent first.
>
> tool 3: quote_bulk_order(sku, size, qty, discount_pct)
> - discount_pct is optional
> - show profit per item, total profit, and the biggest discount we can give without going under our lowest margin.
> - check with human first if discount is allowed.
> - show how many we can ship now and how many need a restock. include any restock blockers from check_restock tool.
>
> after doing all that, update output/harness.md with a Problem 3 section. list out each tool, which table it reads, which ticket it helps (101 102 or 103), and then write one concise sentence on why that tool can help resolve the ticket. the tool has to be tied directly to the ticket.
>
> finally, add mcp_server/README.md that concisely explains what the MCP server is for, which database file it uses, and the three tools it uses.

**Follow-up prompt:**
> yes keep at least a 40% margin

**What the initial prompt lacked:** It never said what "our lowest margin" was, and the database has no margin policy, so the 40% minimum margin had to come in a follow-up.

## Problem 4: Add the MCP server to vibe coder and test each tool

**Initial prompt:**
> add the MCP server to this project so that you can call the tools, and save the connection json text in .mcp.json
>
> then after it's connected, let's test all 3 MCP tools. create output/mcp_smoke.json to document the test results, with the prompt that was used to test the tool, the tool name, and the tool output. make sure the tool output matches the values in data/campus_customers_new.db

**Follow-up prompt:**
> yes that's what i meant for the db

**What the initial prompt lacked:** It misspelled the database as `campus_customers_new.db`, so I had to confirm that `campus_customs_new.db` was meant before checking the tool outputs against it.

## Problem 5: Build the agent team and grow the MCP tools

**Initial prompt:**
> here's the agent team setup:
>
> * boss reads each ticket, picks who works on it and makes final calls.
> * inventory checks stock by SKU and size and finds a vendor to restock.
> * accounting watches cash and invoices, checks margins, and prepares payments for your approval.
> * facilities handles leases and rent.
> * Customer Service drafts messages to customers.
> * any agent can hand work to any other.
>
> put agent prompts into backend/prompts/ and make one file per agent. based on the agent team setup specifications, figure out the appropriate data types and put them all into backend/models.py
>
> and just to be clear the agent files are under backend/
>
> here are the shop rules for the agent:
>
> * `desk.date_today` counts as "today" for deciding what's overdue.
> * Vendor lead times come from the `vendors` table.
> * A vendor won't ship new stock while it has an unpaid invoice open.
>
> * Every payment needs human approval first
> * Once a payment is approved, every affected table gets updated.
> * The pay tool refuses anything that would make the cash balance negative.
> * Money only goes out and no revenue is modeled.
>
> * Messages to customers and vendors stay as drafts and are never sent by the agent
>
> use the PORTKEY_API_KEY and only use gpt-6-luna for all of the agents. based on the agent team setup and knowing that the agent team has to be able to work on open tickets, see if there's any new tools that need to be added to the MCP server, totally ok if the current 3 are sufficient though. all shop information comes from the MCP server over data/campus_customs_new.db, do not create another shop-tools layer that bypasses MCP
>
> all the agents need to append to output/audit_trail.json as they run. they should record enough to audit later if needed for each agent-loop step, and the json should not be wiped after each run. just append to it as we go.
>
> after all that, write down each agent and each MCP tool along with which table the tool uses in output/harness.md. and then add in a safety section, with all the guardrails below:
>
> * Always ask permission when giving discounts and remember that there is a 40% lowest margin as the floor
> * Never send messages directly to real customers or vendors
> * Any transactions involving real money require human approval first
>
> then i also want to add something about token usage limits to this safety section - give me a recommendation for a reasonable amount to limit this multi-agent team to

**Follow-up prompt:**
_None yet._

**What the initial prompt lacked:** _TBD after any follow-up._

## Problem 6: Plan the three tickets

**Initial prompt:**
> build output/desk_tickets.html and it needs to be a page that i can double-click with one tab per ticket. then add empty cash and reflection tabs, i will fill those out later
>
> each ticket tab should have an Expected section and an Actual section which should be left blank for now. here's what each ticket's Expected section should say:
>
> * 101: Boss should read the ticket and then delegate to  Inventory and Accounting to resolve, before pulling in Customer Service to let the customer know what the next steps are. Use the tools get_tickets, check_restock, manage_payables, place_purchase_order, save_draft, and update_ticket.
> * 102: Boss should read the ticket and then ask Accounting and Facilities to help figure out the next steps for paying rent, but always asking/waiting for human approval with the solution since it deals with real money. Use the tools get_tickets, manage_payables, update_ticket.
> * 103: Boss should read the ticket and then get Inventory, Accounting, and Customer Service to work together to figure out the restock needed, the right discount amount, and a drafted message for the Yale AI Club with the results.  Use the tools get_tickets, check_restock, quote_bulk_order, place_purchase_order, record_discount, save_draft, and update_ticket.

**Follow-up prompt:**
_None yet._

**What the initial prompt lacked:** _TBD after any follow-up._

## Problem 7: Backend routes

**Initial prompt:**
> in backend/main.py use FastAPI and add routes so that these actions can happen:
>
> * return the 3 tickets and whether it's open or resolved
> * take a ticket id and run the ticket with the agent team
> * return recent agent events like what each said and what tools were used so that the board can refresh
> * approve a payment or purchase after a human clicks Approve
> * show the current checking balance from cash_accounts
> * reset the database to the original values if i want to try a new run
>
> start the server with uvicorn main:app --reload --port 8000
>
> and do that from the backend/ folder.
>
> after all that, update output/harness.md and list each route with its URL and a concise sentence on what it does.

**Follow-up prompt:**
_None yet._

**What the initial prompt lacked:** _TBD after any follow-up._

## Problem 8: Agent dashboard

**Initial prompt:**
> let's build the frontend dashboard, which should call the routes we just built. it needs to do the following:
>
> * list all three tickets
> * allow human to pick one ticket and then start the agent team to resolve it
> * show each agent and what they are saying and doing while the ticket is being resolved
> * mark a ticket as Resolved when the run finishes
> * create a concise summary showing what each agent did for that ticket
> * when asked, allow a human to Approve a pay or purchase when asked
> * show the checking balance e.g. it should be lower after a payment is approved
>
> make the dashboard layout look like the club penguin secret agent HQ with different screens. have a specific screen for each agent, but add fun looping animations in the other screens to fill it out. it should have a spy penguin theme, nostalgic of the club penguin website and art.
>
> talk to the backend at http://localhost:8000 and on the backend make sure the vite page origin is allowed so the browser can call the routes. start the board with npm run dev
>
> now update output/design.md
>
> summarize the layout, how agents read differently, how resolved tickets and cash is shown, and about the club penguin creative styling and how it's nostalgic of my childhood and playing as a secret penguin agent

**Follow-up prompt:**
> can you make the penguins looks more like the club penguin ones or no

**What the initial prompt lacked:** It asked for a spy-penguin theme nostalgic of Club Penguin art but didn't describe what makes a Club Penguin penguin recognizable, so the first penguins were generic and had to be redrawn in a follow-up.

## Problem 9: Resolve the tickets

**Initial prompt:**
> reset data/campus_customs_new.db so that i can test the agents on a run over the 3 tickets. tell me what the starting checking balance is, then run all three tickets until they are all resolved

**Follow-up prompt:**
> go!!!
>
> then - open up output/desk_tickets.html and now fill out the Actual section for each ticket with a short and concise description of which agents worked, what was delegated, and what tools were used.
>
> then on the cash tab of the same html, itemize the money. show the starting balance, then show how cash changed when each of the 3 tickets resolved (so 3 entries total) and then show the ending checking balance. then, check the ending balance with what's in cash_accounts in the database
>
> tell me if the ending balance matches or not.
>
> also, save output/resolved_tickets.json for each ticket and make sure you track id, final status, a short description of the outcome, a short description of what each agent contributed, and any humans approvals that were requseted
>
> also save output/resolved_board.html - this is a page that i can double-click with a screenshot of the React board for each resolved ticket. include all 3 in this.
>
> append the real runs to output/audit_trail.json, then update output/harness.md so that it has info on the tables, MCP tools, the 5 agents, API routes, dashboard, and safety rules

**What the initial prompt lacked:** It didn't plan for the human approvals each payment needed (the run paused until I clicked Approve) or say what to produce once the run finished, so the go-ahead and all of the write-ups came in the follow-up.

## Problem 10: Reflection

**Initial prompt:**
> * How would you evaluate the performance of the agents on each ticket and why?
>    * For 101:  3.5/5 stars, overall it made good decisions but there was a lot of logistical overhead and approval needed. Inventory correctly identified that there were 0 tees in stock and that the vendor was blocked by an invoice, and then Accounting asked me for two different approvals. Boss correctly kept the ticket open since the tee won't arrive yet.
>    * For 102: 4/5 stars, the agent team performed really well. Boss delegated to Facilities and Accounting accurately, and asked for human approval when needed.
>    * For 103: 3/5 stars, Accounting correctly refused the restock because there wasn't enough cash left but there was a duplicate discount approval bug. In the future, a second identical request should be handled after waiting for the initial request to be resolved.
> * For each ticket, how did Actual compare to the Expected plan you wrote earlier?
>    * For 101: Inventory delegated to Accounting itself.
>    * For 102: No major differences, other than the team using a save_draft tool that I didn't account for.
>    * For 103: Because of the lack of cash, the purchase order wasn't placed. The record_discount was also used twice.
> * What would have been simpler as one agent with tools - and why?
>    * A single agent would have seen the entire cash tab at once, in comparison to an agent team that is making its own calls and running in parallel with other agents. Less tokens would have been used, there would be no duplicate errors, and one agent might have been able to weigh the restock for ticket 103 before spending cash on 101 and 102.
> * Describe three new problems Campus Customs might face that this agent team could solve with the tools you built.
>    * 101: Communicating with Tauhid about when the restock will come and then subsequently resolving the ticket after 9/5
>    * 102: October rent will come up next month, so the agent team can assist with paying that again and/or drafting a rent extension request if there still isn't enough cash yet
>    * 103: Communicating with the AI club that there are 8 hoodies currently in stock, and that they can do a partial order, and then later fulfilling the rest of the order after restocking and notifying the customers
> * Describe three new problems Campus Customs might face that this agent team could not solve with the tools you built, and explain the tools and agents you would need to solve them
>    * There might be a new tool needed to automatically reopen tickets once certain barriers are overcome or removed. In this case, the ticket 101 will need to be reopened and resolved by the agent team after the restock delivery.
>    * To communicate efficiently with customers, there could be a new tool for Customer Service to create tickets for the team based on customers' email replies. A human would need to send out the drafts that the agent makes, but the agent could read and create tickets from emails.
>    * There needs to be a tool where the agent team can see the overall forecasted cash flow and propose a ranking or plan for how the open tickets should be handled. Human approval would be needed for the plan to be executed, but a forecast tool would have helped avoid what happened with ticket 103.

**Follow-up prompt:**
_None yet._

**What the initial prompt lacked:** _TBD after any follow-up._
