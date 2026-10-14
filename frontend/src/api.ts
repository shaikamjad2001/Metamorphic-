export type Criteria = {
  zipcodes?: string[] | null;
  cities?: string[] | null;
  tiers?: string[] | null;
  min_price?: number | null;
  max_price?: number | null;
  min_sqft?: number | null;
  max_sqft?: number | null;
  window_end?: string;
  currency_unit?: "USD" | "USD_K";
  confidence_target?: number;
  label?: string | null;
};

export type ZipGeo = {
  zipcode: string;
  city: string | null;
  neighborhood: string | null;
  core_submarket: string | null;
  price_tier: string;
  lat: number;
  lon: number;
  distance_mi: number;
};

export type Meta = {
  months: string[];
  default_window_end: string;
  zips: ZipGeo[];
  cities: { city: string; n_zips: number }[];
  tiers: string[];
  seeds: number[];
  n_records: number;
  n_listings: number;
  manifest: any;
  retrieved_at: string | null;
  thresholds: Record<string, any>;
  llm: string | null;
};

export type MonthlyStat = {
  month: string;
  active_count: number;
  n_zips: number;
  median_price: number | null;
  median_price_per_sqft: number | null;
  price_q1: number | null;
  price_q3: number | null;
  new_listings: number;
  median_dom: number | null;
  mom_pct_price: number | null;
};

export type ZipTrend = {
  zipcode: string;
  city: string | null;
  start_price: number;
  end_price: number;
  change_pct: number;
  end_active: number;
  rank: number;
};

export type AgentEvent = {
  step: number;
  agent: string;
  action: string;
  loop: "feedback" | "refinement" | null;
  iteration: number | null;
  detail: Record<string, any>;
  elapsed_ms: number;
};

export type ControlPlan = {
  relaxation_level: number;
  relaxation_factor: number;
  added_zips: string[];
  method: "hedonic" | "stratified_median";
  refinements: string[];
};

export type RunResult = {
  criteria: Criteria;
  seed: number;
  trend: {
    window_start: string;
    window_end: string;
    currency_unit: string;
    method: string;
    monthly_series: MonthlyStat[];
    trend_change_pct: number | null;
    annual_cagr_estimate: number | null;
    macro_divergence_score: number | null;
    zip_rankings: ZipTrend[];
    confidence: number;
    quality_audit_passed: boolean;
  };
  control: ControlPlan;
  events: AgentEvent[];
  caveats: string[];
  narrative: string;
  diagnostics: Record<string, any>;
};

export type MapZip = ZipGeo & {
  in_scope: boolean;
  added: boolean;
  change_pct: number | null;
  end_price: number | null;
  end_active: number | null;
  rank: number | null;
};

export type BenchRow = {
  month: string;
  trend_index: number | null;
  zhvi_index: number | null;
  fred_index: number | null;
  zhvi_metro: number | null;
  fred_median_listing_price: number | null;
  fred_active_listing_count: number | null;
  mortgage_rate_30y: number | null;
};

export type Analysis = { result: RunResult; zips: MapZip[]; benchmark: BenchRow[] };

export type MRRow = {
  mr: string;
  name: string;
  family: string;
  refined: boolean;
  n_executions: number;
  n_not_applicable: number;
  violations: number;
  violation_rate: number;
  ci95: [number, number];
  n_base_inputs: number;
  bases_violated_any_seed: number;
  base_violation_rate: number;
  base_ci95: [number, number];
  per_seed_rate: Record<string, number>;
  seed_sensitive_bases: number;
  violations_with_path_divergence: number;
  crashes: number;
};

export type CatalogEntry = {
  id: string;
  name: string;
  family: string;
  transformation: string;
  relation: string;
  subdomain: string;
  tolerance: string;
  target_fault: string;
};

export type MTResults = {
  headline: {
    elapsed_seconds: number;
    seeds: number[];
    base_inputs: { n: number; generator_seed: number; labels: string[] };
    catalog: CatalogEntry[];
    results: { natural: MRRow[]; pinned?: MRRow[] };
    snapshot_sha256: Record<string, string>;
  };
  diagnosis: { by_mr: Record<string, any>; top3: string[] } | null;
  history: { stage: string; natural: MRRow[] }[];
};

