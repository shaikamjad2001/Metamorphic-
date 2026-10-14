import { useEffect, useState } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, ReferenceLine, CartesianGrid } from "recharts";
import { FileText } from "lucide-react";
import { api, type Analysis, type Meta, type RunResult } from "../api";
import FlowGraph from "../components/FlowGraph";
import { Badge, Card, Empty, KV, Segmented, Spinner } from "../components/ui";
import { AGENT_COLORS } from "../lib/format";

const fmt = (v: any): string => {
  if (v == null) return "—";
  if (Array.isArray(v)) return v.length ? v.map(fmt).join(", ") : "[]";
  if (typeof v === "object") return Object.entries(v).filter(([, x]) => x != null).map(([k, x]) => `${k}=${fmt(x)}`).join(" ");
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(4);
  return String(v);
};

export default function WorkflowPage({ analysis, meta }: { analysis: Analysis | null; meta: Meta }) {
  const [source, setSource] = useState<"live" | "evidence">("live");
  const [evidence, setEvidence] = useState<RunResult | null>(null);
  const [loading, setLoading] = useState(false);

  const pickEvidence = async () => {
    setSource("evidence");
    if (!evidence) {
      setLoading(true);
      try { setEvidence(await api.trace()); } finally { setLoading(false); }
    }
  };
  const liveD = analysis?.result.diagnostics;
  const liveLoops = liveD ? (liveD.feedback_cycles ?? 0) + (liveD.refinement_cycles ?? 0) : 0;
  useEffect(() => {
    if (!liveLoops) pickEvidence();
  }, []);
  const r = source === "live" ? analysis?.result ?? null : evidence;
  const th = meta.thresholds;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="label">Control flow (cycles marked)</div>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900">Five agents, two loops, one supervisor</h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-500">
            Not a linear pipeline: the Quality Auditor sends work back to the Data Scout (feedback loop), the Synthesizer decides
            whether to stop or iterate on confidence (conditional loop), and upstream outputs change which strategy downstream agents
            execute (genuine dependency).
          </p>
        </div>
        <Segmented value={source} onChange={(v) => (v === "evidence" ? pickEvidence() : setSource("live"))} options={[
          { value: "live", label: "Your last run" }, { value: "evidence", label: <span className="flex items-center gap-1"><FileText size={13} /> Recorded evidence trace</span> },
        ]} />
      </div>

      {source === "evidence" && evidence && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-900">
          Recorded evidence: <b>{evidence.criteria.label ?? "base input"}</b>, seed {evidence.seed}, the first base input where both loops fire
          (<code className="font-mono text-xs">results/loop_trace.log</code>).
          {!liveLoops && analysis && " Your last run met the coverage and confidence targets on the first pass, so no loop was needed."}
        </div>
      )}
      {loading && <Card><div className="flex items-center gap-2 text-sm text-slate-500"><Spinner /> Loading trace…</div></Card>}
      {!r && !loading && <Card><Empty>Run an analysis on the Market Trends tab first.</Empty></Card>}
      {r && <TraceView r={r} th={th} />}
    </div>
  );
}

function TraceView({ r, th }: { r: RunResult; th: Record<string, any> }) {
  const d = r.diagnostics;
  const conf = (d.confidence_history ?? []).map((c: number, i: number) => ({ cycle: i, confidence: c }));
  const cov = (d.audit_history ?? []).map((a: any) => ({ cycle: a.iteration, coverage: a.coverage }));
  return (
    <>
      <Card pad={false}>
        <div className="p-4"><FlowGraph events={r.events} feedback={d.feedback_cycles} refinement={d.refinement_cycles} /></div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Feedback loop: coverage per cycle" subtitle={`A month passes with ≥ ${th.min_zips_per_month} ZIPs and ≥ ${th.min_active_per_month} active listings`}>
          <ResponsiveContainer width="100%" height={170}>
            <LineChart data={cov}>
              <CartesianGrid stroke="#f1f5f9" vertical={false} />
              <XAxis dataKey="cycle" tickLine={false} axisLine={false} />
              <YAxis domain={[0, 1]} width={32} tickLine={false} axisLine={false} />
              <ReferenceLine y={1} stroke="#10b981" strokeDasharray="4 3" />
              <Tooltip />
              <Line isAnimationActive={false} dataKey="coverage" stroke="#f59e0b" strokeWidth={2.5} dot={{ r: 4 }} />
            </LineChart>
          </ResponsiveContainer>
        </Card>
        <Card title="Refinement loop: confidence per cycle" subtitle={`Stops at ${th.confidence_target} or when the supervisor halts`}>
          <ResponsiveContainer width="100%" height={170}>
            <LineChart data={conf}>
              <CartesianGrid stroke="#f1f5f9" vertical={false} />
              <XAxis dataKey="cycle" tickLine={false} axisLine={false} />
              <YAxis domain={[0, 1]} width={32} tickLine={false} axisLine={false} />
              <ReferenceLine y={th.confidence_target} stroke="#10b981" strokeDasharray="4 3" />
              <Tooltip />
              <Line isAnimationActive={false} dataKey="confidence" stroke="#0ea5e9" strokeWidth={2.5} dot={{ r: 4 }} />
            </LineChart>
          </ResponsiveContainer>
        </Card>
        <Card title="Recorded control plan" subtitle="Replaying it gives the pinned ablation">
          <KV k="Relaxation level" v={`${r.control.relaxation_level} (±${Math.round(r.control.relaxation_factor * 100)}%)`} />
          <KV k="Added ZIPs" v={r.control.added_zips.join(", ") || "none"} />
          <KV k="Method" v={r.control.method} />
          <KV k="Refinements kept" v={r.control.refinements.join(" → ") || "none"} />
          <KV k="Supervisor halts" v={(d.supervisor_halts ?? []).join("; ") || "none"} />
          <KV k="Seed" v={r.seed} />
        </Card>
      </div>

      <Card title="Execution trace" subtitle={`${r.events.length} events · ${d.runtime_ms} ms`} pad={false}>
        <ol className="divide-y divide-slate-100">
          {r.events.map((e) => (
            <li key={e.step} className="grid grid-cols-[48px_150px_190px_minmax(0,1fr)] items-start gap-3 px-5 py-2.5 text-sm">
              <span className="font-mono text-xs text-slate-400">#{e.step}<br />{e.elapsed_ms.toFixed(1)}ms</span>
              <span className="flex items-center gap-2 font-semibold" style={{ color: AGENT_COLORS[e.agent] }}>
                <span className="h-2 w-2 rounded-full" style={{ background: AGENT_COLORS[e.agent] }} />{e.agent}
              </span>
              <span className="flex flex-wrap items-center gap-1.5">
                <span className="font-medium text-slate-800">{e.action.replaceAll("_", " ")}</span>
                {e.loop && <Badge tone={e.loop === "feedback" ? "amber" : "sky"}>{e.loop} #{e.iteration}</Badge>}
              </span>
              <span className="font-mono text-[11.5px] leading-relaxed text-slate-500">
                {Object.entries(e.detail).filter(([k]) => k !== "thresholds").map(([k, v]) => (
                  <span key={k} className="mr-3 inline-block"><span className="text-slate-400">{k}=</span>{fmt(v)}</span>
                ))}
              </span>
            </li>
          ))}
        </ol>
      </Card>
    </>
  );
}
