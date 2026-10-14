import { useEffect, useMemo, useRef, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Bot, ExternalLink, RotateCcw, Send, Sparkles, User } from "lucide-react";
import { chatStream, type ChatItem, type ChatRunSummary, type Criteria, type Meta } from "../api";
import FlowGraph from "../components/FlowGraph";
import { Badge, Spinner } from "../components/ui";
import { AGENT_COLORS, money, monthLabel, num, pct } from "../lib/format";

type Step = { agent: string; action: string; loop: string | null; iteration: number | null; detail: Record<string, any>; run: number | null };

type Msg = {
  id: number;
  role: "user" | "assistant";
  text: string;
  status: "thinking" | "done" | "error";
  steps: Step[];
  plan?: { intent: string; planner: string; notes: string[]; labels: string[] };
  runLabels: Record<number, string>;
  runs: Record<number, ChatRunSummary>;
  errors: string[];
  answer?: { text: string; writer: string; intent: string; facts: any };
  elapsed?: number;
  context?: any;
};

const SUGGESTIONS = [
  "How did prices change in Plano?",
  "Compare Frisco vs McKinney under $700k",
  "Which ZIPs fell the most in Dallas?",
  "Which cities grew fastest?",
  "Luxury homes 2024 vs 2025",
  "3 bedroom homes in 75204",
  "What happened to mortgage rates?",
  "Which MR was violated most and why?",
  "Show me an MR2 violation",
  "Test MR5 live",
  "How do the agents work?",
];

const PALETTE = ["#4f46e5", "#f59e0b", "#10b981", "#ef4444", "#0ea5e9", "#8b5cf6"];

const INTENT_LABEL: Record<string, string> = {
  trend: "12-month trend", compare: "comparison", rank: "ranking", listings: "listing lookup",
  macro: "macro indicators", testing: "metamorphic testing", system: "how it works", help: "out of scope",
};

const AGENT_NAME: Record<string, string> = {
  Orchestrator: "Orchestrator", DataScout: "Data Scout", QualityAuditor: "Quality Auditor",
  TrendSpecialist: "Trend Specialist", Synthesizer: "Synthesizer", LoopSupervisor: "Loop Supervisor",
};

const BRIEF_KEYS = ["question", "intent", "slices", "planner", "n_zips", "window", "records_in_window", "relaxation_factor",
  "added_zips", "coverage", "sparse_months", "next_action", "reason", "feedback_action", "method", "sqft_cv", "bed_sigma",
  "directive", "refinements", "trend_change_pct", "confidence", "verdict", "invariant", "tool", "indicators", "n",
  "n_runs", "writer", "error", "metric", "level"];

function brief(d: Record<string, any>): string {
  const out: string[] = [];
  for (const k of BRIEF_KEYS) {
    if (!(k in d)) continue;
    let v = d[k];
    if (v == null || (Array.isArray(v) && !v.length)) continue;
    if (k === "sparse_months") v = `${v.length} sparse`;
    else if (k === "window" && Array.isArray(v)) v = `${v[0]}…${v[1]}`;
    else if (Array.isArray(v)) v = v.slice(0, 4).join(", ") + (v.length > 4 ? "…" : "");
    else if (typeof v === "number") v = Number.isInteger(v) ? v : v.toFixed(3);
    else if (typeof v === "object") v = JSON.stringify(v);
    out.push(k === "question" ? `“${v}”` : `${k.replaceAll("_", " ")}: ${v}`);
    if (out.length >= 4) break;
  }
  return out.join(" · ");
}

