"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  BarChart3,
  AlertCircle,
  Archive,
  ArrowLeft,
  Database,
  Download,
  FileCheck2,
  FileClock,
  FileImage,
  FileText,
  Grid2X2,
  Info,
  Layers3,
  Maximize2,
  Menu,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Upload,
  X,
} from "lucide-react";
import { api, clearAuthToken, downloadEndpoint, setAuthToken, viewerUrl } from "../lib/api";
import { AnalyticsSuite } from "../components/AnalyticsSuite";
import { useAppStore } from "../lib/store";
import { Badge, EmptyState, HelpRow, IconButton, Metric, Section } from "../components/Ui";

type Toast = { kind: "good" | "warn" | "bad"; text: string };
type Plane = "axial" | "sagittal" | "coronal";
type Workspace =
  | "2D Diagnostic"
  | "4-Panel MPR"
  | "3D Reconstruction"
  | "AI Analysis"
  | "Quantitative Analysis"
  | "Comparison"
  | "Reporting"
  | "Full Workstation";
type Mode = "BASIC" | "ADVANCED" | "RADIOLOGY" | "RESEARCH" | "ENGINEERING";

function formatNumber(value: number | null | undefined, decimals = 2): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: decimals,
  });
}

type CaseRecord = {
  case_id: string;
  status: string;
  classification: string;
  created_at: string;
  files?: string[];
  study?: Record<string, string | null>;
  summary?: {
    modality?: string;
    source_type?: string;
    pixel_spacing_mm?: number[];
    slice_thickness_mm?: number | null;
    volume_dimensions?: number[];
    files_detected?: number;
    slices_detected?: number;
    series_detected?: number;
    orientation?: string;
  };
};

type Measurements = {
  mean_intensity: number;
  median_intensity: number;
  area_mm2: number;
  units: string;
  method: string;
  voxel_spacing_mm: number[];
};

type QC = { overall: "PASS" | "WARNING" | "FAIL"; tests: Array<Record<string, unknown>> };
type Surface = {
  status: string;
  vertices: number[][];
  faces: number[][];
  vertex_count?: number;
  triangle_count?: number;
  surface_area_mm2?: number;
  volume_cm3?: number;
  bounding_box_mm?: number[];
  method?: string;
};
type ModelRecord = { model_id: string; model_name: string; modality: string; body_region: string; status: string };
type MPR = { axial: string; sagittal: string; coronal: string; position: { z: number; y: number; x: number } };
type Diagnostics = Record<string, string>;

const WORKSPACES: Workspace[] = [
  "2D Diagnostic",
  "4-Panel MPR",
  "3D Reconstruction",
  "AI Analysis",
  "Quantitative Analysis",
  "Comparison",
  "Reporting",
  "Full Workstation",
];
const MODES: Mode[] = ["BASIC", "ADVANCED", "RADIOLOGY", "RESEARCH", "ENGINEERING"];

function Workstation() {
  const [ready, setReady] = useState(false);
  const [cases, setCases] = useState<CaseRecord[]>([]);
  const [activeCase, setActiveCase] = useState<CaseRecord | null>(null);
  const [showLanding, setShowLanding] = useState(true);
  const [showImport, setShowImport] = useState(false);
  const [showCases, setShowCases] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showAnalytics, setShowAnalytics] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);
  const [measurements, setMeasurements] = useState<Measurements | null>(null);
  const [surface, setSurface] = useState<Surface | null>(null);
  const [mpr, setMpr] = useState<MPR | null>(null);
  const [models, setModels] = useState<ModelRecord[]>([]);
  const [qc, setQc] = useState<QC | null>(null);
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null);
  const [loadingCase, setLoadingCase] = useState(false);
  const [demoLoading, setDemoLoading] = useState(false);

  const backendOnline = diagnostics?.backend === "ONLINE";

  useEffect(() => {
    const timer = window.setTimeout(() => setReady(true), 850);
    void api<CaseRecord[]>("/cases").then(setCases).catch(() => setCases([]));
    void api<Diagnostics>("/system/diagnostics").then(setDiagnostics).catch(() => setDiagnostics(null));
    void api<ModelRecord[]>("/models").then(setModels).catch(() => setModels([]));
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 4500);
    return () => window.clearTimeout(timer);
  }, [toast]);

  async function openCase(record: CaseRecord) {
    setLoadingCase(true);
    try {
      const detail = await api<CaseRecord>(`/cases/${encodeURIComponent(record.case_id)}`);
      setActiveCase(detail);
      setMeasurements(null);
      setSurface(null);
      setQc(null);
      setMpr(null);
      setShowLanding(false);
      setShowCases(false);
      useAppStore.setState({ workspace: "2D Diagnostic", plane: "axial", position: { z: 0, y: 0, x: 0 }, windowLevel: null, windowWidth: null });
      await refreshDerived(detail.case_id);
    } catch (error) {
      setToast({ kind: "bad", text: error instanceof Error ? error.message : "Unable to open case." });
    } finally {
      setLoadingCase(false);
    }
  }

  async function refreshDerived(caseId: string) {
    try {
      const volume = await api<{ shape: number[] }>(`/viewer/${encodeURIComponent(caseId)}/volume`);
      const [z, y, x] = volume.shape;
      const center = {
        z: Math.max(0, Math.floor((z - 1) / 2)),
        y: Math.max(0, Math.floor((y - 1) / 2)),
        x: Math.max(0, Math.floor((x - 1) / 2)),
      };
      useAppStore.setState({ position: center });

      const [q, s, m, images] = await Promise.allSettled([
        api<QC>(`/qc/${encodeURIComponent(caseId)}`),
        api<Surface>(`/3d/${encodeURIComponent(caseId)}/surface`),
        api<Measurements>("/measurements", { method: "POST", body: JSON.stringify({ case_id: caseId, index: center.z, plane: "axial" }) }),
        api<MPR>(`/viewer/${encodeURIComponent(caseId)}/mpr?z=${center.z}&y=${center.y}&x=${center.x}`),
      ]);

      if (q.status === "fulfilled") setQc(q.value);
      if (s.status === "fulfilled") setSurface(s.value);
      if (m.status === "fulfilled") setMeasurements(m.value);
      if (images.status === "fulfilled") setMpr(images.value);
    } catch (error) {
      setToast({ kind: "warn", text: error instanceof Error ? error.message : "Derived analysis is unavailable." });
    }
  }

  async function openDemo() {
    setDemoLoading(true);
    try {
      const demo = await api<CaseRecord>("/cases/demo", { method: "POST" });
      setCases((current) => [demo, ...current.filter((item) => item.case_id !== demo.case_id)]);
      await openCase(demo);
      setToast({ kind: "good", text: "Synthetic research phantom loaded. This dataset is explicitly non-clinical." });
    } catch (error) {
      setToast({ kind: "bad", text: error instanceof Error ? error.message : "Demo case could not be created." });
    } finally {
      setDemoLoading(false);
    }
  }

  async function importStudy(files: FileList | null, modality: "AUTO" | "CT" | "MRI") {
    if (!files?.length) return;
    const form = new FormData();
    Array.from(files).forEach((file) => form.append("files", file));
    form.append("modality", modality);
    setLoadingCase(true);
    try {
      const imported = await api<CaseRecord>("/dicom/import", { method: "POST", body: form });
      setCases((current) => [imported, ...current.filter((item) => item.case_id !== imported.case_id)]);
      setShowImport(false);
      await openCase(imported);
      setToast({ kind: "good", text: `Imported ${files.length} file${files.length === 1 ? "" : "s"}. Geometry and metadata were parsed server-side.` });
    } catch (error) {
      setToast({ kind: "bad", text: error instanceof Error ? error.message : "Import failed." });
    } finally {
      setLoadingCase(false);
    }
  }

  if (!ready) return <Startup />;

  return (
    <main className="min-h-screen bg-[var(--bg)] text-[var(--text)]">
      <AnimatePresence>
        {showLanding && !activeCase ? (
          <Landing
            onOpen={() => setShowLanding(false)}
            onImport={() => setShowImport(true)}
            onDemo={openDemo}
            onCases={() => setShowCases(true)}
            onSettings={() => setShowSettings(true)}
            onResearch={() => { setShowLanding(false); useAppStore.setState({ mode: "RESEARCH", workspace: "Full Workstation" }); }}
            demoLoading={demoLoading}
          />
        ) : null}
      </AnimatePresence>

      {!showLanding || activeCase ? (
        <WorkspaceShell
          activeCase={activeCase}
          cases={cases}
          backendOnline={backendOnline}
          loadingCase={loadingCase}
          measurements={measurements}
          surface={surface}
          mpr={mpr}
          models={models}
          qc={qc}
          diagnostics={diagnostics}
          onOpenCases={() => setShowCases(true)}
          onDemo={openDemo}
          onImport={() => setShowImport(true)}
          onHome={() => {
            setActiveCase(null);
            setShowLanding(true);
          }}
          onSettings={() => setShowSettings(true)}
          onAnalytics={() => setShowAnalytics(true)}
          refresh={() => activeCase && void refreshDerived(activeCase.case_id)}
          setToast={setToast}
        />
      ) : null}

      <AnimatePresence>
        {showImport ? <ImportModal onClose={() => setShowImport(false)} onImport={importStudy} /> : null}
        {showCases ? <CasesModal cases={cases} onClose={() => setShowCases(false)} onOpen={openCase} onError={(message) => setToast({ kind: "bad", text: message })} onDelete={(id) => { setCases((current) => current.filter((item) => item.case_id !== id)); if (activeCase?.case_id === id) { setActiveCase(null); setShowLanding(true); } setToast({ kind: "good", text: "Case deleted from the local development store." }); }} /> : null}
        {showSettings ? <SettingsModal onClose={() => setShowSettings(false)} /> : null}
        {showAnalytics ? <AnalyticsSuite activeCase={activeCase} cases={cases} onClose={() => setShowAnalytics(false)} setToast={(value) => setToast(value)} /> : null}
        {toast ? <ToastView toast={toast} onClose={() => setToast(null)} /> : null}
      </AnimatePresence>
    </main>
  );
}

