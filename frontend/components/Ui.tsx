"use client";

import React from "react";
import { LucideIcon, Play, ScanLine, Upload } from "lucide-react";

export function Badge({ children, tone="neutral" }: { children: React.ReactNode; tone?: "neutral"|"good"|"warn"|"bad"|"accent" }) {
  const tones = {
    neutral: "border-slate-700 bg-slate-900/50 text-slate-300",
    good: "border-emerald-500/20 bg-emerald-500/10 text-emerald-300",
    warn: "border-amber-500/20 bg-amber-500/10 text-amber-300",
    bad: "border-rose-500/20 bg-rose-500/10 text-rose-300",
    accent: "border-cyan-400/20 bg-cyan-400/10 text-cyan-200"
  };
  return <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[10px] font-semibold tracking-[.12em] uppercase ${tones[tone]}`}>{children}</span>;
}

export function Section({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return <section className="border-b border-slate-800/80 last:border-b-0">
    <div className="flex items-center justify-between px-3 py-2.5 text-[10px] font-semibold uppercase tracking-[.16em] text-slate-400">
      <span>{title}</span>{action}
    </div>
    <div className="px-3 pb-3">{children}</div>
  </section>;
}

export function IconButton({ label, children, onClick, active=false }: { label: string; children: React.ReactNode; onClick?:()=>void; active?:boolean }) {
  return <button onClick={onClick} title={label} aria-label={label} className={`grid size-8 place-items-center rounded-md border transition ${active ? "border-cyan-400/35 bg-cyan-400/10 text-cyan-100" : "border-slate-800 bg-slate-950/40 text-slate-400 hover:border-slate-700 hover:text-white"}`}>{children}</button>
}

export function Metric({ label, value, unit, source }: { label:string; value:string|number; unit?:string; source?:string }) {
  return <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-2.5">
    <div className="text-[10px] uppercase tracking-[.14em] text-slate-500">{label}</div>
    <div className="mt-1 flex items-baseline gap-1"><span className="mono text-sm text-slate-100">{value}</span>{unit && <span className="mono text-[10px] text-slate-500">{unit}</span>}</div>
    {source && <div className="mt-1 text-[9px] leading-3 text-slate-500">{source}</div>}
  </div>
}

export function EmptyState({ onDemo, onImport }: { onDemo:()=>void; onImport:()=>void }) {
  return <div className="grid h-full place-items-center overflow-hidden scan-grid">
    <div className="relative max-w-lg text-center">
      <div className="pulse-ring absolute left-1/2 top-1/2 size-64 -translate-x-1/2 -translate-y-1/2 rounded-full border border-cyan-400/20" />
      <div className="mx-auto grid size-16 place-items-center rounded-2xl border border-cyan-400/20 bg-slate-950/70 text-cyan-200"><ScanLine size={28}/></div>
      <div className="mt-5 text-sm font-semibold">No imaging study loaded</div>
      <div className="mx-auto mt-2 max-w-sm text-xs leading-5 text-slate-500">Import a DICOM or NIfTI study to begin analysis. All quantitative outputs are derived from source imaging data.</div>
      <div className="mt-5 flex justify-center gap-2">
        <button onClick={onImport} className="inline-flex items-center gap-2 rounded-md border border-cyan-400/25 bg-cyan-400/10 px-3 py-2 text-xs font-semibold text-cyan-100 hover:bg-cyan-400/15"><Upload size={14}/>Import Study</button>
        <button onClick={onDemo} className="inline-flex items-center gap-2 rounded-md border border-slate-700 bg-slate-900/60 px-3 py-2 text-xs text-slate-200 hover:bg-slate-800"><Play size={14}/>Open Demo Case</button>
      </div>
    </div>
  </div>
}

export function HelpRow({ icon: Icon, label, value }: { icon: LucideIcon; label:string; value:string }) {
  return <div className="flex items-center justify-between gap-2 py-1.5"><div className="flex min-w-0 items-center gap-2 text-[10px] text-slate-500"><Icon size={12}/><span>{label}</span></div><span className="mono truncate text-[10px] text-slate-300">{value}</span></div>
}
