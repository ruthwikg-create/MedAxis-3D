"use client";

import Link from "next/link";
import { useState } from "react";

type Entry = { id: string; metric: string; value: number; unit: string; method: string; uncertainty: string };
type Manifest = {
  schema: "medaxis-experiment-v1";
  generatedAt: string;
  datasetAlias: string;
  title: string;
  hypothesis: string;
  protocol: string;
  softwareRevision: string;
  entries: Entry[];
  provenance: { source: "researcher-entered"; imagingAutomaticallyMeasured: false; containsImages: false };
};
const MAX_ROWS = 2000;
function escapeCSV(text: string | number) { return '"' + String(text).replace(/"/g, '""') + '"'; }
function download(filename: string, contents: string, mime: string) {
  const url = URL.createObjectURL(new Blob([contents], { type: mime }));
  const a = document.createElement("a");
  a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function validEntry(item: unknown): item is Entry {
  if (!item || typeof item !== "object") return false;
  const row = item as Record<string, unknown>;
  return typeof row.id === "string" && typeof row.metric === "string" &&
    row.metric.length <= 160 && typeof row.value === "number" && Number.isFinite(row.value) &&
    typeof row.unit === "string" && row.unit.length <= 32 &&
    typeof row.method === "string" && row.method.length <= 300 &&
    typeof row.uncertainty === "string" && row.uncertainty.length <= 500;
}
function decodeManifest(value: unknown): Manifest {
  if (!value || typeof value !== "object") throw new Error("Invalid experiment file");
  const m = value as Record<string, unknown>;
  if (m.schema !== "medaxis-experiment-v1" ||
      !Array.isArray(m.entries) || m.entries.length > MAX_ROWS || !m.entries.every(validEntry)) {
    throw new Error("Invalid experiment schema or measurements");
  }
  for (const [key, limit] of [["datasetAlias", 120], ["title", 200], ["hypothesis", 6000],
    ["protocol", 12000], ["softwareRevision", 120]] as const) {
    if (typeof m[key] !== "string" || m[key].length > limit) throw new Error("Invalid field: " + key);
  }
  return {
    schema: "medaxis-experiment-v1",
    generatedAt: typeof m.generatedAt === "string" ? m.generatedAt.slice(0, 60) : "",
    datasetAlias: m.datasetAlias as string,
    title: m.title as string,
    hypothesis: m.hypothesis as string,
    protocol: m.protocol as string,
    softwareRevision: m.softwareRevision as string,
    entries: m.entries,
    provenance: { source: "researcher-entered", imagingAutomaticallyMeasured: false, containsImages: false },
  };
}

export default function ResearchExperiments() {
  const [title, setTitle] = useState("Synthetic CT algorithm experiment");
  const [datasetAlias, setDatasetAlias] = useState("synthetic-reference-01");
  const [hypothesis, setHypothesis] = useState("");
  const [protocol, setProtocol] = useState("");
  const [softwareRevision, setSoftwareRevision] = useState("");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [metric, setMetric] = useState("");
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState("HU");
  const [method, setMethod] = useState("");
  const [uncertainty, setUncertainty] = useState("");
  const [message, setMessage] = useState("");

  const manifest = (): Manifest => ({
    schema: "medaxis-experiment-v1",
    generatedAt: new Date().toISOString(),
    title, datasetAlias, hypothesis, protocol, softwareRevision, entries,
    provenance: { source: "researcher-entered", imagingAutomaticallyMeasured: false, containsImages: false },
  });
  function addEntry(event: React.FormEvent) {
    event.preventDefault();
    const numeric = Number(value);
    if (!metric.trim() || !value.trim() || !Number.isFinite(numeric) || entries.length >= MAX_ROWS) {
      setMessage("Enter a valid finite measurement, or export and start a new experiment.");
      return;
    }
    setEntries(previous => [...previous, {
      id: crypto.randomUUID(), metric: metric.trim(), value: numeric, unit,
      method: method.trim(), uncertainty: uncertainty.trim(),
    }]);
    setValue(""); setMetric(""); setUncertainty(""); setMessage("Measurement recorded as manually entered.");
  }
  async function importManifest(file?: File) {
    if (!file) return;
    if (file.size > 2_000_000) { setMessage("File exceeds the 2 MB import limit."); return; }
    try {
      const m = decodeManifest(JSON.parse(await file.text()));
      setTitle(m.title); setDatasetAlias(m.datasetAlias);
      setHypothesis(m.hypothesis); setProtocol(m.protocol);
      setSoftwareRevision(m.softwareRevision); setEntries(m.entries);
      setMessage("Imported research manifest. No image data was loaded.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to read the manifest.");
    }
  }
  const groups = Array.from(new Set(entries.map(e => e.metric + " [" + e.unit + "]")));
  return <main className="min-h-screen bg-[#080e1a] text-slate-100 px-5 py-10">
    <div className="max-w-6xl mx-auto space-y-7">
      <nav className="flex justify-between items-center gap-4 flex-wrap">
        <Link href="/" className="text-blue-300 underline">← MedAxis-3D Workstation</Link>
        <span className="text-xs rounded border border-amber-500 px-3 py-2 text-amber-300">RESEARCH ONLY — NOT FOR DIAGNOSIS</span>
      </nav>
      <header className="space-y-2">
        <p className="tracking-widest text-blue-300 text-xs uppercase">Scientific reproducibility</p>
        <h1 className="text-4xl font-bold">Experiment &amp; Provenance Lab</h1>
        <p className="text-slate-400 max-w-3xl">Document a study protocol, record independently obtained measurements, and import/export a versioned research manifest. This module does not automatically analyze image pixels or transmit data to the backend.</p>
        <p className="text-amber-300 text-sm">Use only synthetic or appropriately de-identified data. Do not enter patient identifiers. Notes are held in this browser tab: export before leaving.</p>
      </header>
      <div className="flex flex-wrap gap-3">
        <button className="px-4 py-2 rounded bg-blue-600" onClick={() => download("medaxis-experiment.json", JSON.stringify(manifest(), null, 2), "application/json")}>Export JSON</button>
        <button disabled={!entries.length} className="px-4 py-2 rounded bg-slate-700 disabled:opacity-40" onClick={() => {
          const rows = [["metric","value","unit","method","uncertainty"], ...entries.map(e => [e.metric, String(e.value), e.unit, e.method, e.uncertainty])];
          download("medaxis-experiment.csv", rows.map(r => r.map(escapeCSV).join(",")).join("\r\n"), "text/csv;charset=utf-8");
        }}>Export CSV</button>
        <label className="rounded border border-slate-600 px-4 py-2 cursor-pointer">Import JSON manifest
          <input type="file" accept=".json,application/json" className="sr-only" onChange={e => { void importManifest(e.currentTarget.files?.[0]); e.currentTarget.value = ""; }} />
        </label>
      </div>
      {message && <p role="status" className="text-blue-300 text-sm">{message}</p>}
      <section className="rounded-xl border border-slate-700 bg-[#101c30] p-6 space-y-4">
        <h2 className="text-xl font-semibold">Research protocol</h2>
        <div className="grid md:grid-cols-2 gap-4">
          <label>Experiment title<input className="mt-1 block w-full p-3 rounded bg-slate-900 border border-slate-600" maxLength={200} value={title} onChange={e => setTitle(e.target.value)}/></label>
          <label>De-identified dataset alias<input className="mt-1 block w-full p-3 rounded bg-slate-900 border border-slate-600" maxLength={120} value={datasetAlias} onChange={e => setDatasetAlias(e.target.value)}/></label>
        </div>
        <label className="block">Software revision / Git commit SHA<input className="mt-1 block w-full p-3 rounded bg-slate-900 border border-slate-600" maxLength={120} value={softwareRevision} onChange={e => setSoftwareRevision(e.target.value)} placeholder="Record the tested revision"/></label>
        <label className="block">Hypothesis<textarea className="mt-1 block w-full p-3 rounded bg-slate-900 border border-slate-600 h-24" maxLength={6000} value={hypothesis} onChange={e => setHypothesis(e.target.value)}/></label>
        <label className="block">Reproducibility protocol<textarea className="mt-1 block w-full p-3 rounded bg-slate-900 border border-slate-600 h-36" maxLength={12000} value={protocol} onChange={e => setProtocol(e.target.value)}/></label>
      </section>
      <section className="rounded-xl border border-slate-700 bg-[#101c30] p-6 space-y-4">
        <h2 className="text-xl font-semibold">Independent measurement log</h2>
        <form className="grid md:grid-cols-5 gap-3" onSubmit={addEntry}>
          <label className="md:col-span-2">Metric<input required maxLength={160} className="mt-1 block w-full p-3 rounded bg-slate-900 border border-slate-600" value={metric} onChange={e => setMetric(e.target.value)} placeholder="e.g. reference mask volume"/></label>
          <label>Value<input type="number" required step="any" className="mt-1 block w-full p-3 rounded bg-slate-900 border border-slate-600" value={value} onChange={e => setValue(e.target.value)}/></label>
          <label>Unit<select className="mt-1 block w-full p-3 rounded bg-slate-900 border border-slate-600" value={unit} onChange={e => setUnit(e.target.value)}>{["HU","mm","mm²","cm³","%","unitless","seconds"].map(u => <option key={u}>{u}</option>)}</select></label>
          <button type="submit" className="self-end p-3 bg-blue-600 rounded">Add measurement</button>
          <label className="md:col-span-2">Method<input maxLength={300} className="mt-1 block w-full p-3 rounded bg-slate-900 border border-slate-600" value={method} onChange={e => setMethod(e.target.value)} placeholder="External reference tool or algorithm"/></label>
          <label className="md:col-span-3">Uncertainty / observations<input maxLength={500} className="mt-1 block w-full p-3 rounded bg-slate-900 border border-slate-600" value={uncertainty} onChange={e => setUncertainty(e.target.value)}/></label>
        </form>
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left"><thead><tr className="border-b border-slate-600">{["Metric","Value","Unit","Method","Uncertainty","Action"].map(h => <th key={h} className="p-3">{h}</th>)}</tr></thead><tbody>
            {entries.map(e => <tr className="border-b border-slate-800" key={e.id}><td className="p-3">{e.metric}</td><td className="p-3 tabular-nums">{e.value}</td><td className="p-3">{e.unit}</td><td className="p-3">{e.method}</td><td className="p-3">{e.uncertainty}</td><td className="p-3"><button className="text-red-300 underline" aria-label={"Remove " + e.metric} onClick={() => setEntries(rows => rows.filter(row => row.id !== e.id))}>Remove</button></td></tr>)}
          </tbody></table>
        </div>
        <p className="text-sm text-slate-400">{entries.length} manually entered measurements; maximum {MAX_ROWS}.</p>
      </section>
      <section className="rounded-xl border border-slate-700 bg-[#101c30] p-6">
        <h2 className="font-semibold text-xl mb-3">Exploratory summary</h2>
        <p className="text-sm text-slate-400 mb-4">Arithmetic means are grouped by exact metric and unit; this is not inferential statistics or clinical validation.</p>
        <div className="grid md:grid-cols-3 gap-3">{groups.map(name => {
          const rows = entries.filter(e => e.metric + " [" + e.unit + "]" === name);
          const avg = rows.reduce((sum, e) => sum + e.value, 0) / rows.length;
          return <div key={name} className="p-4 rounded border border-slate-700"><p className="text-sm text-slate-300">{name}</p><p className="text-2xl font-semibold tabular-nums mt-2">{Number(avg.toPrecision(6))}</p><p className="text-xs text-slate-400">Mean of {rows.length} researcher-entered values</p></div>;
        })}</div>
      </section>
    </div>
  </main>;
}