export default function ChatPage({ meta, onOpen }: { meta: Meta; onOpen: (c: Criteria) => void }) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [seed, setSeed] = useState(42);
  const queue = useRef<{ id: number; item: ChatItem }[]>([]);
  const pumping = useRef(false);
  const streamDone = useRef(true);
  const idRef = useRef(1);
  const scroller = useRef<HTMLDivElement>(null);

  const patch = (id: number, f: (m: Msg) => Msg) => setMsgs((ms) => ms.map((m) => (m.id === id ? f(m) : m)));

  const apply = (id: number, it: ChatItem) => {
    if (it.type === "event") {
      const e = it.event;
      patch(id, (m) => ({ ...m, steps: [...m.steps, { agent: e.agent, action: e.action, loop: e.loop ?? null, iteration: e.iteration ?? null, detail: e.detail, run: it.run }] }));
    } else if (it.type === "plan") patch(id, (m) => ({ ...m, plan: it.plan }));
    else if (it.type === "run_start") patch(id, (m) => ({ ...m, runLabels: { ...m.runLabels, [it.run]: it.label } }));
    else if (it.type === "run_result") patch(id, (m) => ({ ...m, runs: { ...m.runs, [it.run]: it.summary } }));
    else if (it.type === "run_error") patch(id, (m) => ({ ...m, errors: [...m.errors, `${it.label}: ${it.error}`] }));
    else if (it.type === "answer") patch(id, (m) => ({ ...m, answer: it, context: it.context }));
    else if (it.type === "done") patch(id, (m) => ({ ...m, status: "done", elapsed: it.elapsed_ms }));
    else if (it.type === "error") patch(id, (m) => ({ ...m, status: "error", errors: [...m.errors, it.text] }));
  };

  const pump = () => {
    if (pumping.current) return;
    pumping.current = true;
    const tick = () => {
      const next = queue.current.shift();
      if (!next) {
        pumping.current = false;
        if (streamDone.current) setBusy(false);
        return;
      }
      apply(next.id, next.item);
      const pending = queue.current.filter((q) => q.item.type === "event").length;
      const delay = next.item.type === "event" ? Math.max(18, Math.min(150, 3200 / Math.max(1, pending))) : 0;
      setTimeout(tick, delay);
    };
    tick();
  };

  const ask = async (q: string) => {
    q = q.trim();
    if (!q || busy) return;
    const uid = idRef.current++;
    const aid = idRef.current++;
    const lastCtx = [...msgs].reverse().find((m) => m.role === "assistant" && m.context)?.context ?? null;
    setMsgs((ms) => [...ms,
      { id: uid, role: "user", text: q, status: "done", steps: [], runLabels: {}, runs: {}, errors: [] },
      { id: aid, role: "assistant", text: "", status: "thinking", steps: [], runLabels: {}, runs: {}, errors: [] }]);
    setSelected(aid);
    setInput("");
    setBusy(true);
    streamDone.current = false;
    try {
      await chatStream(q, seed, lastCtx, (item) => {
        queue.current.push({ id: aid, item });
        pump();
      });
    } catch (e: any) {
      queue.current.push({ id: aid, item: { type: "error", text: e.message } });
      pump();
    } finally {
      streamDone.current = true;
      if (!pumping.current) setBusy(false);
    }
  };

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [msgs]);

  const autoAsked = useRef(false);
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("q");
    if (q && !autoAsked.current) {
      autoAsked.current = true;
      ask(q);
    }
  }, []);

  const sel = msgs.find((m) => m.id === selected) ?? [...msgs].reverse().find((m) => m.role === "assistant");

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_560px]">
      <section className="card flex h-[calc(100vh-112px)] flex-col overflow-hidden">
        <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-3">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900"><Sparkles size={15} className="text-indigo-500" /> Ask the agents</h2>
            <p className="text-xs text-slate-500">Any question about Dallas listings, the agents, or their tests. Every number comes from the agents running on the real snapshot.</p>
          </div>
          <div className="flex shrink-0 items-center gap-2 whitespace-nowrap">
            <Badge tone={meta.llm ? "green" : "slate"}>{meta.llm ? `LLM: ${meta.llm}` : "Rule-based planner (no LLM key)"}</Badge>
            {msgs.length > 0 && (
              <button className="btn-ghost px-2.5 py-1.5 text-xs" onClick={() => { setMsgs([]); setSelected(null); }} disabled={busy}>
                <RotateCcw size={13} /> New chat
              </button>
            )}
          </div>
        </header>

        <div ref={scroller} className="flex-1 space-y-5 overflow-y-auto px-5 py-5">
          {msgs.length === 0 && (
            <div className="mx-auto max-w-2xl pt-6 text-center">
              <div className="mx-auto mb-4 grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-indigo-600 to-violet-600 text-white shadow-lg shadow-indigo-200"><Bot size={26} /></div>
              <h3 className="text-lg font-bold text-slate-900">What would you like to know about the Dallas market?</h3>
              <p className="mt-1 text-sm text-slate-500">
                Watch the agent graph on the right: the Orchestrator plans, the Data Scout scans, the Quality Auditor may send it back,
                the Trend Specialist estimates, and the Synthesizer may loop for refinement before answering.
              </p>
              <div className="mt-5 flex flex-wrap justify-center gap-2">
                {SUGGESTIONS.map((s) => (
                  <button key={s} onClick={() => ask(s)} className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-indigo-300 hover:text-indigo-700">{s}</button>
                ))}
              </div>
            </div>
          )}
          {msgs.map((m) => m.role === "user" ? (
            <div key={m.id} className="flex justify-end gap-2">
              <div className="max-w-[80%] rounded-2xl rounded-br-md bg-indigo-600 px-4 py-2.5 text-sm text-white shadow-sm">{m.text}</div>
              <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-slate-200 text-slate-600"><User size={15} /></div>
            </div>
          ) : (
            <AssistantMsg key={m.id} m={m} selected={sel?.id === m.id} onSelect={() => setSelected(m.id)} onOpen={onOpen} />
          ))}
        </div>

        <footer className="border-t border-slate-100 p-3">
          <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); ask(input); }}>
            <textarea
              className="input min-h-[44px] flex-1 resize-none"
              rows={1}
              placeholder="e.g. Which Dallas ZIPs under $500k rose the most in 2025?"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(input); } }}
            />
            <div className="flex flex-col items-end gap-1">
              <div className="flex items-center gap-1 text-[10px] text-slate-400">
                seed
                {[42, 101, 2026].map((s) => (
                  <button type="button" key={s} onClick={() => setSeed(s)} className={`rounded px-1.5 py-0.5 font-mono ${seed === s ? "bg-indigo-100 text-indigo-700" : "hover:bg-slate-100"}`}>{s}</button>
                ))}
              </div>
              <button className="btn-primary h-[44px]" disabled={busy || !input.trim()}>{busy ? <Spinner /> : <Send size={15} />} Ask</button>
            </div>
          </form>
        </footer>
      </section>

      <LivePanel m={sel ?? null} />
    </div>
  );
}

