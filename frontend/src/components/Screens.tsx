import { useState, type ReactNode } from "react";
import { AGENTS, type AgentEvent, type AgentName, type Approval, type RunState, type Ticket } from "../api";
import { Penguin, Puffle, type Mood } from "./Penguin";

// --------------------------------------------------------------------------- //
// Monitor frame
// --------------------------------------------------------------------------- //
export function Monitor({
  label, className = "", light, children,
}: { label: string; className?: string; light?: "on" | "busy" | "alert" | "off"; children: ReactNode }) {
  return (
    <section className={`monitor ${className}`}>
      <header className="monitor-label">
        <span className={`led led-${light ?? "off"}`} />
        <span>{label}</span>
        <span className="rivets" aria-hidden="true">● ●</span>
      </header>
      <div className="screen">
        <div className="scanlines" aria-hidden="true" />
        {children}
      </div>
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Agent state derived from the event feed
// --------------------------------------------------------------------------- //
export interface AgentView {
  mood: Mood;
  bubble: string | null;
  feed: AgentEvent[];
  tools: Record<string, number>;
  handoffsTo: string[];
  report: string | null;
  active: boolean;
}

export function deriveAgents(events: AgentEvent[], running: boolean): Record<AgentName, AgentView> {
  const out = {} as Record<AgentName, AgentView>;
  for (const a of AGENTS) {
    out[a.id] = { mood: "idle", bubble: null, feed: [], tools: {}, handoffsTo: [], report: null, active: false };
  }
  for (const e of events) {
    if (!e.agent || !out[e.agent]) continue;
    const v = out[e.agent];
    v.active = true;
    v.feed.push(e);
    switch (e.kind) {
      case "agent_start":
        v.mood = "working";
        break;
      case "tool_call":
        if (e.tool && e.tool !== "hand_off") v.tools[e.tool] = (v.tools[e.tool] ?? 0) + 1;
        if (e.tool === "hand_off") {
          const m = e.text.match(/"to_agent":\s*"(\w+)"/);
          if (m) v.handoffsTo.push(m[1]);
        }
        v.mood = "working";
        break;
      case "said":
        v.bubble = e.text;
        break;
      case "approval_requested":
        v.mood = "waiting";
        v.bubble = `Requesting HQ approval: ${e.text}`;
        break;
      case "approval_decision":
        v.mood = "working";
        v.bubble = e.text.startsWith("approved") ? "HQ approved it! Proceeding." : "HQ denied it. Standing down.";
        break;
      case "report":
      case "final":
        v.mood = "done";
        v.report = e.text;
        v.bubble = e.text;
        break;
    }
  }
  if (!running) {
    for (const a of AGENTS) if (out[a.id].mood === "working" || out[a.id].mood === "waiting") out[a.id].mood = "done";
  }
  return out;
}

const ICON: Record<string, string> = {
  agent_start: "▶", tool_call: "🔧", tool_result: "📡", handoff: "📨", said: "💬",
  report: "📝", final: "⭐", approval_requested: "🔔", approval_decision: "🛡️",
};

function prettyTool(e: AgentEvent): string {
  if (e.kind === "tool_result") {
    const status = e.text.match(/"status":\s*"(\w+)"/)?.[1];
    return `${e.tool} ${status ? `→ ${status.replace(/_/g, " ")}` : "✓ data back"}`;
  }
  if (e.kind !== "tool_call") return e.text;
  const name = e.tool ?? "";
  if (name === "hand_off") {
    const to = e.text.match(/"to_agent":\s*"(\w+)"/)?.[1] ?? "?";
    return `hand_off → ${to.replace("_", " ")}`;
  }
  const args = e.text.slice(name.length + 1, -1);
  return `${name}(${args.length > 70 ? args.slice(0, 70) + "…" : args})`;
}

// --------------------------------------------------------------------------- //
// Agent screen
// --------------------------------------------------------------------------- //
export function AgentScreen({ agent, view, big = false }: { agent: AgentName; view: AgentView; big?: boolean }) {
  const meta = AGENTS.find((a) => a.id === agent)!;
  const light = view.mood === "waiting" ? "alert" : view.mood === "working" ? "busy" : view.active ? "on" : "off";
  const feed = view.feed.filter((e) => e.kind !== "agent_start" && e.kind !== "said").slice(big ? -5 : -4);
  return (
    <Monitor label={`AGENT ${meta.codename}`} light={light} className={`agent-screen ${big ? "big" : ""} mood-${view.mood}`}>
      <div className="agent-head">
        <div className="agent-title">
          <h3>{meta.title}</h3>
          <p>{meta.role}</p>
        </div>
        <span className={`mood-tag tag-${view.mood}`}>
          {view.mood === "idle" ? "STANDBY" : view.mood === "working" ? "ON MISSION" : view.mood === "waiting" ? "AWAITING HQ" : "REPORTED"}
        </span>
      </div>
      <div className="agent-body">
        <div className="agent-avatar">
          <Penguin agent={agent} mood={view.mood} size={big ? 120 : 84} />
        </div>
        <div className="agent-talk">
          {view.bubble && <div key={view.bubble} className="bubble">{clip(view.bubble, big ? 240 : 140)}</div>}
          <ul className="feed">
            {feed.length === 0 && <li className="feed-empty">Awaiting orders…</li>}
            {feed.map((e, i) => (
              <li key={`${e.index}-${i}`} className={`feed-${e.kind}`}>
                <span className="feed-icon">{ICON[e.kind] ?? "•"}</span>
                <span className="feed-text">{clip(prettyTool(e), big ? 150 : 95)}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Monitor>
  );
}

function clip(s: string, n: number) {
  return s.length > n ? s.slice(0, n) + "…" : s;
}

// --------------------------------------------------------------------------- //
// Mission board (tickets)
// --------------------------------------------------------------------------- //
const STAMP: Record<string, { label: string; cls: string }> = {
  open: { label: "OPEN", cls: "stamp-open" },
  in_progress: { label: "IN PROGRESS", cls: "stamp-progress" },
  waiting_approval: { label: "AWAITING HQ", cls: "stamp-wait" },
  blocked: { label: "BLOCKED", cls: "stamp-blocked" },
  resolved: { label: "RESOLVED", cls: "stamp-resolved" },
};

export function MissionBoard({
  tickets, selected, onSelect, onStart, run, starting, dateToday,
}: {
  tickets: Ticket[];
  selected: number | null;
  onSelect: (id: number) => void;
  onStart: () => void;
  run: RunState | null;
  starting: boolean;
  dateToday: string;
}) {
  const running = run?.state === "running";
  const sel = tickets.find((t) => t.id === selected);
  return (
    <Monitor label="MISSION BOARD" light={running ? "busy" : "on"} className="mission-board">
      <p className="board-date">Shop date · {dateToday || "…"}</p>
      <ul className="tickets">
        {tickets.map((t) => {
          const st = STAMP[t.status] ?? { label: t.status.toUpperCase(), cls: "stamp-open" };
          const live = running && run?.ticket_id === t.id;
          return (
            <li key={t.id}>
              <button
                className={`ticket-card ${selected === t.id ? "selected" : ""} ${live ? "live" : ""}`}
                onClick={() => onSelect(t.id)}
                disabled={running}
              >
                <span className="ticket-id">#{t.id}</span>
                <span className="ticket-subject">{t.subject}</span>
                <span className="ticket-meta">
                  {t.requester} · {t.type.replace("_", " ")}
                  {t.sku ? ` · ${t.sku} ${t.size} ×${t.qty}` : ""}
                </span>
                <span className={`stamp ${live ? "stamp-live" : st.cls}`}>{live ? "IN THE FIELD" : st.label}</span>
              </button>
            </li>
          );
        })}
      </ul>
      <button className="cp-button start" onClick={onStart} disabled={!sel || running || starting || sel.resolved}>
        {running ? "Mission in progress…" : sel?.resolved ? "Mission complete ✓" : starting ? "Deploying…" : sel ? `Start mission #${sel.id}` : "Pick a mission"}
      </button>
    </Monitor>
  );
}

// --------------------------------------------------------------------------- //
// Approval transmission (modal)
// --------------------------------------------------------------------------- //
export function ApprovalModal({ approval, onDecide }: { approval: Approval; onDecide: (ok: boolean, name: string, reason: string) => Promise<void> }) {
  const [name, setName] = useState(() => localStorage.getItem("cc-approver") ?? "");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const r = approval.request;
  const kindLabel = r.kind === "payment" ? "PAYMENT" : r.kind === "purchase_order" ? "PURCHASE ORDER" : "DISCOUNT";

  async function decide(ok: boolean) {
    if (ok && !name.trim()) return setErr("Enter your agent name to approve.");
    setBusy(true);
    setErr(null);
    try {
      if (ok) localStorage.setItem("cc-approver", name.trim());
      await onDecide(ok, name.trim(), reason.trim());
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="tx-title">
      <div className="spyphone">
        <div className="spyphone-top">
          <span className="antenna" aria-hidden="true" />
          <span className="signal" aria-hidden="true"><i /><i /><i /></span>
        </div>
        <div className="spyphone-screen">
          <p className="tx-flash">◉ INCOMING TRANSMISSION</p>
          <h2 id="tx-title">HQ approval needed: {kindLabel}</h2>
          <div className="tx-from">
            <Penguin agent={r.requested_by} mood="waiting" size={64} />
            <div>
              <p className="tx-agent">Agent {r.requested_by.replace("_", " ")} · ticket #{r.ticket_id}</p>
              <p className="tx-summary">{r.summary}</p>
              {r.amount != null && (
                <p className="tx-amount">
                  ${r.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  {r.payee ? <span> to {r.payee}</span> : null}
                </p>
              )}
            </div>
          </div>
          <label className="tx-field">
            Your agent name (saved as approved_by)
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Emily" autoFocus />
          </label>
          <label className="tx-field">
            Reason if denying (optional)
            <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. hold until next week" />
          </label>
          {err && <p className="tx-error">{err}</p>}
          <div className="tx-buttons">
            <button className="cp-button deny" onClick={() => decide(false)} disabled={busy}>Deny</button>
            <button className="cp-button approve" onClick={() => decide(true)} disabled={busy}>Approve</button>
          </div>
          <p className="tx-note">The agents can’t move money on their own. Nothing happens until you choose.</p>
        </div>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Mission debrief (summary)
// --------------------------------------------------------------------------- //
export function Debrief({ views, run, ticket }: { views: Record<AgentName, AgentView>; run: RunState | null; ticket?: Ticket }) {
  const res = run?.result?.resolution ?? null;
  const done = run?.state === "done" || run?.state === "error";
  const involved = AGENTS.filter((a) => views[a.id].active);
  return (
    <Monitor label="MISSION DEBRIEF" light={done ? "on" : run?.state === "running" ? "busy" : "off"} className="debrief">
      {!run || run.state === "idle" ? (
        <p className="muted center">Pick a mission and deploy the team. The debrief shows up here when they report back.</p>
      ) : (
        <>
          <div className="debrief-head">
            <h3>Ticket #{run.ticket_id}{ticket ? ` · ${ticket.subject}` : ""}</h3>
            {done && run.result && (
              <span className={`stamp ${STAMP[run.result.status]?.cls ?? "stamp-open"}`}>{STAMP[run.result.status]?.label ?? run.result.status}</span>
            )}
            {!done && <span className="stamp stamp-live">IN THE FIELD</span>}
          </div>
          {res && <p className="debrief-decision">⭐ {res.decision}</p>}
          {run.result?.error && <p className="tx-error">{run.result.error}</p>}
          <div className="debrief-grid">
            {involved.map((a) => {
              const v = views[a.id];
              const tools = Object.entries(v.tools);
              return (
                <div key={a.id} className="debrief-card">
                  <div className="debrief-card-head">
                    <Penguin agent={a.id} mood="idle" size={38} />
                    <strong>{a.title}</strong>
                  </div>
                  <p>{v.report ? clip(v.report, 260) : v.mood === "working" ? "Still working…" : "No report."}</p>
                  {v.handoffsTo.length > 0 && (
                    <p className="small">Handed off to: {[...new Set(v.handoffsTo)].map((h) => h.replace("_", " ")).join(", ")}</p>
                  )}
                  {tools.length > 0 && (
                    <div className="chips">
                      {tools.map(([t, n]) => (
                        <span key={t} className="chip">{t}{n > 1 ? ` ×${n}` : ""}</span>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          {res && (res.pending_approvals.length > 0 || res.next_steps.length > 0) && (
            <div className="debrief-foot">
              {res.pending_approvals.map((p, i) => (
                <p key={i} className="small">🛡️ {p.kind.replace("_", " ")} ({p.status.replace(/_/g, " ")}): {p.summary}</p>
              ))}
              {res.next_steps.map((s, i) => (
                <p key={`n${i}`} className="small">➜ {s}</p>
              ))}
            </div>
          )}
          {done && run.result && (
            <p className="small muted">
              {run.result.usage.total_tokens.toLocaleString()} tokens · {run.result.usage.requests} model calls · {run.result.usage.tool_calls} tool calls
            </p>
          )}
        </>
      )}
    </Monitor>
  );
}

// --------------------------------------------------------------------------- //
// Filler screens with looping animations
// --------------------------------------------------------------------------- //
export function RadarScreen() {
  return (
    <Monitor label="SNOW RADAR" light="on" className="filler">
      <div className="radar">
        <div className="radar-sweep" />
        <span className="blip" style={{ top: "30%", left: "62%" }} />
        <span className="blip" style={{ top: "64%", left: "34%", animationDelay: "1.1s" }} />
        <span className="blip" style={{ top: "48%", left: "74%", animationDelay: "2.2s" }} />
        <span className="radar-ring r1" /><span className="radar-ring r2" /><span className="radar-ring r3" />
      </div>
    </Monitor>
  );
}

export function IslandScreen() {
  return (
    <Monitor label="ISLAND MAP" light="on" className="filler">
      <div className="island">
        <svg viewBox="0 0 200 120" className="island-svg" aria-hidden="true">
          <path className="island-land" d="M30 70c-6-20 12-38 34-34 8-16 32-20 46-8 18-8 42 2 46 20 16 4 22 22 12 34-8 12-30 14-44 10-12 10-38 12-52 4-18 8-40 0-42-26z" />
          <path className="island-route" d="M60 72C80 50 110 54 128 66S160 74 150 58" />
          <circle cx="60" cy="72" r="3" className="island-dot" />
          <g className="island-pin">
            <path d="M150 58c0-6-9-6-9 0 0 5 4.5 9 4.5 9s4.5-4 4.5-9z" transform="translate(4 -9)" />
          </g>
          <text x="96" y="24" className="island-label">CAMPUS CUSTOMS</text>
        </svg>
        <div className="snow" aria-hidden="true">
          {Array.from({ length: 18 }, (_, i) => (
            <i key={i} style={{ left: `${(i * 37) % 100}%`, animationDelay: `${(i * 0.53) % 5}s`, animationDuration: `${4 + (i % 4)}s` }} />
          ))}
        </div>
      </div>
    </Monitor>
  );
}

export function PuffleCam() {
  return (
    <Monitor label="PUFFLE CAM 03" light="on" className="filler">
      <div className="pufflecam">
        <span className="rec">● REC</span>
        <div className="puffle-track">
          <Puffle color="#4fc3f7" />
        </div>
        <div className="puffle-track second">
          <Puffle color="#e53935" size={40} />
        </div>
        <div className="floor" />
      </div>
    </Monitor>
  );
}

const CODE = [
  "DECRYPTING MESSAGE…", "AGENT STATUS: ACTIVE", "SNOWBALL PROTOCOL 7", "PING >> EPF NODE 3",
  "CIPHER: 0xC0FFEE", "IGLOO PERIMETER OK", "COINS VAULT SEALED", "PUFFLE SIGNAL: STRONG",
  "TRACKING HERBERT…", "NO KLUTZY SIGHTED", "MISSION LOG SYNCED", "HOT CHOCOLATE: 98%",
];

export function DecoderScreen() {
  const lines = [...CODE, ...CODE];
  return (
    <Monitor label="DECODER" light="on" className="filler">
      <div className="decoder">
        <div className="decoder-roll">
          {lines.map((l, i) => (
            <p key={i}>
              <span>{String(1000 + i * 37).padStart(4, "0")}</span> {l}
            </p>
          ))}
        </div>
      </div>
    </Monitor>
  );
}