function Startup() {
  return (
    <div className="grid min-h-screen place-items-center bg-[#05070a] text-slate-200">
      <div className="w-[340px] px-4">
        <div className="flex items-end justify-between">
          <div>
            <div className="text-[9px] font-semibold uppercase tracking-[.32em] text-cyan-300/70">MEDAXIS 3D</div>
            <div className="mt-2 text-xl font-semibold tracking-tight">Imaging engine</div>
          </div>
          <span className="mono text-[10px] text-slate-500">v4.1.1</span>
        </div>
        <div className="mt-6 h-px w-full overflow-hidden bg-slate-800">
          <motion.div initial={{ x: "-100%" }} animate={{ x: "0%" }} transition={{ duration: 0.8, ease: "easeOut" }} className="h-full w-full bg-cyan-400" />
        </div>
        <div className="mt-3 grid gap-2 text-[10px] uppercase tracking-[.13em] text-slate-500">
          {["Initializing imaging engine…", "Loading visualization engine…", "Checking DICOM services…", "Checking AI models…", "Checking system capabilities…"].map((text, index) => (
            <motion.div key={text} initial={{ opacity: 0, x: -4 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: index * 0.12 }}>{text}</motion.div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Landing(props: { onOpen: () => void; onImport: () => void; onDemo: () => void; onCases: () => void; onSettings: () => void; onResearch: () => void; demoLoading: boolean }) {
  return (
    <motion.section initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="relative min-h-screen overflow-hidden bg-[#06090d]">
      <div className="absolute inset-0 scan-grid opacity-60" />
      <div className="absolute left-[10%] top-[20%] h-52 w-52 rounded-full border border-cyan-400/10 pulse-ring" />
      <div className="relative mx-auto flex min-h-screen max-w-6xl flex-col px-6 py-8">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="grid size-9 place-items-center rounded-xl border border-cyan-300/20 bg-cyan-300/[.06] text-cyan-200"><Layers3 size={18} /></div>
            <div><div className="text-[10px] font-semibold uppercase tracking-[.22em] text-slate-400">MEDAXIS 3D</div><div className="text-[9px] text-slate-600">Multimodal Imaging Workstation</div></div>
          </div>
          <div className="flex gap-2"><button onClick={props.onSettings} className="rounded-md border border-slate-800 px-3 py-2 text-xs text-slate-400 hover:text-white">Settings</button><button onClick={props.onCases} className="rounded-md border border-slate-800 px-3 py-2 text-xs text-slate-400 hover:text-white">Recent Cases</button></div>
        </div>

        <div className="grid flex-1 items-center gap-12 py-16 lg:grid-cols-[1.05fr_.95fr]">
          <div>
            <Badge tone="accent">Research / Educational Use</Badge>
            <h1 className="mt-5 max-w-2xl text-5xl font-semibold leading-[1.02] tracking-[-.045em] text-slate-100 sm:text-6xl">Advanced multimodal imaging, built like a workstation.</h1>
            <p className="mt-6 max-w-xl text-sm leading-6 text-slate-500">A high-density environment for DICOM and NIfTI review, multiplanar reconstruction, 3D visualization, quantitative analysis, provenance, and research workflows.</p>
            <div className="mt-8 flex flex-wrap gap-2">
              <button onClick={props.onOpen} className="rounded-md border border-cyan-300/25 bg-cyan-300/10 px-4 py-2.5 text-sm font-semibold text-cyan-100 hover:bg-cyan-300/15">Open Workstation</button>
              <button onClick={props.onImport} className="inline-flex items-center gap-2 rounded-md border border-slate-700 bg-slate-900/60 px-4 py-2.5 text-sm text-slate-200"><Upload size={15} />Import DICOM / NIfTI / ZIP</button>
              <button onClick={props.onDemo} disabled={props.demoLoading} className="inline-flex items-center gap-2 rounded-md border border-slate-800 px-4 py-2.5 text-sm text-slate-400 disabled:opacity-50"><Activity size={15} />{props.demoLoading ? "Building demo…" : "Open Demo Case"}</button>
              <button onClick={props.onResearch} className="rounded-md border border-slate-800 px-4 py-2.5 text-sm text-slate-500 hover:text-slate-200">Research Mode</button>
            </div>
            <div className="mt-10 grid max-w-2xl grid-cols-2 gap-x-8 gap-y-4 border-t border-slate-800/80 pt-6 sm:grid-cols-4">
              {["2D viewer", "MPR", "3D surface", "Quantitative"].map((item) => <div key={item}><div className="text-[9px] uppercase tracking-[.16em] text-slate-600">Core</div><div className="mt-1 text-xs text-slate-300">{item}</div></div>)}
            </div>
          </div>
          <div className="relative min-h-[440px] rounded-2xl border border-slate-800 bg-[#0b1016]/80 p-3 shadow-2xl">
            <div className="relative h-full overflow-hidden rounded-xl bg-[#070b10] scan-grid">
              <div className="absolute inset-x-5 top-5 flex items-center justify-between text-[9px] uppercase tracking-[.18em] text-slate-600"><span>Source / geometry / analysis</span><span>DATA-DERIVED</span></div>
              <div className="absolute inset-14 rounded-full border border-cyan-300/10" />
              <div className="absolute left-1/2 top-1/2 h-56 w-56 -translate-x-1/2 -translate-y-1/2 rounded-full border border-cyan-300/15 shadow-[0_0_80px_rgba(98,211,255,.06)]" />
              <div className="absolute left-1/2 top-1/2 h-32 w-44 -translate-x-1/2 -translate-y-1/2 rounded-[40%] border border-cyan-200/20 bg-cyan-200/[.03]" />
              <div className="absolute left-[22%] top-[28%] h-px w-[56%] bg-cyan-300/20" /><div className="absolute left-1/2 top-[20%] h-[60%] w-px bg-cyan-300/20" />
              <div className="absolute bottom-5 left-5 right-5 grid grid-cols-3 gap-2">{["SOURCE", "GEOMETRY", "ANALYSIS"].map((item, index) => <div key={item} className="rounded border border-slate-800 bg-slate-950/65 px-2 py-2"><div className="text-[8px] tracking-[.16em] text-slate-600">{item}</div><div className="mt-1 mono text-[10px] text-slate-300">{index === 0 ? "DICOM / NIfTI" : index === 1 ? "MPR READY" : "NO FABRICATED VALUES"}</div></div>)}</div>
            </div>
          </div>
        </div>
        <footer className="flex flex-col gap-1 border-t border-slate-800/80 pt-4 text-[9px] uppercase tracking-[.12em] text-slate-600 sm:flex-row sm:items-center sm:justify-between"><span>Advanced Multimodal Medical Imaging & 3D Analysis Workstation</span><span>Created By: <span className="text-slate-400">Ruthwik Goparaju</span></span></footer>
      </div>
    </motion.section>
  );
}

function WorkspaceShell(props: {
  activeCase: CaseRecord | null;
  cases: CaseRecord[];
  backendOnline: boolean;
  loadingCase: boolean;
  measurements: Measurements | null;
  surface: Surface | null;
  mpr: MPR | null;
  models: ModelRecord[];
  qc: QC | null;
  diagnostics: Diagnostics | null;
  onOpenCases: () => void;
  onDemo: () => void;
  onImport: () => void;
  onHome: () => void;
  onSettings: () => void;
  onAnalytics: () => void;
  refresh: () => void;
  setToast: React.Dispatch<React.SetStateAction<Toast | null>>;
}) {
  const { activeCase, cases, backendOnline, loadingCase, measurements, surface, mpr, models, qc, diagnostics, onOpenCases, onDemo, onImport, onHome, onSettings, onAnalytics, refresh, setToast } = props;
  const store = useAppStore();
  const [cine, setCine] = useState(false);
  const [windowOpen, setWindowOpen] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });

  const dimensions = activeCase?.summary?.volume_dimensions ?? [1, 1, 1];
  const maxSlice = useMemo(() => {
    if (store.plane === "axial") return Math.max(0, (dimensions[2] ?? 1) - 1);
    if (store.plane === "coronal") return Math.max(0, (dimensions[1] ?? 1) - 1);
    return Math.max(0, (dimensions[0] ?? 1) - 1);
  }, [dimensions, store.plane]);

  const currentSlice = store.plane === "axial" ? store.position.z : store.plane === "coronal" ? store.position.y : store.position.x;
  const imageSrc = activeCase ? viewerUrl(activeCase.case_id, store.plane, Math.min(currentSlice, maxSlice), store.windowLevel, store.windowWidth) : "";

  useEffect(() => {
    if (!activeCase) return;
    const clamped = Math.min(currentSlice, maxSlice);
    if (clamped !== currentSlice) store.setSlice(clamped);
  }, [activeCase, currentSlice, maxSlice, store]);

  useEffect(() => {
    if (!cine || !activeCase) return;
    const timer = window.setInterval(() => {
      const next = currentSlice >= maxSlice ? 0 : currentSlice + 1;
      store.setSlice(next);
    }, 180);
    return () => window.clearInterval(timer);
  }, [activeCase, cine, currentSlice, maxSlice, store]);

  useEffect(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, [store.plane, store.workspace, activeCase?.case_id]);

  useEffect(() => {
    if (!activeCase || store.workspace !== "4-Panel MPR") return;
    const timer = window.setTimeout(() => {
      void api<MPR>(`/viewer/${encodeURIComponent(activeCase.case_id)}/mpr?z=${store.position.z}&y=${store.position.y}&x=${store.position.x}`).then((value) => {
        setMprLocal(value);
      }).catch(() => undefined);
    }, 90);
    return () => window.clearTimeout(timer);
  }, [activeCase, store.position.x, store.position.y, store.position.z, store.workspace, store.windowLevel, store.windowWidth]);

  const [mprLocal, setMprLocal] = useState<MPR | null>(mpr);
  useEffect(() => setMprLocal(mpr), [mpr]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target?.tagName === "INPUT" || target?.tagName === "TEXTAREA" || target?.tagName === "SELECT") return;
      switch (event.key.toLowerCase()) {
        case "w": setWindowOpen((value) => !value); break;
        case "z": setZoom((value) => Math.min(5, value + 0.2)); break;
        case "p": setToast({ kind: "warn", text: "Pan mode is the default pointer drag interaction in the 2D viewer." }); break;
        case "r": setZoom(1); setPan({ x: 0, y: 0 }); break;
        case "3": store.set({ workspace: "3D Reconstruction" }); break;
        case "1": store.set({ plane: "axial", workspace: "2D Diagnostic" }); break;
        case "2": store.set({ plane: "sagittal", workspace: "2D Diagnostic" }); break;
        case "4": store.set({ plane: "coronal", workspace: "2D Diagnostic" }); break;
        case " ": event.preventDefault(); setCine((value) => !value); break;
        default: break;
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [setToast, store]);

  function changePlane(plane: Plane) {
    store.set({ plane, workspace: "2D Diagnostic" });
  }

  async function exportReport() {
    if (!activeCase) return;
    try {
      const report = await api<Record<string, unknown>>("/reports", { method: "POST", body: JSON.stringify({ case_id: activeCase.case_id, user_observations: "" }) });
      const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `medaxis-report-${activeCase.case_id}.json`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setToast({ kind: "good", text: "Structured report JSON exported with QC and provenance." });
    } catch (error) {
      setToast({ kind: "bad", text: error instanceof Error ? error.message : "Report export failed." });
    }
  }

  async function exportDicomSeg() {
    if (!activeCase) return;
    try {
      await downloadEndpoint(`/export/seg/${encodeURIComponent(activeCase.case_id)}?structure=spleen`, `medaxis-${activeCase.case_id}-seg.dcm`);
      setToast({ kind: "good", text: "DICOM SEG exported from the compatible source series and selected mask." });
    } catch (error) {
      setToast({ kind: "bad", text: error instanceof Error ? error.message : "DICOM SEG export failed." });
    }
  }

  async function exportDicomSr() {
    if (!activeCase) return;
    try {
      await downloadEndpoint(`/export/sr/${encodeURIComponent(activeCase.case_id)}`, `medaxis-${activeCase.case_id}-sr.dcm`);
      setToast({ kind: "good", text: "DICOM SR exported from source evidence and derived measurements." });
    } catch (error) {
      setToast({ kind: "bad", text: error instanceof Error ? error.message : "DICOM SR export failed." });
    }
  }

  return (
    <motion.section initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex h-screen flex-col bg-[#070a0e]">
      <header className="z-20 flex h-12 items-center border-b border-slate-800/90 bg-[#080c11]/95 px-2">
        <div className="flex items-center gap-2 pr-2"><IconButton label="Home" onClick={onHome}><ArrowLeft size={15} /></IconButton><div className="hidden pl-1 sm:block"><div className="text-[9px] font-semibold uppercase tracking-[.22em] text-slate-300">MEDAXIS 3D</div><div className="text-[8px] text-slate-600">Research Imaging Workstation</div></div></div>
        <div className="ml-2 hidden min-w-0 flex-1 items-center gap-2 md:flex"><div className="h-5 w-px bg-slate-800" /><div className="truncate text-[11px] text-slate-300">{activeCase?.study?.study_description ?? activeCase?.study?.body_region ?? "No study loaded"}</div><Badge tone={activeCase?.status === "DEMO DATA" ? "warn" : activeCase ? "good" : "neutral"}>{activeCase?.status ?? "EMPTY"}</Badge></div>
        <div className="ml-auto flex items-center gap-1">
          <ModeSelect value={store.mode} onChange={(mode) => store.set({ mode })} />
          <WorkspaceSelect value={store.workspace} onChange={(workspace) => store.set({ workspace })} />
          <IconButton label="Refresh derived analysis" onClick={refresh}><RefreshCw size={15} /></IconButton>
          <IconButton label="Dataset & AI Analytics" onClick={onAnalytics}><BarChart3 size={15} /></IconButton>
          <IconButton label="Cases" onClick={onOpenCases}><Database size={15} /></IconButton>
          <IconButton label="Settings" onClick={onSettings}><Settings size={15} /></IconButton>
        </div>
      </header>

      <div className="workstation-grid min-h-0 flex-1 grid relative" style={{ "--left-panel": store.panelLeft ? "244px" : "0px", "--right-panel": store.panelRight ? "310px" : "0px" } as React.CSSProperties}>
        <aside data-open={store.panelLeft} className="workstation-left overflow-hidden border-r border-slate-800/90 bg-[#0a0f14]">{store.panelLeft ? <LeftPanel activeCase={activeCase} cases={cases} onOpenCases={onOpenCases} onImport={onImport} /> : null}</aside>
        <section className="min-w-0 overflow-hidden bg-[#05080c]">
          {!activeCase ? <EmptyState onDemo={onDemo} onImport={onImport} /> : (
            <Viewer
              activeCase={activeCase}
              imageSrc={imageSrc}
              workspace={store.workspace}
              plane={store.plane}
              currentSlice={currentSlice}
              maxSlice={maxSlice}
              mpr={mprLocal}
              surface={surface}
              measurements={measurements}
              qc={qc}
              windowOpen={windowOpen}
              onWindowOpen={setWindowOpen}
              cine={cine}
              onCine={setCine}
              zoom={zoom}
              onZoom={setZoom}
              pan={pan}
              onPan={setPan}
              onPlane={changePlane}
              onSlice={store.setSlice}
              onWorkspace={(workspace) => store.set({ workspace })}
              setToast={setToast}
              onExport={exportReport}
              onExportSeg={exportDicomSeg}
              onExportSr={exportDicomSr}
            />
          )}
        </section>
        <aside data-open={store.panelRight} className="workstation-right overflow-y-auto border-l border-slate-800/90 bg-[#0a0f14]">{store.panelRight ? <RightPanel activeCase={activeCase} measurements={measurements} surface={surface} models={models} qc={qc} diagnostics={diagnostics} onExport={exportReport} onExportSeg={exportDicomSeg} onExportSr={exportDicomSr} setToast={setToast} /> : null}</aside>
      </div>

      <footer className="flex h-8 items-center justify-between border-t border-slate-800/90 bg-[#080c11] px-3 text-[9px] uppercase tracking-[.11em] text-slate-600">
        <div className="flex items-center gap-4"><span>Created By: <span className="text-slate-400">Ruthwik Goparaju</span></span><span className="hidden sm:inline">Research / Educational Use</span></div>
        <div className="flex items-center gap-3"><span className={backendOnline ? "text-emerald-400" : "text-amber-400"}>{backendOnline ? "BACKEND ONLINE" : "BACKEND OFFLINE"}</span><span>{loadingCase ? "PROCESSING" : diagnostics?.database ?? "LOCAL MODE"}</span><span>v4.1.1</span></div>
      </footer>
    </motion.section>
  );
}

function ModeSelect({ value, onChange }: { value: Mode; onChange: (value: Mode) => void }) {
  return <select aria-label="Workstation mode" value={value} onChange={(event) => onChange(event.target.value as Mode)} className="hidden h-8 border border-slate-800 bg-slate-950 px-2 text-[10px] text-slate-400 outline-none sm:block">{MODES.map((item) => <option key={item} value={item}>{item}</option>)}</select>;
}

function WorkspaceSelect({ value, onChange }: { value: Workspace; onChange: (value: Workspace) => void }) {
  return <select aria-label="Workspace" value={value} onChange={(event) => onChange(event.target.value as Workspace)} className="hidden h-8 max-w-[170px] border border-slate-800 bg-slate-950 px-2 text-[10px] text-slate-400 outline-none lg:block">{WORKSPACES.map((item) => <option key={item} value={item}>{item}</option>)}</select>;
}

function LeftPanel(props: { activeCase: CaseRecord | null; cases: CaseRecord[]; onOpenCases: () => void; onImport: () => void }) {
  const recent = props.cases.slice(0, 5);
  return <div className="h-full overflow-y-auto">
    <Section title="Study Navigator" action={<button onClick={props.onOpenCases} className="text-cyan-300 hover:text-cyan-100">View</button>}>
      <div className="space-y-1"><button onClick={props.onImport} className="flex w-full items-center gap-2 rounded-md border border-slate-800 bg-slate-950/70 p-2 text-left text-xs text-slate-300 hover:border-slate-700"><Upload size={14} className="text-cyan-300" /><span>Import study</span></button><button onClick={props.onOpenCases} className="flex w-full items-center gap-2 rounded-md border border-slate-800 bg-slate-950/40 p-2 text-left text-xs text-slate-400"><Search size={14} /><span>Search cases</span></button></div>
    </Section>
    <Section title="Active Case">
      {props.activeCase ? <div className="space-y-2 rounded-lg border border-slate-800 bg-slate-950/50 p-2.5"><div className="flex items-start justify-between gap-2"><div className="min-w-0"><div className="truncate text-xs font-medium text-slate-100">{props.activeCase.study?.patient_name ?? "Unknown patient"}</div><div className="mono mt-0.5 text-[9px] text-slate-600">{props.activeCase.case_id}</div></div><Badge tone={props.activeCase.status === "DEMO DATA" ? "warn" : "good"}>{props.activeCase.status}</Badge></div><div className="grid grid-cols-2 gap-1.5 pt-1"><MiniKV k="Modality" v={props.activeCase.summary?.modality ?? "—"} /><MiniKV k="Source" v={props.activeCase.summary?.source_type ?? "—"} /><MiniKV k="Matrix" v={(props.activeCase.summary?.volume_dimensions ?? []).slice(0, 2).join(" × ") || "—"} /><MiniKV k="Slices" v={String(props.activeCase.summary?.volume_dimensions?.[2] ?? "—")} /></div></div> : <div className="text-xs text-slate-600">No case loaded.</div>}
    </Section>
    <Section title="Recent Studies"><div className="space-y-1">{recent.length ? recent.map((item) => <div key={item.case_id} className="rounded-md border border-slate-900 bg-slate-950/40 px-2.5 py-2"><div className="truncate text-[10px] text-slate-300">{item.study?.study_description ?? item.case_id}</div><div className="mt-1 flex justify-between text-[9px] text-slate-600"><span>{item.study?.modality ?? "—"}</span><span>{item.status}</span></div></div>) : <div className="text-[10px] text-slate-600">No recent cases.</div>}</div></Section>
    <Section title="Keyboard"><div className="grid grid-cols-2 gap-1.5">{[["W", "Window/Level"], ["Z", "Zoom"], ["P", "Pan"], ["R", "Reset"], ["3", "3D"], ["Space", "Cine"]].map(([key, label]) => <div key={key} className="flex items-center gap-2 rounded border border-slate-900 bg-slate-950/35 px-2 py-1.5"><kbd className="mono rounded border border-slate-800 bg-slate-900 px-1 text-[9px] text-slate-400">{key}</kbd><span className="text-[9px] text-slate-600">{label}</span></div>)}</div></Section>
    <Section title="Data Integrity"><HelpRow icon={ShieldCheck} label="Source provenance" value="tracked" /><HelpRow icon={Info} label="Synthetic data" value={props.activeCase?.status === "DEMO DATA" ? "YES" : "NO"} /><HelpRow icon={Archive} label="Audit trail" value="enabled" /></Section>
  </div>;
}

function MiniKV({ k, v }: { k: string; v: string }) { return <div className="rounded border border-slate-900 bg-slate-950/55 p-1.5"><div className="text-[8px] uppercase tracking-[.12em] text-slate-600">{k}</div><div className="mono mt-0.5 truncate text-[10px] text-slate-300">{v}</div></div>; }

function Viewer(props: {
  activeCase: CaseRecord;
  imageSrc: string;
  workspace: Workspace;
  plane: Plane;
  currentSlice: number;
  maxSlice: number;
  mpr: MPR | null;
  surface: Surface | null;
  measurements: Measurements | null;
  qc: QC | null;
  windowOpen: boolean;
  onWindowOpen: (value: boolean) => void;
  cine: boolean;
  onCine: (value: boolean) => void;
  zoom: number;
  onZoom: React.Dispatch<React.SetStateAction<number>>;
  pan: { x: number; y: number };
  onPan: React.Dispatch<React.SetStateAction<{ x: number; y: number }>>;
  onPlane: (plane: Plane) => void;
  onSlice: (index: number) => void;
  onWorkspace: (workspace: Workspace) => void;
  setToast: React.Dispatch<React.SetStateAction<Toast | null>>;
  onExport: () => void;
  onExportSeg: () => void;
  onExportSr: () => void;
}) {
  return <div className="flex h-full min-h-0 flex-col">
    <div className="flex min-h-10 shrink-0 flex-wrap items-center justify-between gap-2 border-b border-slate-800/70 px-2 py-1.5">
      <div className="flex items-center gap-1"><IconButton label="Toggle left panel" onClick={() => useAppStore.getState().set({ panelLeft: !useAppStore.getState().panelLeft })}><Menu size={15} /></IconButton>{(["axial", "sagittal", "coronal"] as Plane[]).map((plane) => <button key={plane} onClick={() => props.onPlane(plane)} className={`h-8 rounded px-2 text-[10px] uppercase tracking-[.1em] ${props.plane === plane ? "bg-cyan-300/10 text-cyan-100" : "text-slate-500 hover:text-slate-200"}`}>{plane}</button>)}<button onClick={() => props.onWorkspace("4-Panel MPR")} className={`ml-1 inline-flex h-8 items-center gap-1 rounded px-2 text-[10px] ${props.workspace === "4-Panel MPR" ? "bg-cyan-300/10 text-cyan-100" : "text-slate-500"}`}><Grid2X2 size={13} />MPR</button></div>
      <div className="flex items-center gap-1"><button onClick={() => props.onWindowOpen(!props.windowOpen)} className={`h-8 rounded border px-2 text-[10px] ${props.windowOpen ? "border-cyan-400/20 bg-cyan-400/10 text-cyan-100" : "border-slate-800 text-slate-500"}`}>W/L</button><button onClick={() => props.onCine(!props.cine)} className={`h-8 rounded border px-2 text-[10px] ${props.cine ? "border-cyan-400/20 bg-cyan-400/10 text-cyan-100" : "border-slate-800 text-slate-500"}`}>{props.cine ? "Pause" : "Cine"}</button><IconButton label="Reset view" onClick={() => { props.onZoom(1); props.onPan({ x: 0, y: 0 }); }}><Maximize2 size={14} /></IconButton><IconButton label="Toggle right panel" onClick={() => useAppStore.getState().set({ panelRight: !useAppStore.getState().panelRight })}><SlidersHorizontal size={14} /></IconButton></div>
    </div>
    <AnimatePresence>{props.windowOpen ? <WindowLevelControls activeCase={props.activeCase} onClose={() => props.onWindowOpen(false)} /> : null}</AnimatePresence>
    <div className="min-h-0 flex-1">{props.workspace === "4-Panel MPR" ? <MPRViewer mpr={props.mpr} dimensions={props.activeCase?.summary?.volume_dimensions ?? [1, 1, 1]} onPosition={(patch) => { const current = useAppStore.getState().position; useAppStore.getState().set({ position: { ...current, ...patch } }); }} /> : props.workspace === "3D Reconstruction" ? <SurfaceViewer surface={props.surface} activeCase={props.activeCase} setToast={props.setToast} /> : props.workspace === "AI Analysis" ? <WorkspaceNotice title="Dataset & AI Analytics" badge="OPEN ANALYTICS SUITE" message="Use the Analytics button for MONAI model management, research radiomics, validation, cardiac/prostate analysis, PI-RADS worksheet, DICOM SEG/SR, RBAC, PostgreSQL/S3 status, and cross-modality synthesis." /> : props.workspace === "Comparison" ? <WorkspaceNotice title="Longitudinal Comparison" badge="USE ANALYTICS SUITE" message="Select two or more compatible studies from Dataset & AI Analytics → Segmentation & metrics to compare metadata and later attach compatible measurements." /> : props.workspace === "Reporting" ? <ReportingWorkspace activeCase={props.activeCase} measurements={props.measurements} qc={props.qc} onExport={props.onExport} onExportSeg={props.onExportSeg} onExportSr={props.onExportSr} /> : props.workspace === "Quantitative Analysis" ? <QuantitativeWorkspace activeCase={props.activeCase} measurements={props.measurements} /> : <SingleViewer {...props} />}</div>
    <div className="h-16 shrink-0 border-t border-slate-800/80 bg-[#080c11] px-3 py-2"><div className="flex items-center justify-between text-[9px] uppercase tracking-[.13em] text-slate-600"><span>Slice navigator</span><span className="mono text-slate-400">{Math.min(props.currentSlice, props.maxSlice) + 1} / {props.maxSlice + 1}</span></div><input aria-label="Slice" type="range" min={0} max={Math.max(0, props.maxSlice)} value={Math.min(props.currentSlice, props.maxSlice)} onChange={(event) => props.onSlice(Number(event.target.value))} className="mt-2 w-full accent-cyan-300" /></div>
  </div>;
}

function WorkspaceNotice({ title, badge, message }: { title: string; badge: string; message: string }) {
  return <div className="grid h-full place-items-center bg-[#020508] p-8 text-center scan-grid"><div className="max-w-xl rounded-2xl border border-slate-800 bg-[#0a0f14]/90 p-8 shadow-2xl"><div className="text-[10px] font-semibold uppercase tracking-[.2em] text-slate-500">{title}</div><div className="mt-4 inline-flex rounded border border-amber-500/20 bg-amber-500/10 px-2 py-1 text-[9px] uppercase tracking-[.14em] text-amber-200">{badge}</div><p className="mt-4 text-sm leading-6 text-slate-500">{message}</p></div></div>;
}

function QuantitativeWorkspace({ activeCase, measurements }: { activeCase: CaseRecord | null; measurements: Measurements | null }) {
  return <div className="h-full overflow-auto bg-[#020508] p-5 scan-grid"><div className="mx-auto max-w-3xl rounded-2xl border border-slate-800 bg-[#0a0f14]/95 p-5"><div className="flex items-start justify-between gap-4"><div><div className="text-[10px] uppercase tracking-[.18em] text-cyan-300/70">Quantitative Analysis</div><h2 className="mt-2 text-xl font-semibold text-slate-100">Source-derived measurements</h2></div><Badge tone="accent">ACTUAL SOURCE DATA</Badge></div><div className="mt-5 grid gap-2 sm:grid-cols-3"><Metric label="Mean" value={measurements ? measurements.mean_intensity.toFixed(3) : "—"} unit={measurements?.units === "HU" ? "HU" : "source units"} /><Metric label="Median" value={measurements ? measurements.median_intensity.toFixed(3) : "—"} unit={measurements?.units === "HU" ? "HU" : "source units"} /><Metric label="Area" value={measurements ? measurements.area_mm2.toFixed(3) : "—"} unit="mm²" /></div><div className="mt-4 rounded border border-slate-900 bg-slate-950/50 p-3 text-[10px] leading-5 text-slate-500">{measurements?.method ?? "Measurement unavailable — required imaging metadata or validated calibration is missing."}</div><div className="mt-4 grid gap-2 sm:grid-cols-2 text-[10px] text-slate-500"><div>Case: <span className="mono text-slate-300">{activeCase?.case_id ?? "—"}</span></div><div>Spacing: <span className="mono text-slate-300">{(measurements?.voxel_spacing_mm ?? []).map((v) => v.toFixed(3)).join(" × ") || "—"} mm</span></div></div></div></div>;
}

function ReportingWorkspace({ activeCase, measurements, qc, onExport, onExportSeg, onExportSr }: { activeCase: CaseRecord | null; measurements: Measurements | null; qc: QC | null; onExport: () => void; onExportSeg: () => void; onExportSr: () => void }) {
  return <div className="h-full overflow-auto bg-[#020508] p-5 scan-grid"><div className="mx-auto max-w-3xl rounded-2xl border border-slate-800 bg-[#0a0f14]/95 p-5"><div className="flex items-center justify-between gap-4 border-b border-slate-800 pb-4"><div><div className="text-[10px] uppercase tracking-[.18em] text-cyan-300/70">MEDAXIS 3D</div><h2 className="mt-2 text-xl font-semibold text-slate-100">Structured Imaging Report</h2></div><Badge tone="warn">RESEARCH / EDUCATIONAL</Badge></div><div className="mt-5 grid gap-3 sm:grid-cols-2"><MiniKV k="Case" v={activeCase?.case_id ?? "—"} /><MiniKV k="Study" v={activeCase?.study?.study_description ?? "—"} /><MiniKV k="Modality" v={activeCase?.summary?.modality ?? "—"} /><MiniKV k="QC" v={qc?.overall ?? "—"} /></div><div className="mt-4 rounded-lg border border-slate-900 bg-slate-950/50 p-3 text-[10px] leading-5 text-slate-500">The report contains only stored metadata, QC, source-derived measurements, provenance, limitations, and user-entered observations. No unsupported diagnosis is generated. DICOM SEG/SR exports remain subject to source-geometry compatibility and deployment validation.</div><div className="mt-4 flex flex-wrap gap-2"><button onClick={onExport} className="inline-flex items-center gap-2 rounded-md border border-cyan-400/20 bg-cyan-400/10 px-3 py-2 text-[10px] text-cyan-100"><Download size={13} />Export structured JSON report</button><button onClick={onExportSeg} className="inline-flex items-center gap-2 rounded-md border border-slate-800 px-3 py-2 text-[10px] text-slate-300"><FileImage size={13} />DICOM SEG</button><button onClick={onExportSr} className="inline-flex items-center gap-2 rounded-md border border-slate-800 px-3 py-2 text-[10px] text-slate-300"><FileCheck2 size={13} />DICOM SR</button></div></div></div>;
}

function WindowLevelControls({ activeCase, onClose }: { activeCase: CaseRecord; onClose: () => void }) {
  const store = useAppStore();
  const presets = activeCase.summary?.modality === "CT" ? [{ name: "Brain", wl: 40, ww: 80 }, { name: "Bone", wl: 300, ww: 1500 }, { name: "Lung", wl: -600, ww: 1600 }, { name: "Soft", wl: 60, ww: 400 }] : [];
  return <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} className="border-b border-slate-800 bg-[#080c11] px-3 py-2"><div className="flex flex-wrap items-end gap-2"><div><div className="text-[9px] uppercase tracking-[.14em] text-slate-600">Window Level</div><input type="number" value={store.windowLevel ?? ""} placeholder="Auto" onChange={(event) => store.set({ windowLevel: event.target.value === "" ? null : Number(event.target.value) })} className="mt-1 w-24 rounded border border-slate-800 bg-slate-950 px-2 py-1.5 text-[10px] text-slate-300" /></div><div><div className="text-[9px] uppercase tracking-[.14em] text-slate-600">Window Width</div><input type="number" min={1} value={store.windowWidth ?? ""} placeholder="Auto" onChange={(event) => store.set({ windowWidth: event.target.value === "" ? null : Math.max(1, Number(event.target.value)) })} className="mt-1 w-24 rounded border border-slate-800 bg-slate-950 px-2 py-1.5 text-[10px] text-slate-300" /></div>{presets.map((preset) => <button key={preset.name} onClick={() => store.set({ windowLevel: preset.wl, windowWidth: preset.ww })} className="h-8 rounded border border-slate-800 px-2 text-[10px] text-slate-500 hover:text-slate-200">{preset.name}</button>)}<button onClick={() => store.set({ windowLevel: null, windowWidth: null })} className="h-8 rounded border border-slate-800 px-2 text-[10px] text-slate-500 hover:text-slate-200">Auto</button><button onClick={onClose} className="ml-auto h-8 rounded border border-slate-800 px-2 text-[10px] text-slate-600 hover:text-slate-300">Close</button></div></motion.div>;
}

function SingleViewer(props: any) {
  const start = useRef<{ x: number; y: number } | null>(null);
  return <div className="relative h-full overflow-hidden bg-[#020508] scan-grid"><div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(22,33,43,.5),transparent_55%)]" /><div className="absolute left-3 top-3 z-10 flex flex-wrap gap-1.5"><Badge tone="accent">{props.activeCase.summary?.modality ?? "N/A"}</Badge><Badge>{props.activeCase.status}</Badge><Badge>{props.activeCase.summary?.source_type ?? "SOURCE"}</Badge></div><div className="absolute right-3 top-3 z-10 text-right"><div className="mono text-[10px] text-slate-300">{props.plane.toUpperCase()}</div><div className="mono mt-1 text-[9px] text-slate-600">SLICE {String(props.currentSlice + 1).padStart(3, "0")}</div></div><div className="absolute inset-0 grid place-items-center p-10"><div className="relative max-h-full max-w-full overflow-hidden" onWheel={(event) => { event.preventDefault(); props.onZoom((value: number) => Math.max(0.5, Math.min(5, value + (event.deltaY < 0 ? 0.12 : -0.12)))); }} onPointerDown={(event) => { event.currentTarget.setPointerCapture(event.pointerId); start.current = { x: event.clientX - props.pan.x, y: event.clientY - props.pan.y }; }} onPointerMove={(event) => { if (start.current) props.onPan({ x: event.clientX - start.current.x, y: event.clientY - start.current.y }); }} onPointerUp={() => { start.current = null; }} onPointerCancel={() => { start.current = null; }}><img draggable={false} alt="Medical image slice from source dataset" src={props.imageSrc} className="max-h-[calc(100vh-185px)] max-w-[90%] select-none object-contain" style={{ transform: `translate(${props.pan.x}px,${props.pan.y}px) scale(${props.zoom})` }} /></div></div><div className="absolute bottom-3 left-3 right-3 z-10 flex items-end justify-between gap-4"><div className="space-y-0.5 text-[9px] text-slate-500"><div>Pixel spacing: <span className="mono text-slate-300">{(props.activeCase.summary?.pixel_spacing_mm ?? []).map((value: number) => value.toFixed(3)).join(" × ") || "N/A"} mm</span></div><div>Slice thickness: <span className="mono text-slate-300">{props.activeCase.summary?.slice_thickness_mm ? `${Number(props.activeCase.summary.slice_thickness_mm).toFixed(3)} mm` : "N/A"}</span></div></div><div className="rounded border border-slate-800 bg-black/55 px-2 py-1.5 text-[9px] text-slate-500">Scroll = zoom · Drag = pan</div></div></div>;
}

function MPRViewer({ mpr, dimensions, onPosition }: { mpr: MPR | null; dimensions: number[]; onPosition: (patch: Partial<MPR["position"]>) => void }) {
  if (!mpr) return <div className="grid h-full place-items-center text-xs text-slate-600">MPR unavailable — source volume could not be reconstructed.</div>;
  const [xDim, yDim, zDim] = dimensions;
  const clampPercent = (value: number, size: number) => size > 1 ? Math.max(0, Math.min(100, (value / (size - 1)) * 100)) : 50;
  const crosshair = (plane: Plane) => {
    if (plane === "axial") return { left: clampPercent(mpr.position.x, xDim), top: 100 - clampPercent(mpr.position.y, yDim) };
    if (plane === "sagittal") return { left: clampPercent(mpr.position.y, yDim), top: 100 - clampPercent(mpr.position.z, zDim) };
    return { left: clampPercent(mpr.position.x, xDim), top: 100 - clampPercent(mpr.position.z, zDim) };
  };
  const tiles: Array<[Plane, string, number, number]> = [["axial", mpr.axial, xDim, yDim], ["sagittal", mpr.sagittal, yDim, zDim], ["coronal", mpr.coronal, xDim, zDim]];
  function clickToPosition(event: React.MouseEvent<HTMLDivElement>, plane: Plane, imageWidth: number, imageHeight: number) {
    const rect = event.currentTarget.getBoundingClientRect();
    const imageRatio = imageWidth / Math.max(1, imageHeight);
    const containerRatio = rect.width / Math.max(1, rect.height);
    let left = 0; let top = 0; let width = rect.width; let height = rect.height;
    if (containerRatio > imageRatio) { width = rect.height * imageRatio; left = (rect.width - width) / 2; }
    else { height = rect.width / imageRatio; top = (rect.height - height) / 2; }
    const u = Math.max(0, Math.min(1, (event.clientX - rect.left - left) / Math.max(1, width)));
    const v = Math.max(0, Math.min(1, (event.clientY - rect.top - top) / Math.max(1, height)));
    const horizontal = Math.round(u * Math.max(0, imageWidth - 1));
    const vertical = Math.round((1 - v) * Math.max(0, imageHeight - 1));
    if (plane === "axial") onPosition({ x: horizontal, y: vertical });
    if (plane === "sagittal") onPosition({ y: horizontal, z: vertical });
    if (plane === "coronal") onPosition({ x: horizontal, z: vertical });
  }
  return <div className="grid h-full grid-cols-2 grid-rows-2 gap-px bg-slate-900 p-px">{tiles.map(([plane, image, width, height]) => { const point = crosshair(plane); return <div key={plane} className="relative cursor-crosshair bg-[#05080c]" onClick={(event) => clickToPosition(event, plane, width, height)}><img alt={`${plane} MPR`} src={`data:image/png;base64,${image}`} className="h-full w-full object-contain" /><div className="absolute left-2 top-2 rounded bg-black/55 px-2 py-1 text-[9px] uppercase tracking-[.16em] text-slate-400">{plane}</div><div className="pointer-events-none absolute inset-0"><span className="absolute inset-y-0 w-px bg-cyan-300/55" style={{ left: `${point.left}%` }} /><span className="absolute inset-x-0 h-px bg-cyan-300/55" style={{ top: `${point.top}%` }} /><span className="absolute size-2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-cyan-200" style={{ left: `${point.left}%`, top: `${point.top}%` }} /></div></div>; })}<div className="grid place-items-center bg-[#070a0e]"><div className="text-center"><div className="text-xs text-slate-400">Synchronized MPR</div><div className="mt-1 mono text-[10px] text-slate-600">Z {mpr.position.z} · Y {mpr.position.y} · X {mpr.position.x}</div><div className="mt-2 text-[9px] text-slate-600">Click a plane to move the shared crosshair</div></div></div></div>;
}

function SurfaceViewer({ activeCase, surface, setToast }: { activeCase: CaseRecord; surface: Surface | null; setToast: React.Dispatch<React.SetStateAction<Toast | null>> }) {
  const [opacity, setOpacity] = useState(0.84);
  const [wireframe, setWireframe] = useState(false);
  const [clipX, setClipX] = useState(1);
  const [clipY, setClipY] = useState(1);
  const [clipZ, setClipZ] = useState(1);
  const geometry = surface?.faces?.length ? surface : null;
  const prepared = useMemo(() => {
    if (!geometry?.vertices?.length) return null;
    const vertices = geometry.vertices;
    const min = [Infinity, Infinity, Infinity];
    const max = [-Infinity, -Infinity, -Infinity];
    vertices.forEach((v) => { for (let axis = 0; axis < 3; axis += 1) { min[axis] = Math.min(min[axis], Number(v[axis] ?? 0)); max[axis] = Math.max(max[axis], Number(v[axis] ?? 0)); } });
    const center = min.map((value, axis) => (value + max[axis]) / 2);
    const centered = new Float32Array(vertices.length * 3);
    vertices.forEach((v, index) => { centered[index * 3] = Number(v[0] ?? 0) - center[0]; centered[index * 3 + 1] = Number(v[1] ?? 0) - center[1]; centered[index * 3 + 2] = Number(v[2] ?? 0) - center[2]; });
    const centeredMin = min.map((value, axis) => value - center[axis]);
    const centeredMax = max.map((value, axis) => value - center[axis]);
    const maxDim = Math.max(max[0] - min[0], max[1] - min[1], max[2] - min[2], 1);
    const cameraDistance = maxDim * 1.8;
    return { centered, faces: new Uint32Array(geometry.faces.flat()), cameraDistance, min: centeredMin, max: centeredMax };
  }, [geometry]);
  if (!surface || surface.status !== "AVAILABLE" || !prepared) {
    return <div className="grid h-full place-items-center bg-[#020508] p-8 text-center"><div><Badge tone="warn">3D UNAVAILABLE</Badge><div className="mt-3 max-w-md text-xs text-slate-400">{surface?.method ?? "A source-derived 3D surface could not be reconstructed from the current dataset."}</div></div></div>;
  }
  const cameraDistance = prepared.cameraDistance;
  const clipPlanes = useMemo(() => [
    new THREE.Plane(new THREE.Vector3(-1, 0, 0), prepared.min[0] + (prepared.max[0] - prepared.min[0]) * clipX),
    new THREE.Plane(new THREE.Vector3(0, -1, 0), prepared.min[1] + (prepared.max[1] - prepared.min[1]) * clipY),
    new THREE.Plane(new THREE.Vector3(0, 0, -1), prepared.min[2] + (prepared.max[2] - prepared.min[2]) * clipZ),
  ], [prepared.min, prepared.max, clipX, clipY, clipZ]);
  return <div className="relative h-full overflow-hidden bg-[#020508] scan-grid">
    <div className="absolute left-3 top-3 z-10 flex gap-1.5"><Badge tone="accent">3D RECONSTRUCTION</Badge><Badge>{activeCase.summary?.modality ?? "N/A"}</Badge></div>
    <div className="absolute right-3 top-3 z-10 text-right"><div className="mono text-[10px] text-slate-300">WEBGL SURFACE</div><div className="mono mt-1 text-[9px] text-slate-600">SOURCE-DERIVED</div></div>
    <div className="absolute left-3 bottom-14 z-10 w-64 rounded-lg border border-slate-800 bg-black/60 p-3 backdrop-blur-sm">
      <div className="mb-2 flex items-center justify-between text-[9px] uppercase tracking-[.14em] text-slate-600"><span>3D inspection</span><button onClick={() => { setClipX(1); setClipY(1); setClipZ(1); setOpacity(0.84); setWireframe(false); }} className="text-slate-400 hover:text-white">Reset</button></div>
      <div className="space-y-2">
        <label className="block text-[9px] text-slate-500">Opacity <input aria-label="3D mesh opacity" type="range" min="0.15" max="1" step="0.01" value={opacity} onChange={(e) => setOpacity(Number(e.target.value))} className="mt-1 w-full" /></label>
        <label className="block text-[9px] text-slate-500">Clip X <input aria-label="3D clip X" type="range" min="0" max="1" step="0.01" value={clipX} onChange={(e) => setClipX(Number(e.target.value))} className="mt-1 w-full" /></label>
        <label className="block text-[9px] text-slate-500">Clip Y <input aria-label="3D clip Y" type="range" min="0" max="1" step="0.01" value={clipY} onChange={(e) => setClipY(Number(e.target.value))} className="mt-1 w-full" /></label>
        <label className="block text-[9px] text-slate-500">Clip Z <input aria-label="3D clip Z" type="range" min="0" max="1" step="0.01" value={clipZ} onChange={(e) => setClipZ(Number(e.target.value))} className="mt-1 w-full" /></label>
        <button onClick={() => setWireframe((v) => !v)} className={`w-full rounded border px-2 py-1.5 text-[9px] ${wireframe ? "border-cyan-400/25 bg-cyan-400/10 text-cyan-100" : "border-slate-800 text-slate-500"}`}>{wireframe ? "Wireframe ON" : "Wireframe OFF"}</button>
      </div>
    </div>
    <Canvas camera={{ position: [cameraDistance, cameraDistance * 0.82, cameraDistance * 1.1], fov: 42, near: 0.1, far: cameraDistance * 8 }} dpr={[1, 1.5]} gl={{ antialias: true, localClippingEnabled: true }}>
      <color attach="background" args={["#020508"]} />
      <ambientLight intensity={1.15} />
      <directionalLight position={[3, 4, 5]} intensity={2.1} />
      <directionalLight position={[-4, -2, 3]} intensity={0.8} />
      <mesh>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[prepared.centered, 3]} />
          <bufferAttribute attach="index" args={[prepared.faces, 1]} />
        </bufferGeometry>
        <meshStandardMaterial color="#9ae7ff" roughness={0.58} metalness={0.08} side={THREE.DoubleSide} transparent opacity={opacity} wireframe={wireframe} clippingPlanes={clipPlanes} clipIntersection={false} />
      </mesh>
      <OrbitControls enableDamping dampingFactor={0.09} minDistance={Math.max(1, cameraDistance * 0.25)} maxDistance={cameraDistance * 5} />
    </Canvas>
    <div className="absolute bottom-3 left-3 right-3 z-10 flex items-center justify-between rounded-lg border border-slate-800 bg-black/55 px-3 py-2 text-[9px] text-slate-500">
      <span>{surface.method?.includes("not an anatomical segmentation") ? "Intensity-derived research surface — not anatomical segmentation" : "Marching Cubes surface"}</span>
      <span className="mono text-slate-300">{surface.vertex_count ?? 0} VTX · {surface.triangle_count ?? 0} TRI · {formatNumber(surface.volume_cm3 ?? NaN)} cm³</span>
    </div>
  </div>;
}

