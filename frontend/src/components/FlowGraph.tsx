import type { AgentEvent } from "../api";
import { AGENT_COLORS } from "../lib/format";

type Node = { id: string; label: string; sub: string; x: number; y: number; w?: number };

const NODES: Node[] = [
  { id: "User", label: "User criteria", sub: "form or plain English", x: 90, y: 130, w: 140 },
  { id: "Orchestrator", label: "1 · Orchestrator", sub: "validate & resolve", x: 290, y: 130 },
  { id: "DataScout", label: "2 · Data Scout", sub: "slice frozen snapshot", x: 520, y: 130 },
  { id: "QualityAuditor", label: "3 · Quality Auditor", sub: "per-month coverage", x: 790, y: 130 },
  { id: "TrendSpecialist", label: "4 · Trend Specialist", sub: "hedonic | median", x: 790, y: 330 },
  { id: "Synthesizer", label: "5 · Synthesizer", sub: "bootstrap confidence", x: 520, y: 330 },
  { id: "Output", label: "TrendOutput", sub: "12-month contract", x: 290, y: 330, w: 140 },
  { id: "LoopSupervisor", label: "Loop Supervisor", sub: "I1 caps · I2 monotone · I3 progress · I4 clock", x: 655, y: 525, w: 300 },
];
const W = 190, H = 58;

function Box({ n, count, active, current }: { n: Node; count: number; active: boolean; current: boolean }) {
  const w = n.w ?? W;
  const color = AGENT_COLORS[n.id] ?? "#64748b";
  return (
    <g transform={`translate(${n.x - w / 2},${n.y - H / 2})`}>
      {current && (
        <rect x={-6} y={-6} width={w + 12} height={H + 12} rx={18} fill="none" stroke={color} strokeWidth={3} className="agent-pulse" />
      )}
      <rect width={w} height={H} rx={14} fill={current ? `${color}14` : "white"} stroke={active ? color : "#e2e8f0"} strokeWidth={active ? 2 : 1.2}
        style={{ filter: active ? `drop-shadow(0 6px 14px ${color}33)` : undefined }} />
      <rect width={6} height={H - 20} x={0} y={10} rx={3} fill={color} opacity={n.id === "User" || n.id === "Output" ? 0.25 : 1} />
      <text x={18} y={25} fontSize={13} fontWeight={700} fill="#0f172a">{n.label}</text>
      <text x={18} y={43} fontSize={11} fill="#64748b">{n.sub}</text>
      {count > 0 && (
        <g transform={`translate(${w - 14},-8)`}>
          <circle r={11} fill={color} />
          <text textAnchor="middle" y={4} fontSize={11} fontWeight={700} fill="white">{count}</text>
        </g>
      )}
    </g>
  );
}