function AssistantMsg({ m, selected, onSelect, onOpen }: { m: Msg; selected: boolean; onSelect: () => void; onOpen: (c: Criteria) => void }) {
  const thinking = m.status === "thinking";
  const last = m.steps[m.steps.length - 1];
  const runs = Object.values(m.runs);
  return (
    <div className="flex gap-2">
      <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-gradient-to-br from-indigo-600 to-violet-600 text-white"><Bot size={15} /></div>
      <div onClick={onSelect}
        className={`min-w-0 max-w-[92%] flex-1 cursor-pointer rounded-2xl rounded-tl-md border bg-white px-4 py-3 shadow-sm transition ${selected ? "border-indigo-300 ring-2 ring-indigo-100" : "border-slate-200 hover:border-slate-300"}`}>
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          {m.plan && <Badge tone="indigo">{INTENT_LABEL[m.plan.intent] ?? m.plan.intent}</Badge>}
          {m.plan?.labels?.slice(0, 4).map((l, i) => <Badge key={i}>{l}</Badge>)}
          {(m.plan?.labels?.length ?? 0) > 4 && <Badge>+{m.plan!.labels.length - 4} more</Badge>}
          <span className="ml-auto text-[11px] text-slate-400">{m.steps.length} agent steps{m.elapsed != null && ` · ${m.elapsed} ms real time`}</span>
        </div>

        {thinking && !m.answer && (
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <Spinner />
            {last ? <span><b style={{ color: AGENT_COLORS[last.agent] }}>{AGENT_NAME[last.agent] ?? last.agent}</b> {last.action.replaceAll("_", " ")}…</span> : "Planning…"}
          </div>
        )}

        {m.answer && <AnswerText text={m.answer.text} />}
        {m.errors.length > 0 && <div className="mt-2 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{m.errors.join(" · ")}</div>}

        {m.answer && <Visual intent={m.answer.intent} facts={m.answer.facts} runs={runs} />}

        {m.answer && runs.length > 0 && runs.length <= 6 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {runs.map((s, i) => (
              <div key={i} className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs">
                <span className="h-2 w-2 rounded-full" style={{ background: PALETTE[i % PALETTE.length] }} />
                <span className="font-medium text-slate-700">{s.label}</span>
                <span className={s.change_pct == null ? "" : s.change_pct >= 0 ? "text-emerald-600" : "text-rose-600"}>{pct(s.change_pct)}</span>
                <span className={s.confidence < 0.7 ? "text-amber-600" : "text-slate-500"}>conf {s.confidence.toFixed(2)}</span>
                {s.feedback_cycles > 0 && <Badge tone="amber">feedback ×{s.feedback_cycles}</Badge>}
                {s.refinements_attempted.length > 0 && <Badge tone="sky">refine ×{s.refinements_attempted.length}</Badge>}
                <button title="Open in Market Trends" className="text-slate-400 hover:text-indigo-600" onClick={(e) => { e.stopPropagation(); onOpen(s.criteria); }}><ExternalLink size={12} /></button>
              </div>
            ))}
          </div>
        )}
        {m.answer && (
          <div className="mt-2 text-[10px] text-slate-400">
            planned by {m.plan?.planner} · answer written by {m.answer.writer}
            {m.plan?.notes?.length && ["trend", "compare", "rank"].includes(m.plan.intent) ? ` · ${m.plan.notes.join("; ")}` : ""}
          </div>
        )}
      </div>
    </div>
  );
}

