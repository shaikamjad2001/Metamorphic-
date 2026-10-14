import { useCallback, useEffect, useState } from "react";
import { Activity, Database, FlaskConical, GitBranch, LineChart, MessageSquare } from "lucide-react";
import { api, type Analysis, type Criteria, type Meta } from "./api";
import AnalyzePage from "./pages/Analyze";
import ChatPage from "./pages/Chat";
import WorkflowPage from "./pages/Workflow";
import LabPage from "./pages/Lab";
import DataPage from "./pages/DataPage";
import { Spinner } from "./components/ui";

type Tab = "chat" | "analyze" | "workflow" | "lab" | "data";

const TABS: { id: Tab; label: string; icon: typeof LineChart }[] = [
  { id: "chat", label: "Ask the Agents", icon: MessageSquare },
  { id: "analyze", label: "Market Trends", icon: LineChart },
  { id: "workflow", label: "Agent Workflow", icon: GitBranch },
  { id: "lab", label: "Metamorphic Lab", icon: FlaskConical },
  { id: "data", label: "Data & Provenance", icon: Database },
];

const tabFromHash = (): Tab => {
  const h = window.location.hash.slice(1);
  return TABS.some((t) => t.id === h) ? (h as Tab) : "chat";
};

export default function App() {
  const [tab, setTabState] = useState<Tab>(tabFromHash);
  const setTab = (t: Tab) => {
    setTabState(t);
    window.history.replaceState(null, "", `#${t}`);
  };
  useEffect(() => {
    const onHash = () => setTabState(tabFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [criteria, setCriteria] = useState<Criteria>({});
  const [seed, setSeed] = useState(42);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async (c: Criteria, s: number) => {
    setLoading(true);
    setError(null);
    try {
      setAnalysis(await api.analyze(c, s));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    api.meta().then((m) => {
      setMeta(m);
      const c = { window_end: m.default_window_end };
      setCriteria(c);
      run(c, 42);
    }).catch((e) => setError(`Backend not reachable: ${e.message}`));
  }, [run]);

  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-[1000] border-b border-slate-200/70 bg-white/85 backdrop-blur">
        <div className="mx-auto flex max-w-[1500px] items-center gap-6 px-6 py-3">
          <div className="flex shrink-0 items-center gap-3">
            <div className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-indigo-600 to-violet-600 text-white shadow-md shadow-indigo-200">
              <Activity size={18} />
            </div>
            <div>
              <div className="text-sm font-bold leading-tight text-slate-900">DFW Housing Trends</div>
              <div className="text-[11px] leading-tight text-slate-500">Multi-agent analysis · metamorphic testing</div>
            </div>
          </div>
          <nav className="flex items-center gap-1">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`flex items-center gap-2 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition ${
                  tab === t.id ? "bg-indigo-50 text-indigo-700" : "text-slate-500 hover:bg-slate-100 hover:text-slate-800"
                }`}
              >
                <t.icon size={15} />
                {t.label}
              </button>
            ))}
          </nav>
          <div className="ml-auto hidden items-center gap-2 whitespace-nowrap text-xs text-slate-500 2xl:flex">
            <span className="h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_0_3px_rgba(16,185,129,0.15)]" />
            Real data · Realtor.com · Zillow · FRED · FHFA · Kaggle — frozen snapshot
            {meta && <span className="font-mono text-slate-400">{meta.months[0]}…{meta.months[meta.months.length - 1]}</span>}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1500px] px-6 py-6">
        {!meta && !error && (
          <div className="flex h-[60vh] items-center justify-center gap-3 text-slate-500">
            <Spinner /> Loading frozen snapshot…
          </div>
        )}
        {error && !meta && <div className="card card-pad text-rose-600">{error}</div>}
        {meta && (
          <div hidden={tab !== "chat"}>
            <ChatPage meta={meta} onOpen={(c) => { setCriteria(c); run(c, seed); setTab("analyze"); }} />
          </div>
        )}
        {meta && tab === "analyze" && (
          <AnalyzePage meta={meta} criteria={criteria} setCriteria={setCriteria} seed={seed} setSeed={setSeed}
            analysis={analysis} loading={loading} error={error} onRun={() => run(criteria, seed)}
            onRunWith={(c) => { setCriteria(c); run(c, seed); }} openWorkflow={() => setTab("workflow")} />
        )}
        {meta && tab === "workflow" && <WorkflowPage analysis={analysis} meta={meta} />}
        {meta && tab === "lab" && <LabPage />}
        {meta && tab === "data" && <DataPage meta={meta} />}
      </main>
    </div>
  );
}