function RightPanel(props: { activeCase: CaseRecord | null; measurements: Measurements | null; surface: Surface | null; models: ModelRecord[]; qc: QC | null; diagnostics: Diagnostics | null; onExport: () => void; onExportSeg: () => void; onExportSr: () => void; setToast: React.Dispatch<React.SetStateAction<Toast | null>> }) {
  const [lower, setLower] = useState("50");
  const [upper, setUpper] = useState("150");
  const [thresholdResult, setThresholdResult] = useState<{ volume_cm3: number; mask_voxel_count: number; provenance: { processing_pipeline_version: string } } | null>(null);
  const [running, setRunning] = useState(false);
  useEffect(() => setThresholdResult(null), [props.activeCase?.case_id]);

  async function runThreshold() {
    if (!props.activeCase) return;
    const low = Number(lower);
    const high = Number(upper);
    if (!Number.isFinite(low) || !Number.isFinite(high) || low > high) {
      props.setToast({ kind: "warn", text: "Invalid intensity range — lower must be less than or equal to upper." });
      return;
    }
    setRunning(true);
    try {
      const result = await api<typeof thresholdResult>("/analysis/threshold", { method: "POST", body: JSON.stringify({ case_id: props.activeCase.case_id, lower: low, upper: high, label: "Research Threshold Mask" }) });
      setThresholdResult(result);
    } catch (error) {
      props.setToast({ kind: "bad", text: error instanceof Error ? error.message : "Research segmentation failed." });
    } finally {
      setRunning(false);
    }
  }

  return <div>
    <Section title="Analysis Status"><div className="grid grid-cols-2 gap-1.5"><StatusCard label="QC" value={props.qc?.overall ?? "—"} tone={props.qc?.overall === "PASS" ? "good" : props.qc?.overall === "FAIL" ? "bad" : "warn"} /><StatusCard label="3D Surface" value={props.surface?.status ?? "—"} tone={props.surface?.status === "AVAILABLE" ? "good" : "warn"} /><StatusCard label="AI Models" value="CONFIG REQUIRED" tone="warn" /><StatusCard label="GPU" value={props.diagnostics?.gpu ?? "NOT CLAIMED"} tone="neutral" /></div></Section>
    <Section title="Measurements"><div className="grid gap-1.5"><Metric label={props.measurements?.units === "HU" ? "Mean HU" : "Mean intensity"} value={props.measurements ? props.measurements.mean_intensity.toFixed(3) : "—"} source="Selected plane • actual source pixels" /><Metric label={props.measurements?.units === "HU" ? "Median HU" : "Median intensity"} value={props.measurements ? props.measurements.median_intensity.toFixed(3) : "—"} source="Selected plane • actual source pixels" /><Metric label="Area" value={props.measurements ? props.measurements.area_mm2.toFixed(3) : "—"} unit="mm²" source="Pixel count × source spacing" /></div><div className="mt-2 rounded border border-slate-800 bg-slate-950/45 p-2 text-[9px] leading-4 text-slate-500">{props.measurements?.method ?? "Measurement unavailable — required imaging metadata or validated calibration is missing."}</div></Section>
    <Section title="Research Threshold Segmentation"><div className="space-y-2"><div className="grid grid-cols-2 gap-1.5"><input value={lower} onChange={(event) => setLower(event.target.value)} inputMode="decimal" aria-label="Lower intensity threshold" className="rounded border border-slate-800 bg-slate-950 px-2 py-1.5 text-[10px] text-slate-300 outline-none" placeholder="Lower" /><input value={upper} onChange={(event) => setUpper(event.target.value)} inputMode="decimal" aria-label="Upper intensity threshold" className="rounded border border-slate-800 bg-slate-950 px-2 py-1.5 text-[10px] text-slate-300 outline-none" placeholder="Upper" /></div><button onClick={() => void runThreshold()} disabled={running || !props.activeCase} className="w-full rounded-md border border-cyan-400/20 bg-cyan-400/10 px-2.5 py-2 text-[10px] text-cyan-100 disabled:opacity-50">{running ? "Running…" : "Run threshold mask"}</button>{thresholdResult ? <div className="rounded border border-slate-800 bg-slate-950/55 p-2"><div className="text-[9px] uppercase tracking-[.12em] text-slate-600">Actual data-derived volume</div><div className="mt-1 mono text-sm text-slate-200">{thresholdResult.volume_cm3.toFixed(3)} cm³</div><div className="mt-1 text-[9px] leading-4 text-slate-600">Voxel count: <span className="mono text-slate-400">{thresholdResult.mask_voxel_count}</span><br />Method: {thresholdResult.provenance.processing_pipeline_version}</div></div> : null}</div></Section>
    <Section title="3D Surface Reconstruction"><div className="space-y-2"><div className="grid grid-cols-2 gap-1.5"><Metric label="Vertices" value={props.surface?.vertex_count ?? "—"} /><Metric label="Triangles" value={props.surface?.triangle_count ?? "—"} /><Metric label="Surface area" value={props.surface?.surface_area_mm2 ? props.surface.surface_area_mm2.toFixed(2) : "—"} unit="mm²" /><Metric label="Derived volume" value={props.surface?.volume_cm3 ? props.surface.volume_cm3.toFixed(3) : "—"} unit="cm³" /></div><div className="rounded border border-slate-900 bg-slate-950/45 p-2 text-[9px] leading-4 text-slate-600">{props.surface?.method ?? "Surface reconstruction unavailable."}</div></div></Section>
    <Section title="AI Model Manager"><div className="space-y-1.5">{props.models.map((model) => <div key={model.model_id} className="rounded border border-slate-900 bg-slate-950/45 p-2"><div className="text-[10px] text-slate-300">{model.model_name}</div><div className="mt-1 flex items-center justify-between"><span className="mono text-[9px] text-slate-600">{model.modality} · {model.body_region}</span><Badge tone="warn">{model.status}</Badge></div></div>)}</div></Section>
    <Section title="Quality Control"><div className="space-y-1.5">{(props.qc?.tests ?? []).map((item) => <div key={String(item.test)} className="rounded border border-slate-900 bg-slate-950/45 p-2"><div className="flex items-center justify-between"><span className="text-[10px] text-slate-300">{String(item.test)}</span><Badge tone={item.status === "PASS" ? "good" : item.status === "FAIL" ? "bad" : "warn"}>{String(item.status)}</Badge></div><div className="mt-1 text-[9px] leading-4 text-slate-600">Observed: <span className="mono text-slate-400">{typeof item.observed === "string" ? item.observed : JSON.stringify(item.observed)}</span></div><div className="text-[9px] text-slate-600">Method: {String(item.method)}</div></div>)}</div></Section>
    <Section title="Reporting"><div className="grid gap-1.5"><button onClick={props.onExport} className="inline-flex items-center justify-center gap-2 rounded-md border border-cyan-400/20 bg-cyan-400/10 px-2.5 py-2 text-[10px] text-cyan-100"><Download size={13} />Export structured JSON report</button><button onClick={() => props.setToast({ kind: "warn", text: "PDF report unavailable — a validated server-side PDF renderer is not configured." })} className="inline-flex items-center justify-center gap-2 rounded-md border border-slate-800 px-2.5 py-2 text-[10px] text-slate-500"><FileText size={13} />PDF report</button><div className="grid gap-1.5"><button onClick={props.onExportSeg} className="inline-flex items-center justify-center gap-2 rounded-md border border-cyan-400/20 bg-cyan-400/10 px-2.5 py-2 text-[10px] text-cyan-100"><FileImage size={13} />DICOM SEG</button><button onClick={props.onExportSr} className="inline-flex items-center justify-center gap-2 rounded-md border border-cyan-400/20 bg-cyan-400/10 px-2.5 py-2 text-[10px] text-cyan-100"><FileCheck2 size={13} />DICOM SR</button></div></div></Section>
    <Section title="System"><HelpRow icon={FileClock} label="Case ID" value={props.activeCase?.case_id ?? "—"} /><HelpRow icon={Database} label="Storage" value={props.diagnostics?.database ?? "—"} /><HelpRow icon={ShieldCheck} label="Clinical status" value="RESEARCH ONLY" /></Section>
  </div>;
}

