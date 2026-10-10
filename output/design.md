# Campus Customs: Secret Agent HQ, Dashboard Design

The agent dashboard (`frontend/`, run with `npm run dev` at http://localhost:5173) is styled as a spy-penguin headquarters inspired by Club Penguin's Secret Agent HQ. It calls the FastAPI routes at http://localhost:8000.

## Layout

The page is one HQ room: a wall of riveted monitors, each a "screen" with its own job.

- **Top bar:** the agency badge, the **coin vault** (checking balance), a connection light, and a **Reset DB** button.
- **Mission Board (left column):** the three tickets as paper mission cards, plus the **Start mission** button.
- **The Director's screen (large, top center):** the Boss gets the biggest monitor because it reads the ticket, hands out work, and makes the final call.
- **Four agent screens (center grid):** Inventory, Accounting, Facilities, and Customer Service each get their own monitor.
- **Filler screens (right column):** looping animations that make the room feel alive: a **snow radar** sweep, an **island map** with falling snow and a marching route to Campus Customs, a **Puffle Cam** with bouncing puffles, and a scrolling **decoder** feed.
- **Mission Debrief (bottom):** a concise summary of what each agent did once the run reports back.
- **Incoming Transmission:** a spy-phone pop-up that appears whenever the team needs a human to approve a payment, purchase order, or discount.

On smaller screens the monitors restack into two columns, then one.

## How the agents read differently

Each agent is a penguin with its own **color, prop, and codename**, so you can tell them apart at a glance:

| Agent | Penguin | Prop | Codename |
|---|---|---|---|
| Boss | black | bow tie + gold badge | THE DIRECTOR |
| Inventory | green | clipboard | STOCKPILE |
| Accounting | yellow | green visor + coin | COINS |
| Facilities | orange | hard hat + wrench | IGLOO |
| Customer Service | pink | headset + postcard | POSTCARD |

Each agent screen shows what the agent is saying and doing:
- **Speech bubble:** the agent's latest message or report.
- **Live feed:** tool calls (🔧), results (📡), hand-offs (📨), approval requests (🔔), and the final report (📝 or ⭐ for the Boss).

The penguin's motion and the status tag show its state:
- **Standby:** the penguin sways.
- **On mission:** it bobs and waves a flipper.
- **Awaiting HQ:** it shakes while waiting for a human approval.
- **Reported:** it does a little hop.

The LED in each monitor's corner matches the state: off, amber blinking, red blinking, or green.

## Resolved tickets and cash

- **Ticket status:** each mission card carries a rubber stamp: **OPEN**, **IN THE FIELD** (running now), **IN PROGRESS**, **AWAITING HQ**, **BLOCKED**, or a green **RESOLVED**. A resolved ticket's button changes to **Mission complete ✓**. The stamp comes from the ticket status in the database, so it only says RESOLVED when the Boss's final call is resolved.
- **Mission Debrief:** the Boss's decision, one card per agent (report, who it handed off to, tools used as chips), any approvals and next steps, and the token count for the run.
- **Cash:** the **coin vault** in the top bar shows the checking balance from `cash_accounts`, with a spinning gold coin. It refreshes during runs and right after an approval. When the balance drops (e.g. $3,400 → $2,560 after paying invoice 501) the vault flashes red, so the cost of each approval is visible.

## Club Penguin creative styling

- **Penguins:** drawn in SVG to match Club Penguin's art: pear-shaped bodies with thick darker outlines, a heart-shaped white face, a separate white belly, a wide two-part orange beak, side flippers, flat scalloped feet, and black agent shades.
- **Type and buttons:** big outlined headline lettering like the game's logo, and chunky rounded orange, green, and red buttons that press down when clicked.
- **Props from the island:** puffles, the snowy island map, coins as currency, and spy-phone transmissions.
- **Screens:** glowing teal monitors with scanlines and a slight flicker, like the HQ's wall of computers.

## Why it feels nostalgic

I played Club Penguin a lot as a kid, and building a multi-agent team reminded me of playing as a secret penguin agent in the game. The dashboard is special because it evokes nostalgia and whimsy for the person using it.  It makes work feel like something fun, while drawing a connection between AI agents and the penguin agents that were a key plot of the Club Penguin game.
