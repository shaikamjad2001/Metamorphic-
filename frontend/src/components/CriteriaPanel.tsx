import { useMemo, useState } from "react";
import { Play, Search, Sparkles, X } from "lucide-react";
import { api, type Criteria, type Meta } from "../api";
import { Segmented, Spinner, Toggle } from "./ui";
import { monthLabel } from "../lib/format";

type Area = "metro" | "cities" | "tiers" | "zips";

const CORE10 = ["75201", "75202", "75204", "75205", "75206", "75209", "75214", "75219", "75225", "75230"];
const PRICE_PRESETS: { label: string; min: number | null; max: number | null }[] = [
  { label: "Any", min: null, max: null },
  { label: "< $350K", min: null, max: 350000 },
  { label: "$350–600K", min: 350000, max: 600000 },
  { label: "$600K–1M", min: 600000, max: 1000000 },
  { label: "$1M+", min: 1000000, max: null },
];
const EXAMPLES = [
  "Luxury ZIPs in Dallas between 600k and 1.5m",
  "Plano under $550k ending 2025-11",
  "Frisco over 700k 2000-4000 sqft",
  "75201 75204 75219 in 2024",
];

const areaOf = (c: Criteria): Area =>
  c.zipcodes?.length ? "zips" : c.cities?.length ? "cities" : c.tiers?.length ? "tiers" : "metro";

