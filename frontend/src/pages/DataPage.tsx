import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CheckCircle2, FileSpreadsheet, ShieldCheck } from "lucide-react";
import { api, type Meta } from "../api";
import { Badge, Card, Segmented, Spinner, Toggle } from "../components/ui";
import { money, monthLabel, num } from "../lib/format";

const FILES: { file: string; title: string; role: string }[] = [
  { file: "dfw_zip_month.csv", title: "Realtor.com ZIP × month listing records", role: "What the agents scan: active listings, median list price, $/sqft, size, DOM per ZIP-month" },
  { file: "dfw_listings_kaggle.csv", title: "Kaggle USA Real Estate listings", role: "Per-listing composition (bedrooms, size) feeding the Trend Specialist's method switch" },
  { file: "macro_monthly.csv", title: "Zillow ZHVI · FRED · FHFA", role: "Published trends for cross-checking and the macro-divergence score" },
  { file: "zillow_zip_zhvi.csv", title: "Zillow ZHVI by ZIP", role: "ZIP-level published index (context)" },
  { file: "zip_geo.json", title: "US Census ZCTA gazetteer", role: "ZIP centroids for the map and the spatial-relaxation step" },
];

const summarize = (o: Record<string, any>): string =>
  Object.entries(o).map(([k, v]) =>
    `${k.replaceAll("_", " ")}: ${Array.isArray(v) ? (v.length > 6 ? `${v.length} items` : v.join(", ")) : typeof v === "object" && v ? JSON.stringify(v) : v}`,
  ).join(" · ");