export default function FlowGraph({ events, feedback, refinement, current }: {
  events: Pick<AgentEvent, "agent">[]; feedback: number; refinement: number; current?: string | null;
}) {
  const counts: Record<string, number> = {};
  events.forEach((e) => (counts[e.agent] = (counts[e.agent] ?? 0) + 1));
  const n = Object.fromEntries(NODES.map((x) => [x.id, x]));
  const arrow = (id: string, color: string) => (
    <marker id={id} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill={color} />
    </marker>
  );
  const line = (a: string, b: string, label?: string) => {
    const A = n[a], B = n[b];
    const horiz = A.y === B.y;
    const x1 = horiz ? A.x + (B.x > A.x ? 1 : -1) * ((A.w ?? W) / 2) : A.x;
    const x2 = horiz ? B.x - (B.x > A.x ? 1 : -1) * ((B.w ?? W) / 2 + 4) : B.x;
    const y1 = horiz ? A.y : A.y + H / 2;
    const y2 = horiz ? B.y : B.y - H / 2 - 4;
    return (
      <g>
        <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#94a3b8" strokeWidth={1.6} markerEnd="url(#a-gray)" />
        {label && <text x={(x1 + x2) / 2 + (horiz ? 0 : 8)} y={(y1 + y2) / 2 + (horiz ? -8 : 4)} fontSize={10.5} fill="#64748b" textAnchor={horiz ? "middle" : "start"}>{label}</text>}
      </g>
    );
  };

  return (
    <svg viewBox="0 0 960 570" className="w-full">
      <defs>
        {arrow("a-gray", "#94a3b8")}
        {arrow("a-amber", "#f59e0b")}
        {arrow("a-sky", "#0ea5e9")}
        {arrow("a-red", "#ef4444")}
      </defs>
      {line("User", "Orchestrator")}
      {line("Orchestrator", "DataScout")}
      {line("DataScout", "QualityAuditor", "scan")}
      {line("QualityAuditor", "TrendSpecialist", "coverage ok → method switch")}
      {line("TrendSpecialist", "Synthesizer", "draft trend")}
      {line("Synthesizer", "Output", "conf ≥ 0.85")}

      <path d={`M ${n.QualityAuditor.x - 40} ${n.QualityAuditor.y - H / 2} C ${n.QualityAuditor.x - 60} 50, ${n.DataScout.x + 60} 50, ${n.DataScout.x + 40} ${n.DataScout.y - H / 2 - 4}`}
        fill="none" stroke="#f59e0b" strokeWidth={2.4} markerEnd="url(#a-amber)" className={feedback ? "flow-dash" : ""} strokeDasharray={feedback ? undefined : "6 4"} />
      <rect x={525} y={6} width={260} height={38} rx={12} fill="#fffbeb" stroke="#fcd34d" />
      <text x={655} y={21} fontSize={10.5} fontWeight={700} fill="#b45309" textAnchor="middle">⟲ FEEDBACK LOOP {feedback ? `· fired ×${feedback}` : "· not needed"}</text>
      <text x={655} y={36} fontSize={10} fill="#92400e" textAnchor="middle">sparse months → relax bands ±15/30/45% · add ZIPs</text>

      <path d={`M ${n.Synthesizer.x + 40} ${n.Synthesizer.y + H / 2} C ${n.Synthesizer.x + 70} 430, ${n.TrendSpecialist.x - 70} 430, ${n.TrendSpecialist.x - 40} ${n.TrendSpecialist.y + H / 2 + 4}`}
        fill="none" stroke="#0ea5e9" strokeWidth={2.4} markerEnd="url(#a-sky)" className={refinement ? "flow-dash" : ""} strokeDasharray={refinement ? undefined : "6 4"} />
      <rect x={525} y={424} width={260} height={38} rx={12} fill="#f0f9ff" stroke="#7dd3fc" />
      <text x={655} y={439} fontSize={10.5} fontWeight={700} fill="#0369a1" textAnchor="middle">⟲ REFINEMENT LOOP {refinement ? `· fired ×${refinement}` : "· not needed"}</text>
      <text x={655} y={454} fontSize={10} fill="#075985" textAnchor="middle">conf &lt; 0.85 → trim outliers / pool months</text>

      <path d={`M ${n.LoopSupervisor.x + 150} ${n.LoopSupervisor.y} L 935 ${n.LoopSupervisor.y} L 935 ${n.QualityAuditor.y} L ${n.QualityAuditor.x + W / 2 + 6} ${n.QualityAuditor.y}`}
        stroke="#ef4444" strokeDasharray="3 4" strokeWidth={1.3} fill="none" markerEnd="url(#a-red)" />
      <path d={`M ${n.LoopSupervisor.x} ${n.LoopSupervisor.y - H / 2} L ${n.LoopSupervisor.x} 466`} stroke="#ef4444" strokeDasharray="3 4" strokeWidth={1.3} fill="none" markerEnd="url(#a-red)" />
      <text x={945} y={330} fontSize={10} fill="#b91c1c" textAnchor="middle" transform="rotate(90 945 330)">supervisor guards both loops</text>

      {NODES.map((x) => <Box key={x.id} n={x} count={counts[x.id] ?? 0} active={(counts[x.id] ?? 0) > 0} current={current === x.id} />)}
    </svg>
  );
}
