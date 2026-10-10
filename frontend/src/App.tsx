import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_URL, api, type AgentEvent, type Approval, type Cash, type RunState, type Ticket } from "./api";
import {
  AgentScreen, ApprovalModal, Debrief, DecoderScreen, IslandScreen, MissionBoard, PuffleCam, RadarScreen, deriveAgents,
} from "./components/Screens";

const POLL_MS = 1200;

export default function App() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [dateToday, setDateToday] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [run, setRun] = useState<RunState | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [cash, setCash] = useState<Cash | null>(null);
  const [cashFlash, setCashFlash] = useState<"down" | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [online, setOnline] = useState(true);
  const lastIndex = useRef(-1);
  const runId = useRef<string | null>(null);
  const prevBalance = useRef<number | null>(null);

  const loadTickets = useCallback(async () => {
    const t = await api.tickets();
    setTickets(t.tickets);
    setDateToday(t.date_today);
  }, []);

  const loadCash = useCallback(async () => {
    const c = await api.cash();
    if (prevBalance.current !== null && c.balance < prevBalance.current) {
      setCashFlash("down");
      setTimeout(() => setCashFlash(null), 2500);
    }
    prevBalance.current = c.balance;
    setCash(c);
  }, []);

  // First load; pick up a run that is already going (e.g. after a page refresh).
  useEffect(() => {
    (async () => {
      try {
        await Promise.all([loadTickets(), loadCash()]);
        // Read-only replay of a finished run: http://localhost:5173/?run=<run_id>
        const replay = new URLSearchParams(location.search).get("run");
        if (replay) {
          const past = await api.pastRun(replay);
          const ev = await api.events(-1, replay);
          runId.current = replay;
          lastIndex.current = ev.last_index;
          setSelected(past.ticket_id);
          setEvents(ev.events);
          setRun(past);
          setOnline(true);
          return;
        }
        const r = await api.runState();
        if (r.state !== "idle" && r.run_id) {
          runId.current = r.run_id;
          setSelected(r.ticket_id);
          const ev = await api.events(-1, r.run_id);
          lastIndex.current = ev.last_index;
          setEvents(ev.events);
        }
        setRun(r);
        setOnline(true);
      } catch {
        setOnline(false);
      }
    })();
  }, [loadTickets, loadCash]);

  // Live polling while a mission runs.
  const running = run?.state === "running";
  useEffect(() => {
    if (!running) return;
    let stop = false;
    const tick = async () => {
      try {
        const [ev, r, ap] = await Promise.all([
          api.events(lastIndex.current, runId.current ?? undefined),
          api.runState(),
          api.approvals(),
        ]);
        if (stop) return;
        if (ev.events.length) setEvents((old) => [...old, ...ev.events]);
        lastIndex.current = ev.last_index;
        setApprovals(ap);
        setRun(r);
        setOnline(true);
        if (r.state !== "running") {
          const rest = await api.events(lastIndex.current, runId.current ?? undefined);
          if (rest.events.length) setEvents((old) => [...old, ...rest.events]);
          lastIndex.current = rest.last_index;
          setApprovals([]);
          await Promise.all([loadTickets(), loadCash()]);
        }
      } catch {
        setOnline(false);
      }
    };
    const id = setInterval(tick, POLL_MS);
    tick();
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, [running, loadTickets, loadCash]);

  // While idle, watch for a run started somewhere else (CLI, API, another tab) and join it.
  useEffect(() => {
    if (running) return;
    const id = setInterval(async () => {
      try {
        const r = await api.runState();
        if (r.state === "running" && r.run_id && r.run_id !== runId.current) {
          runId.current = r.run_id;
          setSelected(r.ticket_id);
          const ev = await api.events(-1, r.run_id);
          lastIndex.current = ev.last_index;
          setEvents(ev.events);
          setRun(r);
        }
      } catch {
        setOnline(false);
      }
    }, 2500);
    return () => clearInterval(id);
  }, [running]);

  // Cash ticker refresh.
  useEffect(() => {
    const id = setInterval(() => loadCash().catch(() => setOnline(false)), running ? 2000 : 6000);
    return () => clearInterval(id);
  }, [running, loadCash]);

  async function startMission() {
    if (selected == null) return;
    setStarting(true);
    setError(null);
    try {
      const r = await api.run(selected);
      runId.current = r.run_id;
      const ev = await api.events(-1, r.run_id ?? undefined);
      lastIndex.current = ev.last_index;
      setEvents(ev.events);
      setApprovals([]);
      setRun(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setStarting(false);
    }
  }

  async function decide(ok: boolean, name: string, reason: string) {
    const a = approvals[0];
    await api.decide(a.id, ok, ok ? name : undefined, ok ? undefined : reason || undefined);
    setApprovals((list) => list.filter((x) => x.id !== a.id));
    setTimeout(() => loadCash().catch(() => undefined), 1500);
  }

  async function reset() {
    if (!confirm("Reset campus_customs_new.db to the original values? This undoes every payment and ticket update.")) return;
    try {
      await api.reset();
      setEvents([]);
      setRun({ state: "idle", run_id: null, ticket_id: null, started_at: null, finished_at: null, result: null, pending_approvals: 0 });
      runId.current = null;
      prevBalance.current = null;
      await Promise.all([loadTickets(), loadCash()]);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const views = useMemo(() => deriveAgents(events, running), [events, running]);
  const currentTicket = tickets.find((t) => t.id === (run?.ticket_id ?? selected));

  return (
    <div className="hq">
      <div className="hq-wall" aria-hidden="true" />
      <header className="hq-top">
        <div className="badge">
          <span className="badge-shield">CC</span>
          <div>
            <h1>Secret Agent HQ</h1>
            <p>Campus Customs Secret Agency · ticket desk</p>
          </div>
        </div>
        <div className={`vault ${cashFlash ? "vault-down" : ""}`} title="Checking balance from cash_accounts">
          <span className="coin" aria-hidden="true">$</span>
          <div>
            <p className="vault-label">Checking · coin vault</p>
            <p className="vault-amount">
              {cash ? `$${cash.balance.toLocaleString(undefined, { minimumFractionDigits: 2 })}` : "…"}
            </p>
          </div>
        </div>
        <div className="top-actions">
          <span className={`net ${online ? "net-on" : "net-off"}`}>{online ? "● HQ link online" : `● Can't reach ${API_URL}`}</span>
          <button className="cp-button small ghost" onClick={reset} disabled={running}>Reset DB</button>
        </div>
      </header>

      {error && (
        <div className="toast" onClick={() => setError(null)}>⚠ {error}</div>
      )}

      <main className="hq-grid">
        <div className="area-board">
          <MissionBoard
            tickets={tickets}
            selected={selected}
            onSelect={setSelected}
            onStart={startMission}
            run={run}
            starting={starting}
            dateToday={dateToday}
          />
        </div>
        <div className="area-boss"><AgentScreen agent="boss" view={views.boss} big /></div>
        <div className="area-radar"><RadarScreen /></div>
        <div className="area-inv"><AgentScreen agent="inventory" view={views.inventory} /></div>
        <div className="area-acc"><AgentScreen agent="accounting" view={views.accounting} /></div>
        <div className="area-island"><IslandScreen /></div>
        <div className="area-fac"><AgentScreen agent="facilities" view={views.facilities} /></div>
        <div className="area-cs"><AgentScreen agent="customer_service" view={views.customer_service} /></div>
        <div className="area-puffle"><PuffleCam /></div>
        <div className="area-debrief"><Debrief views={views} run={run} ticket={currentTicket} /></div>
        <div className="area-decoder"><DecoderScreen /></div>
      </main>

      <footer className="hq-foot">Agents run on gpt-6-luna · every payment, order, and discount needs a human Approve · drafts are never sent</footer>

      {approvals.length > 0 && <ApprovalModal key={approvals[0].id} approval={approvals[0]} onDecide={decide} />}
    </div>
  );
}
