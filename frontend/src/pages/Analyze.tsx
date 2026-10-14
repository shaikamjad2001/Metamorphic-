import { useMemo } from "react";
import {
  Area, Bar, CartesianGrid, ComposedChart, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { AlertTriangle, ArrowRight, Building2, Gauge, Home, Repeat, Ruler, TrendingUp } from "lucide-react";
import type { Analysis, Criteria, Meta } from "../api";
import CriteriaPanel from "../components/CriteriaPanel";
import ZipMap from "../components/ZipMap";
import { Badge, Card, Empty, KV, Spinner, Stat } from "../components/ui";
import { money, monthLabel, num, pct } from "../lib/format";

export default function AnalyzePage(props: {
  meta: Meta; criteria: Criteria; setCriteria: (c: Criteria) => void; seed: number; setSeed: (s: number) => void;
  analysis: Analysis | null; loading: boolean; error: string | null; onRun: () => void;
  onRunWith: (c: Criteria) => void; openWorkflow: () => void;
}) {
  const { analysis, loading, error } = props;
  return (
    <div className="grid gap-6 lg:grid-cols-[340px_minmax(0,1fr)]">
      <aside className="lg:sticky lg:top-20 lg:self-start">
        <CriteriaPanel {...props} />
      </aside>
      <div className="relative min-w-0 space-y-6">
        {error && (
          <div className="card card-pad flex items-center gap-2 border-rose-200 bg-rose-50 text-sm text-rose-700">
            <AlertTriangle size={16} /> {error}
          </div>
        )}
        {loading && (
          <div className="absolute inset-0 z-10 flex items-start justify-center rounded-2xl bg-slate-50/60 pt-40 backdrop-blur-[1px]">
            <div className="card flex items-center gap-3 px-5 py-3 text-sm text-slate-600"><Spinner /> Agents are working…</div>
          </div>
        )}
        {analysis ? <Results a={analysis} openWorkflow={props.openWorkflow} /> : !loading && <Empty>Run the agents to see the trend.</Empty>}
      </div>
    </div>
  );
}

function Results({ a, openWorkflow }: { a: Analysis; openWorkflow: () => void }) {
  const { result: r, benchmark } = a;
  const t = r.trend;
  const unit = t.currency_unit;
  const s = t.monthly_series;
  const first = s[0], last = s[s.length - 1];
  const d = r.diagnostics;
  const data = useMemo(() => s.map((m) => ({ ...m, label: monthLabel(m.month), iqr: [m.price_q1, m.price_q3] })), [s]);
  const bench = useMemo(() => benchmark.map((b) => ({ ...b, label: monthLabel(b.month) })), [benchmark]);
  const confTone = t.confidence >= 0.85 ? "green" : t.confidence >= 0.6 ? "amber" : "red";
  const direction = (t.trend_change_pct ?? 0) > 0.05 ? "up" : (t.trend_change_pct ?? 0) < -0.05 ? "down" : "flat";
  const scopeLabel = r.criteria.zipcodes?.length ? `${r.criteria.zipcodes.length} selected ZIPs`
    : r.criteria.cities?.length ? r.criteria.cities.join(", ") : r.criteria.tiers?.length ? `${r.criteria.tiers.join(", ")} tier`
    : "Dallas metro";

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="label">12-month trend · {scopeLabel}</div>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900">
            {monthLabel(t.window_start)} → {monthLabel(t.window_end)}
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="violet">{t.method === "hedonic" ? "Hedonic (size-standardised)" : "Stratified median"}</Badge>
          <Badge tone={t.quality_audit_passed ? "green" : "red"}>{t.quality_audit_passed ? "Quality audit passed" : "Audit failed · degraded"}</Badge>
          <Badge tone={confTone}>Confidence {t.confidence.toFixed(2)}</Badge>
          {d.feedback_cycles > 0 && <Badge tone="amber"><Repeat size={11} /> {d.feedback_cycles} feedback cycle{d.feedback_cycles > 1 ? "s" : ""}</Badge>}
          {d.refinement_cycles > 0 && <Badge tone="sky"><Repeat size={11} /> {d.refinement_cycles} refinement{d.refinement_cycles > 1 ? "s" : ""}</Badge>}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 xl:grid-cols-5">
        <Stat label="Median list price" icon={<Home size={15} />} value={money(last.median_price, unit, true)}
          sub={`${monthLabel(last.month)} · from ${money(first.median_price, unit, true)}`} />
        <Stat label="12-month change" icon={<TrendingUp size={15} />} value={pct(t.trend_change_pct, 2)} tone={direction}
          sub={`Annualised (CAGR) ${pct(t.annual_cagr_estimate, 2)}`} />
        <Stat label="Active listings" icon={<Building2 size={15} />} value={num(last.active_count)}
          sub={`${pct(first.active_count ? (last.active_count / first.active_count - 1) * 100 : null)} vs ${monthLabel(first.month)} · ${last.n_zips} ZIPs`} />
        <Stat label="Median $/sqft" icon={<Ruler size={15} />} value={unit === "USD" ? `$${num(last.median_price_per_sqft)}` : num(last.median_price_per_sqft, 3)}
          sub={`from ${unit === "USD" ? "$" : ""}${num(first.median_price_per_sqft)} · DOM ${num(last.median_dom)}`} />
        <Stat label="Divergence vs Zillow" icon={<Gauge size={15} />} value={t.macro_divergence_score == null ? "—" : `${t.macro_divergence_score.toFixed(2)}%`}
          sub="MAPD of rebased indices (ZHVI)" />
      </div>

      <Card title="Median list price and active listings" subtitle="Active-listing-weighted median across ZIP-month records · shaded band = weighted IQR">
        <ResponsiveContainer width="100%" height={320}>
          <ComposedChart data={data} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
            <defs>
              <linearGradient id="iqr" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#6366f1" stopOpacity={0.22} />
                <stop offset="100%" stopColor="#6366f1" stopOpacity={0.06} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#f1f5f9" vertical={false} />
            <XAxis dataKey="label" tickLine={false} axisLine={false} />
            <YAxis yAxisId="p" tickFormatter={(v) => money(v, unit, true)} width={64} tickLine={false} axisLine={false} domain={["auto", "auto"]} />
            <YAxis yAxisId="c" orientation="right" tickFormatter={(v) => num(v)} width={56} tickLine={false} axisLine={false} />
            <Tooltip formatter={(v: any, n: any) => (n === "Active listings" ? num(v) : Array.isArray(v) ? `${money(v[0], unit)} – ${money(v[1], unit)}` : money(v, unit))} />
            <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
            <Bar isAnimationActive={false} yAxisId="c" dataKey="active_count" name="Active listings" fill="#e2e8f0" radius={[4, 4, 0, 0]} />
            <Area isAnimationActive={false} yAxisId="p" dataKey="iqr" name="IQR" stroke="none" fill="url(#iqr)" />
            <Line isAnimationActive={false} yAxisId="p" dataKey="median_price" name="Median list price" stroke="#4f46e5" strokeWidth={2.5} dot={{ r: 3 }} />
          </ComposedChart>
        </ResponsiveContainer>
      </Card>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card title="Cross-check against published trends" subtitle="All series rebased to 100 at the first window month">
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={bench} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="#f1f5f9" vertical={false} />
              <XAxis dataKey="label" tickLine={false} axisLine={false} />
              <YAxis domain={["auto", "auto"]} width={44} tickLine={false} axisLine={false} />
              <Tooltip formatter={(v: any) => (v == null ? "—" : Number(v).toFixed(2))} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
              <ReferenceLine y={100} stroke="#cbd5e1" />
              <Line isAnimationActive={false} dataKey="trend_index" name="This analysis" stroke="#4f46e5" strokeWidth={2.5} dot={false} />
              <Line isAnimationActive={false} dataKey="zhvi_index" name="Zillow ZHVI (metro)" stroke="#0ea5e9" strokeWidth={2} dot={false} strokeDasharray="5 3" />
              <Line isAnimationActive={false} dataKey="fred_index" name="Realtor.com MSA median (FRED)" stroke="#f59e0b" strokeWidth={2} dot={false} strokeDasharray="2 3" />
            </LineChart>
          </ResponsiveContainer>
        </Card>
        <Card title="Supply and pricing pressure" subtitle="New listings (bars) and median $/sqft (line)">
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="#f1f5f9" vertical={false} />
              <XAxis dataKey="label" tickLine={false} axisLine={false} />
              <YAxis yAxisId="n" width={44} tickLine={false} axisLine={false} />
              <YAxis yAxisId="p" orientation="right" width={44} domain={["auto", "auto"]} tickLine={false} axisLine={false} />
              <Tooltip />
              <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
              <Bar isAnimationActive={false} yAxisId="n" dataKey="new_listings" name="New listings" fill="#c7d2fe" radius={[4, 4, 0, 0]} />
              <Line isAnimationActive={false} yAxisId="p" dataKey="median_price_per_sqft" name="Median $/sqft" stroke="#10b981" strokeWidth={2.5} dot={{ r: 2.5 }} />
            </ComposedChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Card title="Where prices moved" subtitle="ZIP-level change between the first and last window month" pad={false}>
          <div className="p-3"><ZipMap zips={a.zips} unit={unit} /></div>
        </Card>
        <Card title="ZIP ranking" subtitle={`${t.zip_rankings.length} ZIPs present in both end months`} pad={false}>
          <div className="max-h-[436px] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-slate-50 text-left text-[11px] uppercase tracking-wider text-slate-500">
                <tr><th className="px-4 py-2">#</th><th>ZIP</th><th>City</th><th className="text-right">End median</th><th className="px-4 text-right">Change</th></tr>
              </thead>
              <tbody>
                {t.zip_rankings.map((z) => (
                  <tr key={z.zipcode} className="border-t border-slate-100 hover:bg-slate-50">
                    <td className="px-4 py-1.5 text-slate-400">{z.rank}</td>
                    <td className="font-mono">{z.zipcode}</td>
                    <td className="text-slate-600">{z.city}</td>
                    <td className="text-right">{money(z.end_price, unit, true)}</td>
                    <td className={`px-4 text-right font-semibold ${z.change_pct >= 0 ? "text-emerald-600" : "text-rose-600"}`}>{pct(z.change_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Card title="Synthesizer report">
          <p className="text-[15px] leading-relaxed text-slate-700">{r.narrative}</p>
          {r.caveats.length > 0 && (
            <ul className="mt-4 space-y-2">
              {r.caveats.map((c, i) => (
                <li key={i} className="flex gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  <AlertTriangle size={15} className="mt-0.5 shrink-0" /> {c}
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="How the agents got here" right={
          <button onClick={openWorkflow} className="flex items-center gap-1 text-xs font-semibold text-indigo-600 hover:text-indigo-800">
            Full trace <ArrowRight size={13} />
          </button>
        }>
          <KV k="Feedback loop (Auditor → Scout)" v={`${d.feedback_cycles} cycle(s)`} />
          <KV k="Band relaxation" v={r.control.relaxation_level ? `±${Math.round(r.control.relaxation_factor * 100)}%` : "none"} />
          <KV k="ZIPs added by spatial relaxation" v={r.control.added_zips.length ? r.control.added_zips.join(", ") : "none"} />
          <KV k="Method chosen" v={`${r.control.method.replace("_", " ")} (sqft CV ${d.method_signals?.sqft_cv ?? "—"}, bed σ ${d.method_signals?.bed_sigma ?? "—"})`} />
          <KV k="Refinement loop (Synthesizer → Specialist)" v={(d.refinements_attempted ?? []).join(" → ") || "not needed"} />
          <KV k="Confidence trajectory" v={(d.confidence_history ?? []).map((c: number) => c.toFixed(2)).join(" → ")} />
          <KV k="Kaggle listings profiled" v={num(d.composition?.n_listings)} />
          <KV k="Runtime" v={`${d.runtime_ms} ms · seed ${r.seed}`} />
        </Card>
      </div>
    </>
  );
}