function AnswerText({ text }: { text: string }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    setN(0);
    const step = Math.max(2, Math.ceil(text.length / 60));
    const t = setInterval(() => setN((x) => { if (x + step >= text.length) { clearInterval(t); return text.length; } return x + step; }), 16);
    return () => clearInterval(t);
  }, [text]);
  const shown = text.slice(0, n);
  return (
    <div className={`space-y-2 text-sm leading-relaxed text-slate-700 ${n < text.length ? "caret" : ""}`}>
      {shown.split(/\n\n+/).map((p, i) => (
        <p key={i} className="whitespace-pre-line">{p}</p>
      ))}
    </div>
  );
}

function Visual({ intent, facts, runs }: { intent: string; facts: any; runs: ChatRunSummary[] }) {
  if ((intent === "trend" || intent === "compare") && runs.length) {
    const sameWindow = runs.every((r) => r.window[1] === runs[0].window[1]);
    const data = runs[0].series.map((_, i) => {
      const row: any = { x: sameWindow ? monthLabel(runs[0].series[i].month) : `M${i + 1}` };
      runs.forEach((r, k) => (row[`r${k}`] = r.series[i]?.median_price ?? null));
      return row;
    });
    return (
      <div className="mt-3 h-52 rounded-lg border border-slate-100 bg-slate-50/50 p-2">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 6, right: 8, left: 4, bottom: 0 }}>
            <CartesianGrid stroke="#eef2f7" vertical={false} />
            <XAxis dataKey="x" tickLine={false} axisLine={false} minTickGap={16} />
            <YAxis width={56} tickLine={false} axisLine={false} domain={["auto", "auto"]} tickFormatter={(v) => money(v, "USD", true)} />
            <Tooltip formatter={(v: any) => money(v)} />
            {runs.length > 1 && <Legend iconType="circle" wrapperStyle={{ fontSize: 11 }} />}
            {runs.map((r, k) => (
              <Line isAnimationActive={false} key={k} dataKey={`r${k}`} name={sameWindow ? r.label : `${r.label} (${r.window[0]}…${r.window[1]})`}
                stroke={PALETTE[k % PALETTE.length]} strokeWidth={2.4} dot={{ r: 2.5 }} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    );
  }
  if (intent === "rank" && facts?.ranking?.items?.length) {
    const rk = facts.ranking;
    const key = rk.metric === "change" ? "change_pct" : rk.metric === "price" ? "end_price" : "end_active";
    const max = Math.max(...rk.items.map((x: any) => Math.abs(x[key] ?? 0)), 1e-9);
    return (
      <div className="mt-3 space-y-1.5 rounded-lg border border-slate-100 bg-slate-50/50 p-3">
        {rk.items.map((x: any, i: number) => {
          const v = x[key] ?? 0;
          const color = rk.metric === "change" ? (v >= 0 ? "#10b981" : "#f43f5e") : "#6366f1";
          return (
            <div key={i} className="grid grid-cols-[150px_1fr_80px] items-center gap-2 text-xs">
              <span className="truncate font-medium text-slate-700">{i + 1}. {x.name}</span>
              <div className="h-3 rounded bg-slate-100"><div className="h-3 rounded" style={{ width: `${(Math.abs(v) / max) * 100}%`, background: color, opacity: x.confidence != null && x.confidence < 0.7 ? 0.4 : 1 }} /></div>
              <span className="text-right font-mono">{rk.metric === "change" ? pct(v) : rk.metric === "price" ? money(v, "USD", true) : num(v)}</span>
            </div>
          );
        })}
      </div>
    );
  }
  if (intent === "listings" && facts?.listings?.n) {
    const L = facts.listings;
    return (
      <div className="mt-3 grid gap-3 rounded-lg border border-slate-100 bg-slate-50/50 p-3 sm:grid-cols-[200px_1fr]">
        <div className="grid grid-cols-2 gap-2 text-xs">
          {[["Listings", num(L.n)], ["Median price", money(L.median_price, "USD", true)], ["Median sqft", num(L.median_sqft)], ["$/sqft", money(L.median_ppsf)]].map(([k, v]) => (
            <div key={k} className="rounded-lg bg-white p-2"><div className="label">{k}</div><div className="text-base font-bold">{v}</div></div>
          ))}
        </div>
        <div className="h-36">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={L.by_bedrooms}>
              <XAxis dataKey="beds" tickLine={false} axisLine={false} tickFormatter={(b) => `${b} bd`} />
              <YAxis hide />
              <Tooltip formatter={(v: any, n: any) => (n === "median_price" ? money(v) : v)} />
              <Bar isAnimationActive={false} dataKey="median_price" name="median_price" fill="#818cf8" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    );
  }
  if (intent === "macro" && facts?.macro?.indicators?.length) {
    return (
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {facts.macro.indicators.map((ind: any) => (
          <div key={ind.key} className="rounded-lg border border-slate-100 bg-slate-50/50 p-2">
            <div className="flex justify-between text-[11px]"><span className="font-medium text-slate-600">{ind.name}</span>
              <span className="font-mono">{ind.unit === "%" ? `${ind.end.toFixed(2)}%` : ind.unit === "$" ? money(ind.end, "USD", true) : num(ind.end)}</span></div>
            <div className="h-20">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={ind.series}>
                  <YAxis hide domain={["auto", "auto"]} />
                  <XAxis dataKey="month" hide />
                  <Tooltip labelFormatter={(m: any) => monthLabel(String(m))} />
                  <Line isAnimationActive={false} dataKey="value" stroke="#0ea5e9" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        ))}
      </div>
    );
  }
  if (intent === "testing" && facts?.case && !facts.case.error) return <CaseVisual c={facts.case} />;
  if (intent === "testing" && facts?.testing?.rows) {
    return (
      <div className="mt-3 overflow-hidden rounded-lg border border-slate-100">
        <table className="w-full text-xs">
          <thead className="bg-slate-50 text-left text-[10px] uppercase tracking-wider text-slate-500"><tr><th className="px-2 py-1.5">MR</th><th>Relation</th><th className="text-right">Natural</th><th className="text-right">95% CI</th><th className="px-2 text-right">Pinned</th></tr></thead>
          <tbody>
            {facts.testing.rows.map((r: any) => (
              <tr key={r.mr} className={`border-t border-slate-100 ${facts.testing.asked.includes(r.mr) ? "bg-indigo-50/60" : ""}`}>
                <td className="px-2 py-1 font-semibold">{r.mr}</td><td>{r.name}</td>
                <td className="text-right font-mono">{r.violations}/{r.runs}</td>
                <td className="text-right font-mono text-slate-500">{(r.ci95[0] * 100).toFixed(1)}–{(r.ci95[1] * 100).toFixed(1)}%</td>
                <td className="px-2 text-right font-mono">{r.pinned_violations}/{r.runs}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return null;
}

function CaseVisual({ c }: { c: any }) {
  const countMR = ["MR2", "MR5", "MR6"].includes(c.mr.id);
  const k = c.transform_info?.k ?? 1;
  const src = Object.fromEntries(c.series.source.map((m: any) => [m.month, m]));
  const fol = Object.fromEntries(c.series.follow.map((m: any) => [m.month, m]));
  const months = Array.from(new Set([...Object.keys(src), ...Object.keys(fol)])).sort();
  const data = months.map((m) => ({
    x: monthLabel(m),
    source: countMR ? src[m]?.active_count : src[m]?.median_price != null ? src[m].median_price * k : null,
    follow: countMR ? fol[m]?.active_count : fol[m]?.median_price ?? null,
  }));
  const fmt = (v: any) => (countMR ? num(v) : money(v, c.currency_unit, true));
  const tone = !c.applicable ? "bg-slate-100 text-slate-600" : c.violated ? "bg-rose-50 text-rose-700 ring-1 ring-rose-200" : "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200";
  return (
    <div className="mt-3 space-y-2">
      <div className={`flex flex-wrap items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold ${tone}`}>
        {!c.applicable ? "Outside subdomain" : c.violated ? `${c.mr.id} violated` : `${c.mr.id} holds`}
        <span className="font-normal opacity-80">· {c.base} · seed {c.seed} · {c.mode}</span>
        {c.matches_recorded && <Badge tone="slate" className="ml-auto">reproduces recorded verdict</Badge>}
        {c.path_diverged && <Badge tone="amber">control path diverged</Badge>}
      </div>
      <div className="h-48 rounded-lg border border-slate-100 bg-slate-50/50 p-2">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 6, right: 8, left: 4, bottom: 0 }}>
            <CartesianGrid stroke="#eef2f7" vertical={false} />
            <XAxis dataKey="x" tickLine={false} axisLine={false} minTickGap={16} />
            <YAxis width={56} tickLine={false} axisLine={false} domain={["auto", "auto"]} tickFormatter={fmt} />
            <Tooltip formatter={fmt} />
            <Legend iconType="circle" wrapperStyle={{ fontSize: 11 }} />
            <Line isAnimationActive={false} dataKey="source" name={countMR ? "Source active count" : k !== 1 ? `Source median × ${k}` : "Source median"} stroke="#94a3b8" strokeWidth={2.4} dot={{ r: 2.5 }} />
            <Line isAnimationActive={false} dataKey="follow" name={countMR ? "Follow-up active count" : "Follow-up median"} stroke="#4f46e5" strokeWidth={2} strokeDasharray="5 3" dot={{ r: 2.5 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function LivePanel({ m }: { m: Msg | null }) {
  const steps = m?.steps ?? [];
  const feedback = steps.filter((s) => s.agent === "DataScout" && s.action === "received_feedback").length;
  const refinement = steps.filter((s) => s.agent === "Synthesizer" && s.action === "requested_refinement").length;
  const current = m?.status === "thinking" ? steps[steps.length - 1]?.agent ?? "Orchestrator" : null;
  const multi = Object.keys(m?.runLabels ?? {}).length > 1;
  const log = useRef<HTMLDivElement>(null);
  useEffect(() => { log.current?.scrollTo({ top: log.current.scrollHeight }); }, [steps.length]);
  const fired = useMemo(() => ({ feedback, refinement }), [feedback, refinement]);

  return (
    <aside className="space-y-4 xl:sticky xl:top-[76px] xl:h-[calc(100vh-112px)] xl:overflow-hidden">
      <section className="card">
        <header className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
          <div className="text-sm font-semibold text-slate-900">Live agent graph</div>
          <div className="flex items-center gap-1.5">
            {m?.status === "thinking" && <Badge tone="indigo"><span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-indigo-500" />running</Badge>}
            {fired.feedback > 0 && <Badge tone="amber">feedback ×{fired.feedback}</Badge>}
            {fired.refinement > 0 && <Badge tone="sky">refinement ×{fired.refinement}</Badge>}
          </div>
        </header>
        <div className="px-2 pb-1 pt-2">
          <FlowGraph events={steps} feedback={feedback} refinement={refinement} current={current} />
        </div>
      </section>
      <section className="card flex min-h-0 flex-col xl:h-[calc(100%-20px-var(--graph-h,360px))]">
        <header className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
          <div className="text-sm font-semibold text-slate-900">Agent steps</div>
          <span className="text-[11px] text-slate-400">{steps.length} events{m?.elapsed != null ? ` · ${m.elapsed} ms real time (replayed slower to follow)` : ""}</span>
        </header>
        <div ref={log} className="max-h-[42vh] flex-1 overflow-y-auto px-3 py-2 xl:max-h-none">
          {!steps.length && <div className="py-8 text-center text-xs text-slate-400">Ask a question to watch the agents work.</div>}
          {steps.map((s, i) => (
            <div key={i} className="flex gap-2 border-b border-dashed border-slate-100 py-1.5 text-xs last:border-0">
              <span className="mt-1 h-2 w-2 shrink-0 rounded-full" style={{ background: AGENT_COLORS[s.agent] ?? "#94a3b8" }} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <b style={{ color: AGENT_COLORS[s.agent] }}>{AGENT_NAME[s.agent] ?? s.agent}</b>
                  <span className="text-slate-700">{s.action.replaceAll("_", " ")}</span>
                  {s.loop && <Badge tone={s.loop === "feedback" ? "amber" : "sky"}>{s.loop} #{s.iteration}</Badge>}
                  {multi && s.run != null && <span className="rounded bg-slate-100 px-1.5 text-[10px] text-slate-500">{m?.runLabels[s.run]}</span>}
                </div>
                <div className="truncate font-mono text-[10.5px] text-slate-500" title={JSON.stringify(s.detail)}>{brief(s.detail)}</div>
              </div>
            </div>
          ))}
        </div>
      </section>
    </aside>
  );
}
