import type { AgentName } from "../api";

// Club Penguin–style spy penguins, drawn in SVG (no image files):
// pear-shaped body with a thick darker outline, heart-shaped white face,
// separate white belly, wide two-part beak, side flippers, flat orange
// feet with scalloped toes, and classic black agent shades.
const LOOK: Record<AgentName, { body: string; line: string; shine: string }> = {
  boss: { body: "#33363d", line: "#141518", shine: "#4a4e57" },
  inventory: { body: "#3cb043", line: "#1f6e25", shine: "#62cc68" },
  accounting: { body: "#f5c518", line: "#a5800a", shine: "#ffe066" },
  facilities: { body: "#f07f22", line: "#9c4a0c", shine: "#ffa152" },
  customer_service: { body: "#f26fb2", line: "#a83a72", shine: "#ff99cc" },
};

const BEAK = { fill: "#fbb03b", shade: "#f08c1a", line: "#b85f00" };
const FEET = { fill: "#fbb03b", line: "#b85f00" };

export type Mood = "idle" | "working" | "done" | "waiting";

export function Penguin({ agent, mood = "idle", size = 110 }: { agent: AgentName; mood?: Mood; size?: number }) {
  const c = LOOK[agent];
  return (
    <svg
      className={`penguin penguin-${mood}`}
      viewBox="0 0 120 140"
      width={size}
      height={(size * 140) / 120}
      role="img"
      aria-label={`${agent} penguin agent`}
    >
      <ellipse cx="60" cy="135" rx="36" ry="4.5" fill="rgba(0,0,0,.35)" />

      {/* feet: flat orange paddles with three scalloped toes */}
      <g className="feet" fill={FEET.fill} stroke={FEET.line} strokeWidth="2.5" strokeLinejoin="round">
        <path d="M26 126c-6 2-7 8-2 9 3 1 5-1 7 0 3 1 5-1 8 0 3 1 6 0 9 0 4 0 4-6 0-8-6-3-15-3-22-1z" />
        <path d="M94 126c6 2 7 8 2 9-3 1-5-1-7 0-3 1-5-1-8 0-3 1-6 0-9 0-4 0-4-6 0-8 6-3 15-3 22-1z" />
      </g>

      <g className="pbody">
        {/* flippers, drawn behind the body so they read as sticking out */}
        <g className="flipper-l">
          <path d="M28 70c-12 10-19 26-17 38 1 4 5 4 8 1 6-8 12-18 17-27z" fill={c.body} stroke={c.line} strokeWidth="3" strokeLinejoin="round" />
        </g>
        <g className="flipper-r">
          <path d="M92 70c12 10 19 26 17 38-1 4-5 4-8 1-6-8-12-18-17-27z" fill={c.body} stroke={c.line} strokeWidth="3" strokeLinejoin="round" />
        </g>

        {/* pear-shaped body: big round head flowing into a wide bottom */}
        <path
          d="M60 10c22 0 33 15 32 36-1 9-2 14 1 22 7 16 12 30 9 44-3 15-20 20-42 20s-39-5-42-20c-3-14 2-28 9-44 3-8 2-13 1-22-1-21 10-36 32-36z"
          fill={c.body} stroke={c.line} strokeWidth="3.5" strokeLinejoin="round"
        />
        {/* soft highlight on the head */}
        <path d="M40 22c6-6 14-8 20-8" stroke={c.shine} strokeWidth="5" strokeLinecap="round" fill="none" opacity=".7" />

        {/* white belly */}
        <path d="M60 74c16 0 27 15 28 32 1 15-11 22-28 22s-29-7-28-22c1-17 12-32 28-32z" fill="#fff" />
        {/* heart-shaped white face around the eyes */}
        <path d="M60 33c-6-9-26-10-29 6-3 15 10 26 29 29 19-3 32-14 29-29-3-16-23-15-29-6z" fill="#fff" />

        {/* classic black agent shades */}
        <g className="shades">
          <path d="M31 39c9-4 20-4 29-1 9-3 20-3 29 1l-1 9c-2 7-9 10-16 9-6-1-10-5-12-9-2 4-6 8-12 9-7 1-14-2-16-9z" fill="#111" />
          <path d="M36 42c4-1 8-1 11 0" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" opacity=".55" />
          <path d="M66 42c4-1 8-1 11 0" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" opacity=".55" />
        </g>

        {/* wide two-part beak */}
        <g className="beak" stroke={BEAK.line} strokeWidth="2" strokeLinejoin="round">
          <path d="M47 60c4-4 22-4 26 0-2 5-8 8-13 8s-11-3-13-8z" fill={BEAK.fill} />
          <path d="M51 64c4 2 14 2 18 0-2 4-5 6-9 6s-7-2-9-6z" fill={BEAK.shade} />
        </g>

        <Accessory agent={agent} />
      </g>
    </svg>
  );
}