function StatusCard({ label, value, tone }: { label: string; value: string; tone: "good" | "warn" | "neutral" | "bad" }) { return <div className="rounded-lg border border-slate-800 bg-slate-950/55 p-2"><div className="text-[9px] uppercase tracking-[.12em] text-slate-600">{label}</div><div className={`mt-1 text-[10px] ${tone === "good" ? "text-emerald-300" : tone === "bad" ? "text-rose-300" : tone === "warn" ? "text-amber-300" : "text-slate-300"}`}>{value}</div></div>; }

function ImportModal({ onClose, onImport }: { onClose: () => void; onImport: (files: FileList | null, modality: "AUTO" | "CT" | "MRI") => void }) {
  const [drag, setDrag] = useState(false);
  const [modality, setModality] = useState<"AUTO" | "CT" | "MRI">("AUTO");
  const inputRef = useRef<HTMLInputElement | null>(null);
  const submit = (files: FileList | null) => { if (files?.length) onImport(files, modality); };
  return <Modal onClose={onClose} title="Import Imaging Study"><div className="space-y-4">
    <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
      <div className="rounded-lg border border-slate-900 bg-slate-950/40 p-3 text-[10px] leading-4 text-slate-500"><span className="text-slate-300">NIfTI requires a declared modality.</span> DICOM modality is read from source metadata; a conflicting declaration is rejected.</div>
      <label className="text-[9px] uppercase tracking-[.12em] text-slate-600">NIfTI modality<select value={modality} onChange={(e) => setModality(e.target.value as typeof modality)} className="mt-1 h-9 min-w-32 border border-slate-800 bg-slate-950 px-2 text-xs text-slate-300"><option value="AUTO">DICOM / AUTO</option><option value="CT">CT</option><option value="MRI">MRI</option></select></label>
    </div>
    <div role="button" tabIndex={0} aria-label="Import DICOM or NIfTI study" onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); inputRef.current?.click(); } }} onDragOver={(event) => { event.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={(event) => { event.preventDefault(); setDrag(false); submit(event.dataTransfer.files); }} onClick={() => inputRef.current?.click()} className={`grid min-h-52 cursor-pointer place-items-center rounded-xl border border-dashed outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/50 ${drag ? "border-cyan-300/50 bg-cyan-300/[.04]" : "border-slate-700 bg-slate-950/45"} p-8 text-center`}>
      <input ref={inputRef} type="file" multiple hidden accept=".dcm,.nii,.nii.gz,.zip" onChange={(event) => submit(event.target.files)} />
      <div><div className="mx-auto grid size-12 place-items-center rounded-xl border border-slate-800 bg-slate-900/70 text-cyan-200"><Upload size={20} /></div><div className="mt-3 text-sm text-slate-200">Drop DICOM, NIfTI, or DICOM ZIP</div><div className="mt-1 text-[10px] text-slate-600">.dcm · .nii · .nii.gz · .zip</div><div className="mt-2 mono text-[9px] text-slate-700">Declared modality: {modality}</div></div>
    </div>
    <div className="rounded-lg border border-amber-500/15 bg-amber-500/[.04] p-3 text-[10px] leading-4 text-amber-200/80">Mixed series, invalid geometry, unsupported multiframe objects, and malformed archives are rejected rather than silently processed.</div>
  </div></Modal>;
}

function CasesModal({ cases, onClose, onOpen, onDelete, onError }: { cases: CaseRecord[]; onClose: () => void; onOpen: (record: CaseRecord) => void; onDelete: (id: string) => void; onError: (message: string) => void }) {
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return cases;
    return cases.filter((record) => JSON.stringify(record).toLowerCase().includes(needle));
  }, [cases, query]);
  async function remove(id: string) {
    setBusy(id);
    try {
      await api(`/cases/${encodeURIComponent(id)}`, { method: "DELETE" });
      onDelete(id);
    } catch (error) {
      onError(error instanceof Error ? error.message : "Case deletion failed.");
    } finally {
      setBusy(null);
    }
  }
  return <Modal onClose={onClose} title="Case Management"><div className="mb-3 flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-950/55 px-3 py-2"><Search size={14} className="text-slate-600" /><input value={query} onChange={(event) => setQuery(event.target.value)} autoFocus placeholder="Search case ID, modality, study…" className="w-full bg-transparent text-xs outline-none placeholder:text-slate-700" /></div><div className="max-h-[55vh] space-y-1.5 overflow-y-auto">{filtered.length ? filtered.map((record) => <div key={record.case_id} className="rounded-lg border border-slate-900 bg-slate-950/40 p-3"><button onClick={() => onOpen(record)} className="w-full text-left hover:border-slate-700"><div className="flex items-start justify-between gap-4"><div><div className="text-xs text-slate-200">{record.study?.study_description ?? "Unnamed study"}</div><div className="mono mt-1 text-[9px] text-slate-600">{record.case_id}</div></div><Badge tone={record.status === "DEMO DATA" ? "warn" : "good"}>{record.status}</Badge></div><div className="mt-2 grid grid-cols-3 gap-3 text-[9px] text-slate-600"><span>{record.study?.modality ?? "—"}</span><span>{record.study?.body_region ?? "—"}</span><span>{record.summary?.source_type ?? "—"}</span></div></button><div className="mt-2 flex justify-end"><button disabled={busy === record.case_id} onClick={() => void remove(record.case_id)} className="text-[9px] text-rose-300/70 hover:text-rose-200 disabled:opacity-40">{busy === record.case_id ? "Deleting…" : "Delete case"}</button></div></div>) : <div className="py-10 text-center text-xs text-slate-600">No matching cases.</div>}</div></Modal>;
}