export default function DataPage({ meta }: { meta: Meta }) {
  const [macro, setMacro] = useState<any[]>([]);
  useEffect(() => { api.macro().then(setMacro); }, []);
  const m = meta.manifest;
  const macroData = useMemo(() => macro.map((r) => ({ ...r, label: monthLabel(r.month) })), [macro]);

  return (
    <div className="space-y-6">
      <div>
        <div className="label">Frozen local snapshot · reproducible</div>
        <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900">Real public data, no synthetic or imputed values</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          Downloaded once on {meta.retrieved_at?.slice(0, 10) ?? "—"} with <code className="font-mono text-xs">scripts/fetch_raw_data.py</code>, filtered by{" "}
          <code className="font-mono text-xs">scripts/build_snapshot.py</code> to {m.n_zipcodes} Dallas-area ZIP codes within 40 miles of downtown, {m.months?.[0]} … {m.months?.[1]}.
          Every agent and every metamorphic run reads only this snapshot; the harness refuses to run if a SHA-256 does not match.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        {FILES.map((f) => (
          <div key={f.file} className="card card-pad">
            <div className="mb-2 flex items-center gap-2 text-indigo-600"><FileSpreadsheet size={16} /><span className="font-mono text-[11px]">{f.file}</span></div>
            <div className="text-sm font-semibold text-slate-900">{f.title}</div>
            <p className="mt-1 text-xs text-slate-500">{f.role}</p>
            <div className="mt-3 flex items-center gap-1 font-mono text-[10px] text-slate-400" title={m.snapshot_sha256?.[f.file]}>
              <ShieldCheck size={12} className="text-emerald-500" /> sha256 {m.snapshot_sha256?.[f.file]?.slice(0, 16)}…
            </div>
          </div>
        ))}
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card title="Published DFW price levels" subtitle="Zillow ZHVI (typical home value) vs Realtor.com median listing price (FRED)">
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={macroData} margin={{ left: 8, right: 8 }}>
              <CartesianGrid stroke="#f1f5f9" vertical={false} />
              <XAxis dataKey="label" tickLine={false} axisLine={false} minTickGap={24} />
              <YAxis tickFormatter={(v) => money(v, "USD", true)} width={60} domain={["auto", "auto"]} tickLine={false} axisLine={false} />
              <Tooltip formatter={(v: any) => money(v)} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
              <Line isAnimationActive={false} dataKey="zhvi_metro" name="Zillow ZHVI" stroke="#0ea5e9" strokeWidth={2.5} dot={false} />
              <Line isAnimationActive={false} dataKey="fred_median_listing_price" name="Realtor.com median list price" stroke="#f59e0b" strokeWidth={2.5} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </Card>
        <Card title="DFW inventory and mortgage rates" subtitle="Active listings (FRED ACTLISCOU19100) and 30-year fixed rate (MORTGAGE30US)">
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={macroData} margin={{ left: 8, right: 8 }}>
              <CartesianGrid stroke="#f1f5f9" vertical={false} />
              <XAxis dataKey="label" tickLine={false} axisLine={false} minTickGap={24} />
              <YAxis yAxisId="a" tickFormatter={(v) => num(v)} width={56} tickLine={false} axisLine={false} />
              <YAxis yAxisId="r" orientation="right" unit="%" width={44} domain={[5, 8]} tickLine={false} axisLine={false} />
              <Tooltip />
              <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
              <Bar isAnimationActive={false} yAxisId="a" dataKey="fred_active_listing_count" name="Active listings (MSA)" fill="#c7d2fe" radius={[3, 3, 0, 0]} />
              <Line isAnimationActive={false} yAxisId="r" dataKey="mortgage_rate_30y" name="30y mortgage rate" stroke="#ef4444" strokeWidth={2.5} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <ListingExplorer meta={meta} />

      <Card title="Source manifest" subtitle="From data/snapshot/MANIFEST.json">
        <div className="grid gap-4 md:grid-cols-2">
          {Object.entries(m.sources ?? {}).map(([k, v]: [string, any]) => (
            <div key={k} className="rounded-lg border border-slate-100 p-3 text-xs">
              <div className="mb-2 flex items-center gap-1 font-mono font-semibold text-slate-800"><CheckCircle2 size={13} className="text-emerald-500" />{k}</div>
              <dl className="space-y-1.5">
                {Object.entries(v).map(([field, val]: [string, any]) => (
                  <div key={field}>
                    <dt className="label">{field.replaceAll("_", " ")}</dt>
                    <dd className="text-slate-600">{typeof val === "object" ? summarize(val) : String(val)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function ListingExplorer({ meta }: { meta: Meta }) {
  const [zips, setZips] = useState<string[]>(["75201", "75204", "75219"]);
  const [status, setStatus] = useState<string>("");
  const [data, setData] = useState<{ summary: any; rows: any[] } | null>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    setLoading(true);
    api.listings(zips, status || undefined).then(setData).finally(() => setLoading(false));
  }, [zips, status]);
  const core = ["75201", "75202", "75204", "75205", "75206", "75209", "75214", "75219", "75225", "75230"];
  const beds = data ? Object.entries(data.summary.beds).map(([b, n]) => ({ beds: b === "6" ? "6+" : b, n })) : [];

  return (
    <Card title="Listing explorer · Kaggle USA Real Estate (real Realtor.com listings, 2021-22)"
      subtitle="Per-listing rows used for the composition signal. Pick ZIPs to profile."
      right={<Segmented size="sm" value={status} onChange={setStatus} options={[
        { value: "", label: "All" }, { value: "for_sale", label: "For sale" }, { value: "sold", label: "Sold" },
      ]} />}>
      <div className="mb-4 flex flex-wrap gap-1.5">
        {core.map((z) => {
          const g = meta.zips.find((x) => x.zipcode === z);
          return <Toggle key={z} active={zips.includes(z)} onClick={() => setZips(zips.includes(z) ? zips.filter((x) => x !== z) : [...zips, z])}>
            <span className="font-mono">{z}</span> <span className="opacity-70">{g?.neighborhood}</span>
          </Toggle>;
        })}
      </div>
      {loading && <div className="flex items-center gap-2 text-sm text-slate-500"><Spinner /> Loading…</div>}
      {data && (
        <div className="grid gap-5 lg:grid-cols-[260px_minmax(0,1fr)]">
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-lg bg-slate-50 p-3"><div className="label">Listings</div><div className="text-xl font-bold">{num(data.summary.n)}</div></div>
              <div className="rounded-lg bg-slate-50 p-3"><div className="label">Median price</div><div className="text-xl font-bold">{money(data.summary.median_price, "USD", true)}</div></div>
              <div className="rounded-lg bg-slate-50 p-3"><div className="label">Median sqft</div><div className="text-xl font-bold">{num(data.summary.median_sqft)}</div></div>
              <div className="rounded-lg bg-slate-50 p-3"><div className="label">Median $/sqft</div><div className="text-xl font-bold">${num(data.summary.median_ppsf)}</div></div>
            </div>
            <div className="flex flex-wrap gap-1">{Object.entries(data.summary.by_status).map(([k, v]) => <Badge key={k}>{k}: {String(v)}</Badge>)}</div>
            <ResponsiveContainer width="100%" height={150}>
              <BarChart data={beds}>
                <XAxis dataKey="beds" tickLine={false} axisLine={false} />
                <Tooltip />
                <Bar isAnimationActive={false} dataKey="n" name="Listings" fill="#818cf8" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
            <div className="text-center text-[11px] text-slate-400">Bedroom mix</div>
          </div>
          <div className="max-h-[380px] overflow-auto rounded-lg border border-slate-100">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-slate-50 text-left uppercase tracking-wider text-slate-500">
                <tr><th className="px-3 py-2">ZIP</th><th>Status</th><th className="text-right">Price</th><th className="text-right">Beds</th><th className="text-right">Baths</th><th className="text-right">Sqft</th><th className="text-right">$/sqft</th><th className="px-3">Prev. sold</th></tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.listing_id} className="border-t border-slate-100">
                    <td className="px-3 py-1 font-mono">{r.zipcode}</td>
                    <td><Badge tone={r.status === "sold" ? "slate" : "green"}>{r.status}</Badge></td>
                    <td className="text-right">{money(r.price)}</td>
                    <td className="text-right">{r.bedrooms ?? "—"}</td>
                    <td className="text-right">{r.bathrooms ?? "—"}</td>
                    <td className="text-right">{num(r.sqft)}</td>
                    <td className="text-right">{r.price_per_sqft ? `$${num(r.price_per_sqft)}` : "—"}</td>
                    <td className="px-3 text-slate-500">{r.prev_sold_date ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Card>
  );
}