export default function CriteriaPanel({ meta, criteria, setCriteria, seed, setSeed, loading, onRun, onRunWith }: {
  meta: Meta; criteria: Criteria; setCriteria: (c: Criteria) => void; seed: number; setSeed: (s: number) => void;
  loading: boolean; onRun: () => void; onRunWith: (c: Criteria) => void;
}) {
  const [query, setQuery] = useState("");
  const [parsing, setParsing] = useState(false);
  const [parseInfo, setParseInfo] = useState<{ parser: string; notes: string[] } | null>(null);
  const [zipSearch, setZipSearch] = useState("");
  const [area, setArea] = useState<Area>(areaOf(criteria));
  const set = (patch: Partial<Criteria>) => setCriteria({ ...criteria, ...patch });

  const windowEnds = useMemo(() => meta.months.slice(11).reverse(), [meta.months]);
  const zipMatches = useMemo(() => {
    const q = zipSearch.trim().toLowerCase();
    if (!q) return [];
    return meta.zips.filter((z) =>
      z.zipcode.includes(q) || (z.city ?? "").toLowerCase().includes(q) || (z.neighborhood ?? "").toLowerCase().includes(q),
    ).slice(0, 8);
  }, [zipSearch, meta.zips]);

  const switchArea = (a: Area) => {
    setArea(a);
    set({ zipcodes: null, cities: null, tiers: null });
  };
  const toggleIn = (key: "cities" | "tiers" | "zipcodes", v: string) => {
    const cur = new Set(criteria[key] ?? []);
    cur.has(v) ? cur.delete(v) : cur.add(v);
    set({ [key]: cur.size ? [...cur] : null });
  };

  const interpret = async () => {
    if (!query.trim()) return;
    setParsing(true);
    try {
      const r = await api.parse(query);
      const c: Criteria = { window_end: criteria.window_end, ...r.criteria };
      setArea(areaOf(c));
      setParseInfo({ parser: r.parser, notes: r.notes });
      onRunWith(c);
    } catch (e: any) {
      setParseInfo({ parser: "error", notes: [e.message] });
    } finally {
      setParsing(false);
    }
  };

  const numInput = (key: keyof Criteria, placeholder: string) => (
    <input
      className="input"
      type="number"
      placeholder={placeholder}
      value={(criteria[key] as number | null | undefined) ?? ""}
      onChange={(e) => set({ [key]: e.target.value === "" ? null : Number(e.target.value) })}
    />
  );

  return (
    <div className="card overflow-hidden">
      <div className="bg-gradient-to-br from-indigo-600 via-indigo-600 to-violet-600 p-4 text-white">
        <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-indigo-100">
          <Sparkles size={14} /> Ask in plain English
        </div>
        <div className="flex gap-2">
          <input
            className="w-full rounded-lg border-0 bg-white/15 px-3 py-2 text-sm text-white placeholder:text-indigo-200 outline-none ring-1 ring-white/20 focus:bg-white/20 focus:ring-white/50"
            placeholder="e.g. luxury Dallas ZIPs 600k–1.5m"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && interpret()}
          />
          <button onClick={interpret} disabled={parsing} className="rounded-lg bg-white px-3 text-sm font-semibold text-indigo-700 hover:bg-indigo-50">
            {parsing ? <Spinner /> : "Go"}
          </button>
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {EXAMPLES.map((x) => (
            <button key={x} onClick={() => setQuery(x)} className="rounded-full bg-white/10 px-2 py-0.5 text-[11px] text-indigo-100 hover:bg-white/20">
              {x}
            </button>
          ))}
        </div>
        {parseInfo && (
          <div className="mt-2 text-[11px] text-indigo-100">
            Parsed by <b>{parseInfo.parser}</b>{parseInfo.notes.length ? ` · ${parseInfo.notes.join("; ")}` : ""}
          </div>
        )}
      </div>

      <div className="space-y-5 p-4">
        <div>
          <div className="label mb-2">Area</div>
          <Segmented size="sm" value={area} onChange={switchArea} options={[
            { value: "metro", label: "Whole metro" }, { value: "cities", label: "Cities" },
            { value: "tiers", label: "Price tiers" }, { value: "zips", label: "ZIPs" },
          ]} />
          <div className="mt-3">
            {area === "metro" && <p className="text-xs text-slate-500">All {meta.zips.length} Dallas-area ZIP codes within 40 miles of downtown.</p>}
            {area === "cities" && (
              <div className="flex max-h-36 flex-wrap gap-1.5 overflow-y-auto">
                {meta.cities.map((c) => (
                  <Toggle key={c.city} active={!!criteria.cities?.includes(c.city)} onClick={() => toggleIn("cities", c.city)}>
                    {c.city} <span className="opacity-60">{c.n_zips}</span>
                  </Toggle>
                ))}
              </div>
            )}
            {area === "tiers" && (
              <div className="flex flex-wrap gap-1.5">
                {meta.tiers.map((t) => (
                  <Toggle key={t} active={!!criteria.tiers?.includes(t)} onClick={() => toggleIn("tiers", t)}>{t}</Toggle>
                ))}
              </div>
            )}
            {area === "zips" && (
              <div className="space-y-2">
                <div className="relative">
                  <Search size={14} className="absolute left-3 top-2.5 text-slate-400" />
                  <input className="input pl-8" placeholder="ZIP, city or neighborhood" value={zipSearch}
                    onChange={(e) => setZipSearch(e.target.value)} />
                  {zipMatches.length > 0 && (
                    <div className="absolute z-20 mt-1 w-full overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg">
                      {zipMatches.map((z) => (
                        <button key={z.zipcode} className="flex w-full items-center justify-between px-3 py-1.5 text-left text-sm hover:bg-slate-50"
                          onClick={() => { toggleIn("zipcodes", z.zipcode); setZipSearch(""); }}>
                          <span><b className="font-mono">{z.zipcode}</b> <span className="text-slate-500">{z.neighborhood ?? z.city}</span></span>
                          <span className="text-[11px] text-slate-400">{z.price_tier}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {(criteria.zipcodes ?? []).map((z) => (
                    <span key={z} className="chip bg-indigo-50 font-mono text-indigo-700">
                      {z}<button onClick={() => toggleIn("zipcodes", z)}><X size={12} /></button>
                    </span>
                  ))}
                  <button className="chip border border-dashed border-slate-300 text-slate-500 hover:border-indigo-400 hover:text-indigo-600"
                    onClick={() => set({ zipcodes: CORE10 })}>+ Core 10 Dallas ZIPs</button>
                </div>
              </div>
            )}
          </div>
        </div>

        <div>
          <div className="label mb-2">List-price band (ZIP-month median)</div>
          <div className="mb-2 flex flex-wrap gap-1.5">
            {PRICE_PRESETS.map((p) => (
              <Toggle key={p.label} active={(criteria.min_price ?? null) === p.min && (criteria.max_price ?? null) === p.max}
                onClick={() => set({ min_price: p.min, max_price: p.max })}>{p.label}</Toggle>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-2">{numInput("min_price", "Min $")}{numInput("max_price", "Max $")}</div>
        </div>

        <div>
          <div className="label mb-2">Home size band (sq ft)</div>
          <div className="grid grid-cols-2 gap-2">{numInput("min_sqft", "Min sqft")}{numInput("max_sqft", "Max sqft")}</div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <div className="label mb-2">Window ends</div>
            <select className="input" value={criteria.window_end ?? meta.default_window_end}
              onChange={(e) => set({ window_end: e.target.value })}>
              {windowEnds.map((m) => <option key={m} value={m}>{monthLabel(m)} ({m})</option>)}
            </select>
          </div>
          <div>
            <div className="label mb-2">Bootstrap seed</div>
            <Segmented size="sm" value={seed} onChange={setSeed} options={meta.seeds.map((s) => ({ value: s, label: s }))} />
          </div>
        </div>

        <button className="btn-primary w-full py-2.5" onClick={onRun} disabled={loading}>
          {loading ? <Spinner /> : <Play size={15} />} Run agents
        </button>
      </div>
    </div>
  );
}
