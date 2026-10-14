import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CheckCircle2, FlaskConical, Play, Shuffle, XCircle } from "lucide-react";
import { api, type CaseResult, type Criteria, type MRRow, type MTResults, type RecordedCase } from "../api";
import FlowGraph from "../components/FlowGraph";
import { Badge, Card, Empty, KV, Segmented, Spinner } from "../components/ui";
import { money, monthLabel, num } from "../lib/format";

const FAMILY_COLOR: Record<string, string> = { Invariance: "#6366f1", Monotonic: "#f59e0b", Directional: "#10b981" };

const INTERPRETATION: Record<string, { verdict: string; tone: string; text: string }> = {
  MR4: {
    verdict: "Ill-conceived MR for the deployed estimator (+1 genuine fault, fixed)",
    tone: "amber",
    text: "60 of 61 violations survive the pinned ablation, so they are not loop reactions. 56 are neighbouring months moving inside the temporal-pooling radius: pooling deliberately shares records across months, so “other months unchanged” cannot hold once the refinement loop pooled. All 6 cases where the target month fell coincide with price-band crossings: +$15K lifts cheaper ZIP-months over the lower bound into the slice (or pushes one over the upper bound), so the set being summarised changes and the median can fall. One earlier case was a genuine fault: a MAD trim on a 4-ZIP month dropped the heaviest record (fixed with a minimum-ZIP guard). The refined MR4R (pooling radius excluded, crossing-free subdomain) has 0 violations.",
  },
  MR2: {
    verdict: "Genuine design fault: pseudo-replication in the confidence bootstrap (+1 crash, fixed)",
    tone: "red",
    text: "First run: 100% crash. The ZIP ranking assumed one row per ZIP-month (fixed). Now every violation has a diverged control path and 0% survive pinning. Duplicates narrow the bootstrap interval, so the Synthesizer believes it has more evidence, confidence rises (~+0.05), and it skips refinements the source applied. The medians themselves are duplicate-invariant; the controller is not. Confirmed by intervention: bootstrapping ZIP-month strata instead of rows takes MR2 to 0/96 without changing any untransformed run (scripts/confirm_mr2_pseudoreplication.py).",
  },
  MR5: {
    verdict: "Loop emergence: adaptive relaxation is non-monotone in the requested band",
    tone: "amber",
    text: "In all 18 violations the source run's band was too narrow, so the auditor relaxed it (e.g. Plano $445K–$630K → ±15% = $378K–$725K), which reaches further than the MR's ±$60K. The follow-up already passed the audit and was not relaxed, so it scanned fewer records. Identical across seeds; pinned: 0%. The MR assumes a fixed filter; the feedback loop makes the scanned set depend on sparsity. It also exposes a contract ambiguity: active_count reports the relaxed band, not the user's.",
  },
  MR6: {
    verdict: "Loop emergence: subset triggers relaxation / spatial expansion",
    tone: "amber",
    text: "Halving the ZIP set makes the follow-up sparse; the auditor relaxes its band or adds neighbouring ZIPs that the source never scanned, so some months exceed the source count. Pinned: 0%.",
  },
  MR7: {
    verdict: "Loop emergence: window-dependent confidence near the 0.85 threshold",
    tone: "amber",
    text: "Sliding the window changes the bootstrap sample, so confidence crosses the 0.85 target differently and the two windows take different refinement paths (pooling vs not). Violated cases sit closer to the threshold than average. Pinned: 0%.",
  },
};