function SettingsModal({ onClose }: { onClose: () => void }) {
  const [reduce, setReduce] = useState(() => typeof document !== "undefined" && document.documentElement.dataset.reduceMotion === "true");
  const [high, setHigh] = useState(() => typeof document !== "undefined" && document.documentElement.dataset.highContrast === "true");
  function applyReduce(value: boolean) { setReduce(value); if (typeof document !== "undefined") document.documentElement.dataset.reduceMotion = String(value); }
  function applyHigh(value: boolean) { setHigh(value); if (typeof document !== "undefined") document.documentElement.dataset.highContrast = String(value); }
  return <Modal onClose={onClose} title="Workstation Settings"><div className="grid gap-5 sm:grid-cols-2"><div><div className="mb-2 text-[9px] font-semibold uppercase tracking-[.16em] text-slate-500">Display</div><div className="space-y-1.5"><Toggle label="Reduce motion" value={reduce} set={applyReduce} /><Toggle label="High contrast" value={high} set={applyHigh} /></div></div><div><div className="mb-2 text-[9px] font-semibold uppercase tracking-[.16em] text-slate-500">Privacy / research</div><div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-[10px] leading-5 text-slate-500">This implementation is research/educational. No regulatory, diagnostic, or clinical-validation claim is made. Pixel data may contain burned-in identifiers and requires review before research export.</div></div></div></Modal>;
}