export type CaseSide = {
  series: MonthlyStat[];
  control: ControlPlan;
  confidence: number;
  method: string;
  trend_change_pct: number | null;
  currency_unit: string;
  events: AgentEvent[];
};

export type CaseResult = {
  mr: CatalogEntry;
  mode: string;
  seed: number;
  base_idx: number;
  source_criteria: Criteria;
  follow_criteria: Criteria;
  transform_info: Record<string, any>;
  applicable: boolean;
  violated: boolean | null;
  max_deviation: number | null;
  detail: Record<string, any> | null;
  path_diverged: boolean;
  source: CaseSide;
  follow: CaseSide;
};

export type RecordedCase = {
  base_idx: number;
  base: string;
  seed: number;
  mode: "natural" | "pinned";
  violated: boolean | null;
  applicable: boolean | null;
  path_diverged: boolean | null;
  max_deviation: number | null;
  error: string | null;
};

export type ChatRunSummary = {
  label: string;
  criteria: Criteria;
  window: [string, string];
  method: string;
  start_price: number | null;
  end_price: number | null;
  change_pct: number | null;
  cagr_pct: number | null;
  start_active: number;
  end_active: number;
  confidence: number;
  confidence_target: number;
  audit_passed: boolean;
  n_zips: number;
  control: ControlPlan;
  feedback_cycles: number;
  refinements_attempted: string[];
  caveats: string[];
  series: { month: string; median_price: number | null; active_count: number; median_ppsf: number | null }[];
  zip_rankings: ZipTrend[];
  runtime_ms: number;
};

export type ChatItem =
  | { type: "event"; run: number | null; event: Omit<AgentEvent, "step"> & { step?: number } }
  | { type: "plan"; plan: { intent: string; planner: string; notes: string[]; labels: string[] } & Record<string, any> }
  | { type: "run_start"; run: number; label: string; criteria: Criteria }
  | { type: "run_result"; run: number; summary: ChatRunSummary }
  | { type: "run_error"; run: number; label: string; error: string }
  | { type: "answer"; text: string; writer: string; intent: string; facts: any; context: any }
  | { type: "done"; elapsed_ms: number }
  | { type: "error"; text: string };

export async function chatStream(question: string, seed: number, context: any, onItem: (i: ChatItem) => void) {
  const r = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, seed, context }),
  });
  if (!r.ok || !r.body) throw new Error(r.statusText || "chat failed");
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let nl;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (line) onItem(JSON.parse(line));
    }
  }
  if (buf.trim()) onItem(JSON.parse(buf));
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {}
    throw new Error(msg);
  }
  return r.json();
}

export const api = {
  meta: () => req<Meta>("/api/meta"),
  analyze: (criteria: Criteria, seed: number) =>
    req<Analysis>("/api/analyze", { method: "POST", body: JSON.stringify({ criteria, seed }) }),
  parse: (query: string) =>
    req<{ criteria: Criteria; parser: string; notes: string[] }>("/api/parse", {
      method: "POST",
      body: JSON.stringify({ query }),
    }),
  listings: (zipcodes: string[], status?: string, limit = 300) => {
    const p = new URLSearchParams();
    if (zipcodes.length) p.set("zipcodes", zipcodes.join(","));
    if (status) p.set("status", status);
    p.set("limit", String(limit));
    return req<{ summary: any; rows: any[] }>(`/api/listings?${p}`);
  },
  macro: () => req<any[]>("/api/macro"),
  catalog: () => req<{ relations: CatalogEntry[]; base_inputs: Criteria[]; seeds: number[] }>("/api/mt/catalog"),
  results: () => req<MTResults>("/api/mt/results"),
  cases: (mr: string) => req<RecordedCase[]>(`/api/mt/cases?mr=${encodeURIComponent(mr)}`),
  runCase: (mr: string, base_idx: number, seed: number, mode: "natural" | "pinned") =>
    req<CaseResult>("/api/mt/run", { method: "POST", body: JSON.stringify({ mr, base_idx, seed, mode }) }),
  trace: () => req<RunResult>("/api/trace"),
};