export default function LabPage() {
  const [res, setRes] = useState<MTResults | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [mode, setMode] = useState<"natural" | "pinned">("natural");
  const [bases, setBases] = useState<Criteria[]>([]);
  const [caseMr, setCaseMr] = useState("MR5");
  const openCase = (id: string) => {
    setCaseMr(id);
    document.getElementById("case-runner")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  useEffect(() => {
    api.results().then(setRes).catch((e) => setErr(e.message));
    api.catalog().then((c) => setBases(c.base_inputs));
  }, []);

  if (err) return <Card><Empty>{err}</Empty></Card>;
  if (!res) return <Card><div className="flex items-center gap-2 text-sm text-slate-500"><Spinner /> Loading results…</div></Card>;
  const h = res.headline;
  const rows = h.results[mode] ?? [];
  const total = (h.results.natural.length + (h.results.pinned?.length ?? 0)) * h.base_inputs.n * h.seeds.length;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="label">Metamorphic testing · statistical protocol</div>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900">Violation rates with 95% Wilson intervals</h1>
          <p className="mt-1 text-sm text-slate-500">
            {h.base_inputs.n} distinct base inputs × seeds {h.seeds.join(", ")} per relation · {num(total)} source/follow-up executions in {h.elapsed_seconds}s ·
            reproduce with <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs">python run_headline_results.py</code>
          </p>
        </div>
        <Segmented value={mode} onChange={setMode} options={[
          { value: "natural", label: "Natural (headline)" }, { value: "pinned", label: "Pinned ablation" },
        ]} />
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        <Card title="Forest plot" subtitle={mode === "natural" ? "Follow-up run makes its own loop decisions" : "Follow-up replays the source's control plan (loops frozen)"}>
          <Forest rows={rows} />
        </Card>
        <Card title="How violation rates changed as faults were fixed" subtitle="Natural mode, each archived stage of the codebase">
          <History res={res} />
        </Card>
      </div>

      <Card title="Results table" subtitle="Click a relation to test it live below" pad={false}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-[11px] uppercase tracking-wider text-slate-500">
              <tr>
                <th className="px-4 py-2">MR</th><th>Relation</th><th className="text-right">Violations</th><th className="text-right">Rate</th>
                <th className="text-right">95% CI</th><th className="text-right">Bases violated</th><th className="text-right">Per-seed rates</th>
                <th className="text-right">Seed-sensitive bases</th><th className="px-4 text-right">Path diverged</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.mr} onClick={() => openCase(r.mr)} title="Test this relation live"
                  className="cursor-pointer border-t border-slate-100 transition hover:bg-indigo-50/50">
                  <td className="px-4 py-2 font-semibold" style={{ color: FAMILY_COLOR[r.family] }}>{r.mr}</td>
                  <td>{r.name}{r.refined && <Badge tone="violet" className="ml-2">refined</Badge>}</td>
                  <td className="text-right font-mono">{r.violations}/{r.n_executions}{r.n_not_applicable ? <span className="text-slate-400"> (+{r.n_not_applicable} n/a)</span> : null}</td>
                  <td className="text-right font-semibold">{(r.violation_rate * 100).toFixed(1)}%</td>
                  <td className="text-right font-mono text-slate-500">[{(r.ci95[0] * 100).toFixed(1)}, {(r.ci95[1] * 100).toFixed(1)}]</td>
                  <td className="text-right">{r.bases_violated_any_seed}/{r.n_base_inputs}</td>
                  <td className="text-right font-mono text-xs text-slate-500">{Object.values(r.per_seed_rate).map((x) => (x * 100).toFixed(0) + "%").join(" · ")}</td>
                  <td className="text-right">{r.seed_sensitive_bases}</td>
                  <td className="px-4 text-right">{r.violations_with_path_divergence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div id="case-runner" className="scroll-mt-20">
        <CaseRunner bases={bases} catalogIds={h.catalog.map((c) => c.id)} mr={caseMr} setMr={setCaseMr} />
      </div>

      {res.diagnosis && (
        <div>
          <div className="mb-3 flex items-center gap-2">
            <h2 className="text-lg font-bold text-slate-900">Root-cause diagnosis</h2>
            <Badge tone="indigo">top three: {res.diagnosis.top3.join(", ")}</Badge>
          </div>
          <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
            {Object.entries(res.diagnosis.by_mr).filter(([, d]) => d.violations > 0).map(([id, d]) => (
              <DiagnosisCard key={id} id={id} d={d} top={res.diagnosis!.top3.includes(id)} />
            ))}
          </div>
        </div>
      )}

      <div>
        <h2 className="mb-3 text-lg font-bold text-slate-900">MR catalog</h2>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {h.catalog.map((m) => (
            <div key={m.id} className="card card-pad">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-sm font-bold" style={{ color: FAMILY_COLOR[m.family] }}>{m.id} · {m.name}</span>
                <Badge>{m.family}</Badge>
              </div>
              <dl className="space-y-1.5 text-[13px]">
                <div><dt className="label">Transformation</dt><dd className="text-slate-700">{m.transformation}</dd></div>
                <div><dt className="label">Relation</dt><dd className="text-slate-700">{m.relation}</dd></div>
                <div><dt className="label">Subdomain</dt><dd className="text-slate-600">{m.subdomain}</dd></div>
                <div><dt className="label">Tolerance</dt><dd className="font-mono text-xs text-slate-600">{m.tolerance}</dd></div>
                <div><dt className="label">Fault it targets</dt><dd className="text-slate-600">{m.target_fault}</dd></div>
              </dl>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Forest({ rows }: { rows: MRRow[] }) {
  return (
    <div className="space-y-2.5">
      <div className="grid grid-cols-[150px_1fr_70px] text-[10px] uppercase tracking-wider text-slate-400">
        <span /><div className="flex justify-between"><span>0%</span><span>25%</span><span>50%</span><span>75%</span><span>100%</span></div><span />
      </div>
      {rows.map((r) => {
        const c = FAMILY_COLOR[r.family];
        return (
          <div key={r.mr} className="grid grid-cols-[150px_1fr_70px] items-center gap-2">
            <div className="truncate text-xs"><b style={{ color: c }}>{r.mr}</b> <span className="text-slate-500">{r.name}</span></div>
            <div className="relative h-6 rounded bg-slate-50">
              {[25, 50, 75].map((g) => <div key={g} className="absolute top-0 h-full w-px bg-slate-200" style={{ left: `${g}%` }} />)}
              <div className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full" style={{ left: `${r.ci95[0] * 100}%`, width: `${Math.max(0.6, (r.ci95[1] - r.ci95[0]) * 100)}%`, background: c, opacity: 0.35 }} />
              <div className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white shadow" style={{ left: `${r.violation_rate * 100}%`, background: c }} />
            </div>
            <div className="text-right font-mono text-xs font-semibold">{(r.violation_rate * 100).toFixed(1)}%</div>
          </div>
        );
      })}
      <div className="flex gap-3 pt-2 text-[11px] text-slate-500">
        {Object.entries(FAMILY_COLOR).map(([f, c]) => <span key={f} className="flex items-center gap-1"><span className="h-2 w-2 rounded-full" style={{ background: c }} />{f}</span>)}
      </div>
    </div>
  );
}

function History({ res }: { res: MTResults }) {
  const stages = [...res.history.map((h) => ({ stage: h.stage, rows: h.natural })), { stage: "04_current", rows: res.headline.results.natural }];
  const ids = res.headline.results.natural.filter((r) => !r.refined).map((r) => r.mr);
  const data = ids.map((id) => {
    const o: any = { mr: id };
    stages.forEach((s) => { const r = s.rows.find((x) => x.mr === id); o[s.stage] = r ? +(r.violation_rate * 100).toFixed(1) : null; });
    return o;
  });
  const colors = ["#fda4af", "#fcd34d", "#a5b4fc", "#4f46e5"];
  const names: Record<string, string> = {
    "01_before_ranking_fix": "1 · first run", "02_before_trim_guard": "2 · ranking fixed",
    "03_before_skip_noop_trim": "3 · trim guard", "04_current": "4 · current",
  };
  return (
    <ResponsiveContainer width="100%" height={300}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
        <CartesianGrid stroke="#f1f5f9" vertical={false} />
        <XAxis dataKey="mr" tickLine={false} axisLine={false} />
        <YAxis unit="%" tickLine={false} axisLine={false} />
        <Tooltip formatter={(v: any) => `${v}%`} />
        <Legend iconType="circle" wrapperStyle={{ fontSize: 11 }} formatter={(v) => names[v] ?? v} />
        {stages.map((s, i) => <Bar isAnimationActive={false} key={s.stage} dataKey={s.stage} fill={colors[i % colors.length]} radius={[3, 3, 0, 0]} />)}
      </BarChart>
    </ResponsiveContainer>
  );
}

function DiagnosisCard({ id, d, top }: { id: string; d: any; top: boolean }) {
  const it = INTERPRETATION[id];
  const skip = new Set(["violations", "executions", "examples", "crashes", "bases"]);
  return (
    <div className={`card card-pad ${top ? "ring-2 ring-indigo-200" : ""}`}>
      <div className="mb-2 flex items-center justify-between">
        <span className="text-base font-bold text-slate-900">{id}</span>
        <span className="font-mono text-sm">{d.violations}/{d.executions}</span>
      </div>
      {it && <Badge tone={it.tone} className="mb-2">{it.verdict}</Badge>}
      {it && <p className="mb-3 text-[13px] leading-relaxed text-slate-600">{it.text}</p>}
      <div className="rounded-lg bg-slate-50 p-3">
        <div className="label mb-1">Evidence (computed)</div>
        {Object.entries(d).filter(([k, v]) => !skip.has(k) && v != null && !(typeof v === "object" && !Object.keys(v as object).length)).map(([k, v]) =>
          typeof v === "object" ? (
            <div key={k} className="border-b border-dashed border-slate-100 py-1.5 last:border-0">
              <div className="text-xs text-slate-500">{k.replaceAll("_", " ")}</div>
              {Object.entries(v as Record<string, any>).map(([a, b]) => (
                <div key={a} className="flex justify-between gap-3 pl-3 text-xs"><span className="text-slate-600">{a}</span><span className="font-mono font-medium">{String(b)}</span></div>
              ))}
            </div>
          ) : (
            <KV key={k} k={<span className="text-xs">{k.replaceAll("_", " ")}</span>} v={<span className="font-mono text-xs">{String(v)}</span>} />
          ))}
      </div>
    </div>
  );
}

function Row({ seed, n, cases, current, onPick, labels }: {
  seed: number; n: number; cases: RecordedCase[]; current: { b: number; s: number } | null;
  onPick: (b: number) => void; labels: string[];
}) {
  const by = new Map(cases.filter((c) => c.seed === seed).map((c) => [c.base_idx, c]));
  return (
    <>
      <div className="flex items-center font-mono text-[10px] text-slate-500">seed {seed}</div>
      {Array.from({ length: n }).map((_, b) => {
        const c = by.get(b);
        const color = !c ? "bg-slate-100" : c.applicable === false ? "bg-slate-300" : c.violated ? "bg-rose-500 hover:bg-rose-600" : "bg-emerald-400 hover:bg-emerald-500";
        const here = current?.b === b && current?.s === seed;
        return (
          <button key={b} onClick={() => onPick(b)}
            title={`${labels[b] ?? `base ${b + 1}`} · seed ${seed}: ${!c ? "not recorded" : c.applicable === false ? "outside subdomain" : c.violated ? "violated" : "holds"}${c?.path_diverged ? " · path diverged" : ""}`}
            className={`h-5 rounded-[3px] transition ${color} ${here ? "ring-2 ring-indigo-600 ring-offset-1" : ""}`} />
        );
      })}
    </>
  );
}

function CaseRunner({ bases, catalogIds, mr, setMr }: { bases: Criteria[]; catalogIds: string[]; mr: string; setMr: (m: string) => void }) {
  const [base, setBase] = useState(6);
  const [seed, setSeed] = useState(42);
  const [mode, setMode] = useState<"natural" | "pinned">("natural");
  const [out, setOut] = useState<CaseResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [recorded, setRecorded] = useState<RecordedCase[]>([]);
  useEffect(() => { api.cases(mr).then(setRecorded).catch(() => setRecorded([])); }, [mr]);

  const runWith = async (b: number, s: number, m: "natural" | "pinned" = mode) => {
    setBase(b); setSeed(s); setMode(m);
    setBusy(true); setErr(null);
    try { setOut(await api.runCase(mr, b, s, m)); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  const run = () => runWith(base, seed);
  const mine = recorded.filter((r) => r.mode === mode);
  const violating = mine.filter((r) => r.violated);
  const recordedHere = mine.find((r) => r.base_idx === out?.base_idx && r.seed === out?.seed);
  const runViolation = () => {
    if (!violating.length) return;
    const r = violating[Math.floor(Math.random() * violating.length)];
    runWith(r.base_idx, r.seed);
  };
  const seeds = [42, 101, 2026];
  const countMR = ["MR2", "MR5", "MR6"].includes(out?.mr.id ?? "");
  const k = out?.transform_info?.k ?? 1;
  const data = useMemo(() => {
    if (!out) return [];
    const f = Object.fromEntries(out.follow.series.map((m) => [m.month, m]));
    const months = Array.from(new Set([...out.source.series.map((m) => m.month), ...out.follow.series.map((m) => m.month)])).sort();
    const s = Object.fromEntries(out.source.series.map((m) => [m.month, m]));
    return months.map((m) => ({
      label: monthLabel(m),
      source: countMR ? s[m]?.active_count : s[m]?.median_price != null ? s[m].median_price! * k : null,
      follow: countMR ? f[m]?.active_count : f[m]?.median_price ?? null,
    }));
  }, [out, countMR, k]);

  return (
    <Card title={<span className="flex items-center gap-2"><FlaskConical size={15} /> Test a relation live: reproduce any violation</span>}
      subtitle="Source run → transformation → follow-up run → relation check, exactly as the harness does, on the real snapshot">
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <label className="text-xs"><div className="label mb-1">Relation</div>
          <select className="input w-32" value={mr} onChange={(e) => { setMr(e.target.value); setOut(null); }}>{catalogIds.map((i) => <option key={i}>{i}</option>)}</select></label>
        <label className="text-xs"><div className="label mb-1">Base input</div>
          <select className="input w-64" value={base} onChange={(e) => setBase(+e.target.value)}>{bases.map((b, i) => <option key={i} value={i}>{b.label}</option>)}</select></label>
        <div><div className="label mb-1">Seed</div><Segmented size="sm" value={seed} onChange={setSeed} options={seeds.map((s) => ({ value: s, label: s }))} /></div>
        <div><div className="label mb-1">Mode</div><Segmented size="sm" value={mode} onChange={setMode} options={[{ value: "natural", label: "natural" }, { value: "pinned", label: "pinned" }]} /></div>
        <button className="btn-primary" onClick={run} disabled={busy}>{busy ? <Spinner /> : <Play size={14} />} Run case</button>
        <button className="btn-ghost" onClick={runViolation} disabled={busy || !violating.length}
          title={violating.length ? "Pick a random recorded violation of this MR and re-run it live" : "No recorded violation in this mode"}>
          <Shuffle size={14} /> Run a violating case
        </button>
      </div>

      <div className="mb-5 rounded-xl border border-slate-200 bg-slate-50/60 p-3">
        <div className="mb-2 flex flex-wrap items-center gap-3 text-xs text-slate-600">
          <span className="font-semibold text-slate-800">Recorded harness results for {mr} ({mode})</span>
          <span><b className="text-rose-600">{violating.length}</b> violated of {mine.filter((r) => r.applicable !== false).length} counted runs</span>
          <span className="ml-auto flex items-center gap-3">
            <span className="flex items-center gap-1"><i className="inline-block h-3 w-3 rounded-sm bg-rose-500" /> violated</span>
            <span className="flex items-center gap-1"><i className="inline-block h-3 w-3 rounded-sm bg-emerald-400" /> holds</span>
            <span className="flex items-center gap-1"><i className="inline-block h-3 w-3 rounded-sm bg-slate-300" /> outside subdomain</span>
            <span className="text-slate-400">click a cell to re-run it</span>
          </span>
        </div>
        <div className="overflow-x-auto">
          <div className="grid min-w-[760px] gap-[3px]" style={{ gridTemplateColumns: `52px repeat(${bases.length || 32}, minmax(0, 1fr))` }}>
            <div />
            {(bases.length ? bases : Array.from({ length: 32 })).map((_, i) => (
              <div key={i} className="text-center font-mono text-[9px] text-slate-400">{i + 1}</div>
            ))}
            {seeds.map((s) => (
              <Row key={s} seed={s} n={bases.length || 32} cases={mine} current={out && out.mode === mode ? { b: out.base_idx, s: out.seed } : null}
                onPick={(b) => runWith(b, s)} labels={bases.map((b) => b.label ?? "")} />
            ))}
          </div>
        </div>
      </div>

      {busy && <div className="mb-3 flex items-center gap-2 text-sm text-slate-500"><Spinner /> Running source and follow-up through all agents…</div>}
      {err && <div className="text-sm text-rose-600">{err}</div>}
      {out && (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <div>
            <div className={`mb-3 flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold ${
              !out.applicable ? "bg-slate-100 text-slate-600" : out.violated ? "bg-rose-50 text-rose-700" : "bg-emerald-50 text-emerald-700"}`}>
              {!out.applicable ? "Outside the MR's subdomain (not counted)" : out.violated ? <><XCircle size={16} /> Relation violated</> : <><CheckCircle2 size={16} /> Relation holds</>}
              <span className="font-normal text-slate-500">· {bases[out.base_idx]?.label} · seed {out.seed} · {out.mode}</span>
              {out.path_diverged && <Badge tone="amber" className="ml-auto">control path diverged</Badge>}
            </div>
            {recordedHere && recordedHere.applicable !== false && (
              <div className="mb-3 text-xs text-slate-500">
                Recorded harness verdict for this case: <b>{recordedHere.violated ? "violated" : "holds"}</b>
                {recordedHere.violated === out.violated ? " — the live re-run reproduces it (fixed seeds, frozen snapshot)." : " — differs from the live run."}
              </div>
            )}
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={data} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
                <CartesianGrid stroke="#f1f5f9" vertical={false} />
                <XAxis dataKey="label" tickLine={false} axisLine={false} />
                <YAxis domain={["auto", "auto"]} width={70} tickLine={false} axisLine={false}
                  tickFormatter={(v) => (countMR ? num(v) : money(v, out.follow.currency_unit, true))} />
                <Tooltip formatter={(v: any) => (countMR ? num(v) : money(v, out.follow.currency_unit))} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
                <Line isAnimationActive={false} dataKey="source" name={countMR ? "Source active count" : k !== 1 ? `Source median × ${k}` : "Source median"} stroke="#94a3b8" strokeWidth={2.5} dot={{ r: 3 }} />
                <Line isAnimationActive={false} dataKey="follow" name={countMR ? "Follow-up active count" : "Follow-up median"} stroke="#4f46e5" strokeWidth={2} strokeDasharray="5 3" dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="space-y-3 text-sm">
            <div className="rounded-lg bg-slate-50 p-3">
              <div className="label mb-1">{out.mr.id} · {out.mr.name}</div>
              <p className="text-slate-600">{out.mr.relation}</p>
            </div>
            <div className="grid grid-cols-2 gap-3">
              {(["source", "follow"] as const).map((s) => (
                <div key={s} className="rounded-lg border border-slate-200 p-3">
                  <div className="label mb-1">{s === "source" ? "Source run" : "Follow-up run"}</div>
                  <KV k="relaxation" v={out[s].control.relaxation_level} />
                  <KV k="added ZIPs" v={out[s].control.added_zips.length} />
                  <KV k="method" v={out[s].method === "hedonic" ? "hedonic" : "median"} />
                  <KV k="refinements" v={out[s].control.refinements.length ? out[s].control.refinements.map((x) => x.replace("temporal_", "")).join(", ") : "—"} />
                  <KV k="confidence" v={out[s].confidence.toFixed(3)} />
                </div>
              ))}
            </div>
            {out.detail && <pre className="max-h-40 overflow-auto rounded-lg bg-slate-900 p-3 font-mono text-[11px] text-slate-100">{JSON.stringify(out.detail, null, 1)}</pre>}
          </div>
          <div className="lg:col-span-2">
            <div className="label mb-2">What each run's agents did ({out.source.events.length} vs {out.follow.events.length} agent steps)</div>
            <div className="grid gap-4 md:grid-cols-2">
              {(["source", "follow"] as const).map((s) => {
                const ev = out[s].events;
                return (
                  <div key={s} className="rounded-xl border border-slate-200 p-2">
                    <div className="px-2 pt-1 text-xs font-semibold text-slate-700">{s === "source" ? "Source run" : `Follow-up run (${out.mr.id}${out.mode === "pinned" ? ", pinned" : ""})`}</div>
                    <FlowGraph events={ev}
                      feedback={ev.filter((e) => e.agent === "DataScout" && e.action === "received_feedback").length}
                      refinement={ev.filter((e) => e.agent === "Synthesizer" && e.action === "requested_refinement").length} />
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}