function Toggle({ label, value, set, disabled = false }: { label: string; value: boolean; set: (value: boolean) => void; disabled?: boolean }) { return <button disabled={disabled} onClick={() => set(!value)} className="flex w-full items-center justify-between rounded-lg border border-slate-900 bg-slate-950/45 px-3 py-2 text-left disabled:opacity-50"><span className="text-[10px] text-slate-400">{label}</span><span className={`h-5 w-9 rounded-full p-0.5 ${value ? "bg-cyan-300/30" : "bg-slate-800"}`}><span className={`block size-4 rounded-full transition ${value ? "translate-x-4 bg-cyan-200" : "bg-slate-600"}`} /></span></button>; }

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) { if (event.key === "Escape") onClose(); }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);
  return <motion.div role="dialog" aria-modal="true" aria-label={title} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4 backdrop-blur-sm"><motion.div initial={{ opacity: 0, y: 8, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} className="w-full max-w-2xl rounded-2xl border border-slate-700/80 bg-[#0b1016] p-4 shadow-2xl"><div className="mb-4 flex items-center justify-between"><div><div className="text-sm font-semibold text-slate-100">{title}</div><div className="mt-0.5 text-[9px] uppercase tracking-[.14em] text-slate-600">MedAxis 3D</div></div><IconButton label="Close" onClick={onClose}><X size={15} /></IconButton></div>{children}</motion.div></motion.div>;
}

