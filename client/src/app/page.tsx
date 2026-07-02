"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  approve,
  execute,
  getGraphDef,
  getRun,
  listGraphs,
  reject,
  retry,
  type Edge,
  type GraphDef,
  type Node,
  type Run,
} from "@/lib/api";

const STATUS_COLORS: Record<string, string> = {
  done: "bg-emerald-600",
  skipped: "bg-gray-600",
  running: "bg-blue-600",
  failed: "bg-red-600",
  awaiting_approval: "bg-amber-500",
  pending: "bg-slate-700",
};

// SVG fills (rects can't take tailwind bg- utilities)
const STATUS_FILL: Record<string, string> = {
  done: "#059669",
  skipped: "#374151",
  running: "#2563eb",
  failed: "#dc2626",
  awaiting_approval: "#d97706",
  pending: "#1e293b",
};
const STATUS_STROKE: Record<string, string> = {
  done: "#34d399",
  skipped: "#4b5563",
  running: "#60a5fa",
  failed: "#f87171",
  awaiting_approval: "#fbbf24",
  pending: "#334155",
};

function Badge({ status }: { status: string }) {
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium text-white ${STATUS_COLORS[status] ?? "bg-slate-700"}`}>
      {status}
    </span>
  );
}

type Cell = { key: string; type: string; status: string; id?: string };

// Longest-path layering → left-to-right columns. DAG so it terminates; seen guards anyway.
// ponytail: hand-rolled layout, swap for reactflow only if graphs get big/interactive.
function layout(cells: Cell[], edges: Edge[]) {
  const preds: Record<string, string[]> = {};
  cells.forEach((c) => (preds[c.key] = []));
  edges.forEach((e) => preds[e.target]?.push(e.source));
  const level: Record<string, number> = {};
  const lvl = (k: string, seen = new Set<string>()): number => {
    if (k in level) return level[k];
    if (seen.has(k)) return 0;
    seen.add(k);
    const p = preds[k] ?? [];
    return (level[k] = p.length ? Math.max(...p.map((s) => lvl(s, seen))) + 1 : 0);
  };
  cells.forEach((c) => lvl(c.key));
  const byCol: Record<number, string[]> = {};
  cells.forEach((c) => (byCol[level[c.key]] ??= []).push(c.key));
  const pos: Record<string, { col: number; row: number }> = {};
  Object.entries(byCol).forEach(([c, ks]) =>
    ks.forEach((k, i) => (pos[k] = { col: Number(c), row: i })),
  );
  const cols = Math.max(0, ...Object.keys(byCol).map(Number)) + 1;
  const rows = Math.max(1, ...Object.values(byCol).map((k) => k.length));
  return { pos, cols, rows, level };
}

const NW = 168;
const NH = 58;
const CW = 250;
const RH = 116;
const PAD = 28;

function GraphView({
  cells,
  edges,
  selected,
  onSelect,
  revealCol,
}: {
  cells: Cell[];
  edges: Edge[];
  selected: string | null;
  onSelect: (key: string) => void;
  revealCol: number; // columns with col <= revealCol show real status; the == col pulses
}) {
  const { pos, cols, rows, level } = useMemo(() => layout(cells, edges), [cells, edges]);
  const cx = (k: string) => PAD + pos[k].col * CW;
  const cy = (k: string) => PAD + pos[k].row * RH;
  const width = PAD * 2 + (cols - 1) * CW + NW;
  const height = PAD * 2 + (rows - 1) * RH + NH;
  const shown = (c: Cell) => (level[c.key] <= revealCol ? c.status : "pending");
  const isSkip = (k: string) => {
    const c = cells.find((x) => x.key === k);
    return c ? shown(c) === "skipped" : false;
  };

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full" style={{ maxHeight: 620 }}>
      <defs>
        <marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto">
          <path d="M0,0 L8,3 L0,6 Z" fill="#64748b" />
        </marker>
        <marker id="arrowLive" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto">
          <path d="M0,0 L8,3 L0,6 Z" fill="#34d399" />
        </marker>
      </defs>

      {edges.map((e, i) => {
        if (!pos[e.source] || !pos[e.target]) return null;
        const x1 = cx(e.source) + NW;
        const y1 = cy(e.source) + NH / 2;
        const x2 = cx(e.target);
        const y2 = cy(e.target) + NH / 2;
        const bothShown = level[e.source] <= revealCol && level[e.target] <= revealCol;
        const dim = isSkip(e.source) || isSkip(e.target) || !bothShown;
        const live = bothShown && !dim;
        const mx = (x1 + x2) / 2;
        return (
          <g key={i} opacity={dim ? 0.15 : 1} style={{ transition: "opacity 0.4s" }}>
            <path
              d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`}
              fill="none"
              stroke={live ? "#34d399" : "#64748b"}
              strokeWidth={live ? 2.5 : 1.5}
              markerEnd={live ? "url(#arrowLive)" : "url(#arrow)"}
            />
            {e.condition && (
              <text x={mx} y={(y1 + y2) / 2 - 6} fill="#94a3b8" fontSize={11} textAnchor="middle">
                {e.condition}
              </text>
            )}
          </g>
        );
      })}

      {cells.map((c) => {
        const st = shown(c);
        const sel = c.key === selected;
        const pulse = level[c.key] === revealCol && st !== "pending" && st !== "skipped";
        return (
          <g
            key={c.key}
            transform={`translate(${cx(c.key)},${cy(c.key)})`}
            onClick={() => onSelect(c.key)}
            style={{ cursor: "pointer", transition: "opacity 0.4s" }}
            opacity={st === "skipped" ? 0.4 : 1}
          >
            {pulse && (
              <rect x={-4} y={-4} width={NW + 8} height={NH + 8} rx={12} fill="none" stroke={STATUS_STROKE[st]} strokeWidth={2}>
                <animate attributeName="opacity" values="0.9;0;0.9" dur="1.2s" repeatCount="indefinite" />
                <animate attributeName="stroke-width" values="2;6;2" dur="1.2s" repeatCount="indefinite" />
              </rect>
            )}
            <rect
              width={NW}
              height={NH}
              rx={10}
              fill={STATUS_FILL[st] ?? "#1e293b"}
              stroke={sel ? "#fff" : STATUS_STROKE[st] ?? "#334155"}
              strokeWidth={sel ? 2.5 : 1.5}
            />
            <circle cx={NW - 14} cy={14} r={4} fill={STATUS_STROKE[st] ?? "#334155"} />
            <text x={14} y={24} fill="#f8fafc" fontSize={14} fontWeight={600}>
              {c.key}
            </text>
            <text x={14} y={43} fill="#cbd5e1" fontSize={11}>
              {c.type} · {st}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function Legend() {
  const items = ["pending", "running", "done", "skipped", "awaiting_approval", "failed"];
  return (
    <div className="flex flex-wrap gap-3 text-xs text-neutral-400">
      {items.map((s) => (
        <span key={s} className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: STATUS_STROKE[s] }} />
          {s}
        </span>
      ))}
    </div>
  );
}

function Json({ value }: { value: unknown }) {
  if (value == null) return <span className="text-neutral-500">—</span>;
  return (
    <pre className="overflow-auto rounded-lg bg-black/40 p-3 text-xs text-neutral-200 ring-1 ring-white/5">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export default function Page() {
  const [def, setDef] = useState<GraphDef | null>(null);
  const [text, setText] = useState("I was double-charged on my last invoice.");
  const [run, setRun] = useState<Run | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revealCol, setRevealCol] = useState(99); // skeleton fully shown until a run animates
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const animRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    listGraphs()
      .then((gs) => (gs[0] ? getGraphDef(gs[0].id) : null))
      .then((d) => setDef(d))
      .catch((e) => setError(String(e)));
  }, []);

  // poll while running
  const ACTIVE = run?.status === "running";
  useEffect(() => {
    if (!run || !ACTIVE) return;
    pollRef.current = setInterval(async () => {
      try {
        setRun(await getRun(run.id));
      } catch (e) {
        setError(String(e));
      }
    }, 1000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [run, ACTIVE]);

  // cells: from the run if we have one, else the skeleton definition
  const cells: Cell[] = useMemo(() => {
    if (run) return run.nodes.map((n) => ({ key: n.node_key, type: n.type, status: n.status, id: n.id }));
    if (def) return def.nodes.map((n) => ({ key: n.key, type: n.type, status: "pending" }));
    return [];
  }, [run, def]);

  const edges: Edge[] = run?.edges ?? def?.edges ?? [];

  // replay traversal column-by-column when a new run lands
  const startAnim = useCallback(
    (r: Run) => {
      if (animRef.current) clearInterval(animRef.current);
      const cs = r.nodes.map((n) => ({ key: n.node_key, type: n.type, status: n.status }));
      const { cols } = layout(cs, r.edges ?? []);
      setRevealCol(0);
      let c = 0;
      animRef.current = setInterval(() => {
        c += 1;
        setRevealCol(c);
        if (c >= cols && animRef.current) clearInterval(animRef.current);
      }, 650);
    },
    [],
  );

  useEffect(() => () => void (animRef.current && clearInterval(animRef.current)), []);

  const submit = useCallback(async () => {
    if (!def) return;
    setBusy(true);
    setError(null);
    setSelected(null);
    try {
      const r = await execute(def.id, text);
      setRun(r);
      startAnim(r);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }, [def, text, startAnim]);

  // retry/approve/reject resume the SAME run — only the newly-ready nodes run
  // server-side, so don't replay from column 0 (that looked like a full re-run).
  const act = async (fn: () => Promise<Run>) => {
    setBusy(true);
    setError(null);
    try {
      const r = await fn();
      setRun(r);
      setRevealCol(99); // show resolved state at once
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const node: Node | undefined = run?.nodes.find((n) => n.node_key === selected);

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-8 text-neutral-100">
      <header className="space-y-1">
        <h1 className="bg-gradient-to-r from-emerald-300 via-sky-300 to-indigo-300 bg-clip-text text-3xl font-bold text-transparent">
          Agentic DAG — Workflow Debugger
        </h1>
        <p className="text-sm text-neutral-400">Graph: {def ? def.name : "loading…"}</p>
      </header>

      <section className="flex flex-col gap-3 md:flex-row md:items-end">
        <textarea
          className="flex-1 rounded-xl border border-neutral-800 bg-neutral-900/60 p-3 text-sm outline-none focus:border-sky-600"
          rows={2}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Describe a support request…"
        />
        <button
          onClick={submit}
          disabled={!def || busy}
          className="rounded-xl bg-gradient-to-r from-sky-600 to-indigo-600 px-6 py-3 text-sm font-semibold shadow-lg shadow-sky-950/50 transition hover:opacity-90 disabled:opacity-50"
        >
          {busy ? "Working…" : "▶ Run workflow"}
        </button>
      </section>

      {error && <p className="rounded-lg bg-red-950 p-2 text-sm text-red-300">{error}</p>}

      {/* graph — always visible, full width */}
      <section className="space-y-3 rounded-2xl border border-neutral-800 bg-neutral-950/80 p-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold">Workflow</h2>
            {run && <Badge status={run.status} />}
          </div>
          <Legend />
        </div>
        <div className="overflow-x-auto rounded-xl bg-[radial-gradient(circle_at_1px_1px,rgba(255,255,255,0.05)_1px,transparent_0)] [background-size:22px_22px]">
          <GraphView cells={cells} edges={edges} selected={selected} onSelect={setSelected} revealCol={revealCol} />
        </div>
      </section>

      {/* node detail */}
      <section className="rounded-2xl border border-neutral-800 bg-neutral-950/80 p-5">
        <h2 className="mb-3 text-lg font-semibold">Node</h2>
        {!node && <p className="text-sm text-neutral-500">Select a node in the graph to inspect its input, output and logs.</p>}
        {node && (
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <span className="font-mono text-base">{node.node_key}</span>
              <Badge status={node.status} />
              <span className="text-xs text-neutral-500">attempts: {node.attempts}</span>
              <div className="ml-auto flex gap-2">
                {node.status === "failed" && (
                  <button onClick={() => act(() => retry(node.id))} disabled={busy} className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium">
                    Retry
                  </button>
                )}
                {node.status === "awaiting_approval" && (
                  <>
                    <button onClick={() => act(() => approve(node.id))} disabled={busy} className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium">
                      Approve
                    </button>
                    <button onClick={() => act(() => reject(node.id))} disabled={busy} className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-medium">
                      Reject
                    </button>
                  </>
                )}
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <p className="mb-1 text-xs uppercase tracking-wide text-neutral-500">Input</p>
                <Json value={node.input} />
              </div>
              <div>
                <p className="mb-1 text-xs uppercase tracking-wide text-neutral-500">Output</p>
                <Json value={node.output} />
              </div>
            </div>

            {node.error && (
              <div>
                <p className="mb-1 text-xs uppercase tracking-wide text-neutral-500">Error</p>
                <pre className="overflow-auto rounded-lg bg-red-950 p-3 text-xs text-red-300">{node.error}</pre>
              </div>
            )}

            <div>
              <p className="mb-1 text-xs uppercase tracking-wide text-neutral-500">Logs</p>
              <ul className="space-y-1">
                {node.logs.map((l, i) => (
                  <li key={i} className="text-xs">
                    <span className={l.level === "error" ? "text-red-400" : "text-neutral-400"}>[{l.level}]</span>{" "}
                    {l.message}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </section>
    </main>
  );
}
