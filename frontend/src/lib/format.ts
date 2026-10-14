export const money = (x: number | null | undefined, unit = "USD", compact = false) => {
  if (x == null || Number.isNaN(x)) return "—";
  const usd = unit === "USD_K" ? x * 1000 : x;
  if (compact) {
    if (Math.abs(usd) >= 1e6) return `$${(usd / 1e6).toFixed(2)}M`;
    if (Math.abs(usd) >= 1e3) return `$${(usd / 1e3).toFixed(0)}K`;
  }
  return `$${Math.round(usd).toLocaleString("en-US")}`;
};

export const pct = (x: number | null | undefined, digits = 1, signed = true) => {
  if (x == null || Number.isNaN(x)) return "—";
  return `${signed && x > 0 ? "+" : ""}${x.toFixed(digits)}%`;
};

export const num = (x: number | null | undefined, digits = 0) =>
  x == null || Number.isNaN(x) ? "—" : x.toLocaleString("en-US", { maximumFractionDigits: digits });

export const monthLabel = (m: string) => {
  const [y, mm] = m.split("-").map(Number);
  return new Date(y, mm - 1, 1).toLocaleString("en-US", { month: "short", year: "2-digit" });
};

export const changeColor = (x: number | null | undefined) => {
  if (x == null) return "#cbd5e1";
  const c = Math.max(-12, Math.min(12, x)) / 12;
  if (c >= 0) return `rgba(16,185,129,${0.35 + 0.65 * c})`;
  return `rgba(244,63,94,${0.35 + 0.65 * -c})`;
};

export const AGENT_COLORS: Record<string, string> = {
  Orchestrator: "#6366f1",
  DataScout: "#0ea5e9",
  QualityAuditor: "#f59e0b",
  TrendSpecialist: "#8b5cf6",
  Synthesizer: "#10b981",
  LoopSupervisor: "#ef4444",
};