function ToastView({ toast, onClose }: { toast: Toast; onClose: () => void }) { return <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 8 }} className="fixed bottom-12 right-4 z-[60] flex max-w-md items-start gap-3 rounded-xl border border-slate-700 bg-[#0b1016] p-3 shadow-2xl"><div className="pt-0.5">{toast.kind === "good" ? <ShieldCheck size={15} className="text-emerald-300" /> : toast.kind === "warn" ? <AlertCircle size={15} className="text-amber-300" /> : <X size={15} className="text-rose-300" />}</div><div className="text-[10px] leading-4 text-slate-300">{toast.text}</div><button aria-label="Dismiss notification" onClick={onClose} className="text-slate-600 hover:text-slate-300"><X size={13} /></button></motion.div>; }


function AuthGate({ children }: { children: React.ReactNode }) {
  const [loading, setLoading] = React.useState(true);
  const [required, setRequired] = React.useState(false);
  const [authenticated, setAuthenticated] = React.useState(false);

  React.useEffect(() => {
    let active = true;
    async function bootstrap() {
      try {
        const health = await api<{ capabilities?: { auth?: boolean } }>("/health");
        if (!active) return;
        const authRequired = Boolean(health.capabilities?.auth);
        setRequired(authRequired);
        if (!authRequired) {
          setAuthenticated(true);
          return;
        }
        try {
          await api("/auth/me");
          if (active) setAuthenticated(true);
        } catch {
          clearAuthToken();
          if (active) setAuthenticated(false);
        }
      } catch {
        if (active) setAuthenticated(true);
      } finally {
        if (active) setLoading(false);
      }
    }
    void bootstrap();
    return () => { active = false; };
  }, []);

  if (loading) {
    return <div className="grid min-h-screen place-items-center bg-[#020508] text-xs text-slate-500">Initializing secure workstation…</div>;
  }
  if (!required || authenticated) return <>{children}</>;
  return <LoginScreen onAuthenticated={() => setAuthenticated(true)} />;
}

