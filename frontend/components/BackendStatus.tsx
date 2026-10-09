"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, checkBackendHealth } from "../lib/api";

type HealthState = { kind: "checking" | "online" | "offline"; detail: string };

export default function BackendStatus() {
  const [state, setState] = useState<HealthState>({ kind: "checking", detail: "Checking Python API…" });
  const [attempt, setAttempt] = useState(0);
  const refresh = useCallback(() => setAttempt(value => value + 1), []);
  useEffect(() => {
    let active = true;
    void checkBackendHealth().then(data => {
      if (active) setState({ kind: "online", detail: `MedAxis backend v${data.version} connected` });
    }).catch(error => {
      if (active) setState({
        kind: "offline",
        detail: error instanceof Error ? error.message : "Backend is unreachable.",
      });
    });
    return () => { active = false; };
  }, [attempt]);

  if (state.kind === "online") return null;
  return (
    <aside role={state.kind === "offline" ? "alert" : "status"} className="fixed left-1/2 top-3 z-[95] w-[min(92vw,760px)] -translate-x-1/2 rounded-xl border border-amber-500/60 bg-[#161b24] px-4 py-3 text-slate-100 shadow-2xl">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <strong className="text-sm">{state.kind === "offline" ? "Python backend disconnected" : "Checking MedAxis services"}</strong>
        <button type="button" onClick={refresh} className="rounded bg-blue-700 px-3 py-1.5 text-xs hover:bg-blue-600">Retry connection</button>
      </div>
      <p className="mt-2 text-xs leading-5 text-slate-300 break-words">{state.detail}</p>
      {state.kind === "offline" && (
        <div className="mt-2 text-xs text-amber-200">
          Run <code className="rounded bg-slate-950 px-1">python -m uvicorn app.main:app --host 127.0.0.1 --port 8000</code> from the MedAxis backend virtual environment.
          Check <a className="underline" href={`${API_BASE}/health`} target="_blank" rel="noreferrer">API health</a>. Use a second terminal for the Next.js frontend.
        </div>
      )}
    </aside>
  );
}