function Accessory({ agent }: { agent: AgentName }) {
  switch (agent) {
    case "boss": // red bow tie + gold agent badge
      return (
        <g>
          <g stroke="#7a0a1a" strokeWidth="1.5" strokeLinejoin="round">
            <path d="M48 72l11 4-11 5z" fill="#d7192f" />
            <path d="M72 72l-11 4 11 5z" fill="#d7192f" />
            <circle cx="60" cy="76.5" r="3" fill="#a3101f" />
          </g>
          <circle cx="74" cy="100" r="7" fill="#ffd34d" stroke="#b8860b" strokeWidth="2" />
          <path d="M74 95.5l1.4 2.9 3.2.4-2.3 2.2.6 3.1-2.9-1.5-2.9 1.5.6-3.1-2.3-2.2 3.2-.4z" fill="#b8860b" />
        </g>
      );
    case "inventory": // clipboard held by the flipper
      return (
        <g className="prop" stroke="#5c3b17" strokeWidth="2" strokeLinejoin="round">
          <rect x="88" y="92" width="22" height="28" rx="3" fill="#b07a3e" />
          <rect x="91" y="97" width="16" height="20" rx="1" fill="#fff" stroke="none" />
          <rect x="95" y="89" width="8" height="5" rx="1.5" fill="#9aa0a6" />
          <path d="M93 103h12M93 107h12M93 111h8" stroke="#3cb043" strokeWidth="1.6" />
        </g>
      );
    case "accounting": // green visor + gold coin
      return (
        <g>
          <path d="M30 27c18-10 42-10 60 0l-5 7c-15-7-35-7-50 0z" fill="#2fb36b" stroke="#17703f" strokeWidth="2" strokeLinejoin="round" />
          <g className="prop">
            <circle cx="99" cy="106" r="10" fill="#ffd34d" stroke="#b8860b" strokeWidth="2.5" />
            <text x="99" y="110.5" textAnchor="middle" fontSize="12" fontWeight="900" fill="#b8860b">$</text>
          </g>
        </g>
      );
    case "facilities": // yellow hard hat + wrench
      return (
        <g>
          <g stroke="#9a7b00" strokeWidth="2" strokeLinejoin="round">
            <path d="M32 26c2-14 14-20 28-20s26 6 28 20z" fill="#ffd400" />
            <rect x="26" y="24" width="68" height="7" rx="3.5" fill="#ffcc00" />
            <rect x="56" y="5" width="8" height="12" rx="3" fill="#ffcc00" />
          </g>
          <g className="prop" stroke="#5f6870" strokeWidth="1.5">
            <rect x="94" y="94" width="5" height="24" rx="2" transform="rotate(25 96 106)" fill="#aab3bb" />
            <circle cx="101" cy="92" r="6" fill="none" stroke="#aab3bb" strokeWidth="4" />
          </g>
        </g>
      );
    case "customer_service": // headset + postcard
      return (
        <g>
          <path d="M26 46c0-26 15-36 34-36s34 10 34 36" stroke="#2a2a2a" strokeWidth="5" fill="none" strokeLinecap="round" />
          <rect x="20" y="40" width="11" height="17" rx="5" fill="#2a2a2a" />
          <rect x="89" y="40" width="11" height="17" rx="5" fill="#2a2a2a" />
          <path d="M25 56c1 10 10 13 20 11" stroke="#2a2a2a" strokeWidth="2.5" fill="none" strokeLinecap="round" />
          <circle cx="46" cy="67" r="3.2" fill="#2a2a2a" />
          <g className="prop" stroke="#b39b5f" strokeWidth="1.5">
            <rect x="88" y="96" width="26" height="18" rx="2" fill="#fff6d8" />
            <path d="M88 96l13 9 13-9" fill="none" />
          </g>
        </g>
      );
  }
}

export function Puffle({ color = "#4fc3f7", size = 54 }: { color?: string; size?: number }) {
  return (
    <svg className="puffle" viewBox="0 0 60 60" width={size} height={size} aria-hidden="true">
      <ellipse cx="30" cy="56" rx="16" ry="3" fill="rgba(0,0,0,.3)" className="puffle-shadow" />
      <g className="puffle-body">
        <path d="M30 6l3 6 4-5 1 7 6-3-2 7" stroke={color} strokeWidth="3" fill="none" strokeLinecap="round" />
        <circle cx="30" cy="34" r="19" fill={color} />
        <ellipse cx="23" cy="31" rx="5" ry="6.5" fill="#fff" />
        <ellipse cx="37" cy="31" rx="5" ry="6.5" fill="#fff" />
        <circle cx="24" cy="32" r="2.6" fill="#111" />
        <circle cx="36" cy="32" r="2.6" fill="#111" />
        <path d="M24 41q6 5 12 0" stroke="#111" strokeWidth="2" fill="none" strokeLinecap="round" />
      </g>
    </svg>
  );
}