function LoginScreen({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  async function login(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api<{ access_token: string; user: { username: string; role: string } }>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      setAuthToken(result.access_token);
      onAuthenticated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed.");
    } finally {
      setBusy(false);
    }
  }

  return <main className="grid min-h-screen place-items-center bg-[#020508] p-6 text-slate-200 scan-grid">
    <form onSubmit={login} className="w-full max-w-sm rounded-2xl border border-slate-800 bg-[#0a0f14]/95 p-6 shadow-2xl">
      <div className="text-[10px] uppercase tracking-[.2em] text-cyan-300/70">MEDAXIS 3D</div>
      <h1 className="mt-2 text-xl font-semibold">Secure workstation</h1>
      <p className="mt-2 text-[10px] leading-5 text-slate-500">Authentication is required for this deployment. Sign in with an authorized account.</p>
      <label className="mt-5 block text-[10px] text-slate-500">Username<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-200 outline-none focus:border-cyan-300/40" /></label>
      <label className="mt-3 block text-[10px] text-slate-500">Password<input value={password} onChange={(e) => setPassword(e.target.value)} type="password" autoComplete="current-password" className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-200 outline-none focus:border-cyan-300/40" /></label>
      {error ? <div role="alert" className="mt-3 rounded-lg border border-rose-500/20 bg-rose-500/5 p-2 text-[10px] leading-4 text-rose-200">{error}</div> : null}
      <button disabled={busy || !username || !password} className="mt-5 w-full rounded-lg border border-cyan-300/20 bg-cyan-300/10 px-3 py-2 text-xs text-cyan-100 disabled:opacity-40">{busy ? "Signing in…" : "Sign in"}</button>
      <div className="mt-4 text-center text-[9px] text-slate-700">Research / educational workstation · access controlled by deployment policy</div>
    </form>
  </main>;
}

export default function Home() {
  return <AuthGate><Workstation /></AuthGate>;
}
