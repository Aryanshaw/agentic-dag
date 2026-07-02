import { BaseURL } from "./constants";

async function j(path: string, init?: RequestInit) {
  const res = await fetch(`${BaseURL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export type NodeLog = { ts: string; level: string; message: string; data: unknown };
export type Node = {
  id: string;
  node_key: string;
  type: string;
  status: string;
  input: unknown;
  output: unknown;
  error: string | null;
  attempts: number;
  logs: NodeLog[];
};
export type Edge = { source: string; target: string; condition?: string };
export type Run = { id: string; status: string; request: unknown; nodes: Node[]; edges: Edge[] };
export type Graph = { id: string; name: string; latest_version: number };
export type GraphDef = {
  id: string;
  name: string;
  nodes: { key: string; type: string }[];
  edges: Edge[];
};

export const listGraphs = (): Promise<Graph[]> => j("/graphs");
export const getGraphDef = (id: string): Promise<GraphDef> => j(`/graphs/${id}`);
export const execute = (graphId: string, text: string): Promise<Run> =>
  j(`/runs/execute/${graphId}`, { method: "POST", body: JSON.stringify({ request: { text } }) });
export const getRun = (id: string): Promise<Run> => j(`/runs/${id}`);
export const retry = (nodeId: string): Promise<Run> => j(`/nodes/${nodeId}/retry`, { method: "POST" });
export const approve = (nodeId: string): Promise<Run> => j(`/nodes/${nodeId}/approve`, { method: "POST" });
export const reject = (nodeId: string, reason?: string): Promise<Run> =>
  j(`/nodes/${nodeId}/reject`, { method: "POST", body: JSON.stringify({ reason }) });
