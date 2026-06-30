"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  approve,
  execute,
  getRun,
  listGraphs,
  reject,
  retry,
  type Graph,
  type Node,
  type Run,
} from "@/lib/api";

const STATUS_COLORS: Record<string, string> = {
  done: "bg-green-600",
  skipped: "bg-gray-500",
  running: "bg-blue-600",
  failed: "bg-red-600",
  awaiting_approval: "bg-amber-500",
  pending: "bg-slate-600",
};

function Badge({ status }: { status: string }) {
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium text-white ${STATUS_COLORS[status] ?? "bg-slate-600"}`}>
      {status}
    </span>
  );
}

function Json({ value }: { value: unknown }) {
  if (value == null) return <span className="text-neutral-500">—</span>;
  return (
    <pre className="overflow-auto rounded bg-neutral-900 p-2 text-xs text-neutral-200">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export default function Page() {
  const [graph, setGraph] = useState<Graph | null>(null);
  const [text, setText] = useState("I was double-charged on my last invoice.");
  const [run, setRun] = useState<Run | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    listGraphs().then((gs) => setGraph(gs[0] ?? null)).catch((e) => setError(String(e)));
  }, []);

  // poll while the run is active (running)
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

  const submit = useCallback(async () => {
    if (!graph) return;
    setBusy(true);
    setError(null);
    setSelected(null);
    try {
      setRun(await execute(graph.id, text));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }, [graph, text]);

  const act = async (fn: () => Promise<Run>) => {
    setBusy(true);
    setError(null);
    try {
      setRun(await fn());
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const node: Node | undefined = run?.nodes.find((n) => n.id === selected);

  return (
    <main className="mx-auto max-w-5xl space-y-6 p-8 text-neutral-100">
      <header>
        <h1 className="text-2xl font-semibold">Agentic DAG — Workflow Debugger</h1>
        <p className="text-sm text-neutral-400">Graph: {graph ? graph.name : "loading…"}</p>
      </header>

      <section className="space-y-2">
        <textarea
          className="w-full rounded border border-neutral-700 bg-neutral-900 p-3 text-sm"
          rows={3}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Describe a support request…"
        />
        <button
          onClick={submit}
          disabled={!graph || busy}
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium disabled:opacity-50"
        >
          {busy ? "Working…" : "Run workflow"}
        </button>
      </section>

      {error && <p className="rounded bg-red-950 p-2 text-sm text-red-300">{error}</p>}

      {run && (
        <section className="grid grid-cols-1 gap-6 md:grid-cols-2">
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-medium">Run</h2>
              <Badge status={run.status} />
            </div>
            <ul className="divide-y divide-neutral-800 rounded border border-neutral-800">
              {run.nodes.map((n) => (
                <li
                  key={n.id}
                  onClick={() => setSelected(n.id)}
                  className={`flex cursor-pointer items-center justify-between p-3 hover:bg-neutral-900 ${
                    selected === n.id ? "bg-neutral-900" : ""
                  }`}
                >
                  <span className="font-mono text-sm">
                    {n.node_key} <span className="text-neutral-500">({n.type})</span>
                  </span>
                  <Badge status={n.status} />
                </li>
              ))}
            </ul>
          </div>

          <div className="space-y-3">
            <h2 className="text-lg font-medium">Node</h2>
            {!node && <p className="text-sm text-neutral-500">Select a node to inspect.</p>}
            {node && (
              <div className="space-y-3 rounded border border-neutral-800 p-3">
                <div className="flex items-center gap-2">
                  <span className="font-mono">{node.node_key}</span>
                  <Badge status={node.status} />
                  <span className="text-xs text-neutral-500">attempts: {node.attempts}</span>
                </div>

                <div className="flex gap-2">
                  {node.status === "failed" && (
                    <button onClick={() => act(() => retry(node.id))} disabled={busy} className="rounded bg-blue-600 px-3 py-1 text-xs">
                      Retry
                    </button>
                  )}
                  {node.status === "awaiting_approval" && (
                    <>
                      <button onClick={() => act(() => approve(node.id))} disabled={busy} className="rounded bg-green-600 px-3 py-1 text-xs">
                        Approve
                      </button>
                      <button onClick={() => act(() => reject(node.id))} disabled={busy} className="rounded bg-red-600 px-3 py-1 text-xs">
                        Reject
                      </button>
                    </>
                  )}
                </div>

                <div>
                  <p className="text-xs uppercase text-neutral-500">Input</p>
                  <Json value={node.input} />
                </div>
                <div>
                  <p className="text-xs uppercase text-neutral-500">Output</p>
                  <Json value={node.output} />
                </div>
                {node.error && (
                  <div>
                    <p className="text-xs uppercase text-neutral-500">Error</p>
                    <pre className="overflow-auto rounded bg-red-950 p-2 text-xs text-red-300">{node.error}</pre>
                  </div>
                )}
                <div>
                  <p className="text-xs uppercase text-neutral-500">Logs</p>
                  <ul className="space-y-1">
                    {node.logs.map((l, i) => (
                      <li key={i} className="text-xs">
                        <span className={l.level === "error" ? "text-red-400" : "text-neutral-400"}>
                          [{l.level}]
                        </span>{" "}
                        {l.message}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}
          </div>
        </section>
      )}
    </main>
  );
}
