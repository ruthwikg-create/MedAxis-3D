"use client";

import React, { useEffect, useMemo, useState } from "react";
import {
  Activity, BarChart3, Database, Download, FileCheck2, FileImage, LockKeyhole, LogOut,
  RefreshCw, ShieldCheck, Sparkles, Stethoscope, TestTube2, Upload, Users, X
} from "lucide-react";
import { api, clearAuthToken, downloadEndpoint, getAuthToken, setAuthToken } from "../lib/api";
import { Badge, IconButton, Metric } from "./Ui";

type CaseRecord = {
  case_id: string;
  status: string;
  classification: string;
  created_at: string;
  study?: Record<string, string | null>;
  summary?: {
    modality?: string;
    source_type?: string;
    volume_dimensions?: number[];
    pixel_spacing_mm?: number[];
    slice_thickness_mm?: number | null;
    orientation?: string;
  };
};

type Model = {
  model_id: string;
  display_name: string;
  version: string;
  modality: string;
  body_region: string;
  kind: string;
  input_type?: string;
  source: string;
  status: string;
  device: string;
  publisher_benchmark: string;
  validation_status: string;
  required_sequences?: string[];
  generic_inference?: boolean;
  structures?: Record<string, number>;
  calibration?: { available: boolean; model_version?: string; artifact_hash?: string | null };
};

type Job = {
  job_id: string;
  status: string;
  progress: number;
  message: string;
  result?: Record<string, unknown>;
  error?: string | null;
};

type Calibration = {
  ece: number;
  brier_score: number;
  bins: Array<{ count: number; mean_confidence: number; mean_accuracy: number }>;
  sample_count?: number;
  status?: string;
};

type Histogram = {
  counts: number[];
  centers: number[];
  sample_count: number;
  source_voxel_count: number;
  range: [number, number];
  sampling: string;
};

type Props = {
  activeCase: CaseRecord | null;
  cases: CaseRecord[];
  onClose: () => void;
  setToast: (value: { kind: "good" | "warn" | "bad"; text: string }) => void;
};

type Tab = "anatomy" | "disease" | "quant" | "ai" | "specialty" | "validation" | "security";
const TABS: Array<[Tab, string]> = [
  ["anatomy", "Structural map"],
  ["disease", "Disease & radiomics"],
  ["quant", "Segmentation & metrics"],
  ["ai", "AI & synthesis"],
  ["specialty", "Cardiac / prostate"],
  ["validation", "Validation"],
  ["security", "Security / storage"],
];

export function AnalyticsSuite({ activeCase, cases, onClose, setToast }: Props) {
  const [tab, setTab] = useState<Tab>("anatomy");
  const [models, setModels] = useState<Model[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [selectedStructure, setSelectedStructure] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [lungJob, setLungJob] = useState<Job | null>(null);
  const [clinicalStatus, setClinicalStatus] = useState<Record<string, string> | null>(null);
  const [diagnostics, setDiagnostics] = useState<Record<string, string> | null>(null);
  const [roleMatrix, setRoleMatrix] = useState<Record<string, unknown> | null>(null);
  const [capabilities, setCapabilities] = useState<Record<string, unknown> | null>(null);
  const [datasetProfile, setDatasetProfile] = useState<Record<string, unknown> | null>(null);
  const [tissue, setTissue] = useState<Record<string, unknown> | null>(null);
  const [histogram, setHistogram] = useState<Histogram | null>(null);
  const [radiomics, setRadiomics] = useState<Record<string, unknown> | null>(null);
  const [radiomicsPrediction, setRadiomicsPrediction] = useState<Record<string, unknown> | null>(null);
  const [findings, setFindings] = useState<Record<string, unknown> | null>(null);
  const [history, setHistory] = useState<Record<string, unknown>[]>([]);
  const [validation, setValidation] = useState<Record<string, unknown> | null>(null);
  const [calibration, setCalibration] = useState<Calibration | null>(null);
  const [authUser, setAuthUser] = useState<{ username: string; role: string } | null>(null);
  const [users, setUsers] = useState<Array<{ id: number; username: string; role: string; active: boolean; created_at: string }>>([]);
  const [login, setLogin] = useState({ username: "", password: "" });
  const [newUser, setNewUser] = useState({ username: "", password: "", role: "viewer" });
  const [selectedComparison, setSelectedComparison] = useState<string[]>([]);
  const [comparison, setComparison] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const compatibleModels = useMemo(() => {
    const modality = (activeCase?.summary?.modality ?? "").toUpperCase();
    return models.filter((model) => {
      if (model.modality === "PATHOLOGY") return false;
      if (modality === "MR" || modality === "MRI") return model.modality === "MRI";
      if (modality === "CT") return model.modality === "CT";
      return true;
    });
  }, [activeCase?.summary?.modality, models]);

  useEffect(() => {
    void Promise.allSettled([
      api<Model[]>("/advanced/models").then(setModels),
      api<Record<string, string>>("/research/validation/status").then(setClinicalStatus),
      api<Record<string, string>>("/system/diagnostics").then(setDiagnostics),
      api<Record<string, unknown>>("/analytics/capabilities").then(setCapabilities),
      api<Record<string, unknown>>("/role-matrix").then(setRoleMatrix),
    ]);
    if (getAuthToken()) {
      void api<{ username: string; role: string }>("/auth/me").then(setAuthUser).catch(() => setAuthUser(null));
    }
  }, []);

  useEffect(() => {
    if (!activeCase) return;
    setRadiomics(null);
    setRadiomicsPrediction(null);
    setFindings(null);
    setComparison(null);
    setJob(null);
    setLungJob(null);
    void api<Record<string, unknown>>(`/analytics/dataset-profile/${encodeURIComponent(activeCase.case_id)}`).then(setDatasetProfile).catch(() => setDatasetProfile(null));
    void api<Histogram>(`/analytics/intensity-histogram/${encodeURIComponent(activeCase.case_id)}?bins=72`).then(setHistogram).catch(() => setHistogram(null));
    void api<Record<string, unknown>>(`/analytics/findings/${encodeURIComponent(activeCase.case_id)}`).then(setFindings).catch(() => setFindings(null));
    void api<Record<string, unknown>[]>(`/analytics/history/${encodeURIComponent(activeCase.case_id)}`).then(setHistory).catch(() => setHistory([]));
    if (activeCase.summary?.modality === "CT") {
      void api<Record<string, unknown>>(`/analytics/tissue-bands/${encodeURIComponent(activeCase.case_id)}`).then(setTissue).catch(() => setTissue(null));
    } else {
      setTissue(null);
    }
  }, [activeCase?.case_id, activeCase?.summary?.modality]);

  useEffect(() => {
    if (!compatibleModels.some((item) => item.model_id === selectedModel)) setSelectedModel(compatibleModels[0]?.model_id ?? "");
  }, [compatibleModels, selectedModel]);

  useEffect(() => {
    const model = models.find((item) => item.model_id === selectedModel);
    const structures = model?.structures ? Object.keys(model.structures) : [];
    if (!structures.includes(selectedStructure)) setSelectedStructure(structures[0] ?? "");
  }, [models, selectedModel, selectedStructure]);

  useEffect(() => {
    const jobId = job?.job_id;
    const status = job?.status;

    if (!jobId || status === "COMPLETED" || status === "FAILED" || status === "CANCELLED") return;

    const timer = window.setInterval(() => {
      void api<Job>(`/jobs/${encodeURIComponent(jobId)}`)
        .then(setJob)
        .catch(() => undefined);
    }, 800);

    return () => window.clearInterval(timer);
  }, [job?.job_id, job?.status]);

  useEffect(() => {
    const jobId = lungJob?.job_id;
    const status = lungJob?.status;

    if (!jobId || status === "COMPLETED" || status === "FAILED" || status === "CANCELLED") return;

    const timer = window.setInterval(() => {
      void api<Job>(`/jobs/${encodeURIComponent(jobId)}`)
        .then(setLungJob)
        .catch(() => undefined);
    }, 800);

    return () => window.clearInterval(timer);
  }, [lungJob?.job_id, lungJob?.status]);

  const currentModel = useMemo(() => models.find((item) => item.model_id === selectedModel) ?? null, [models, selectedModel]);

  async function refreshAnalytics() {
    if (!activeCase) return;
    const [profile, hist, findingRows, historyRows] = await Promise.allSettled([
      api<Record<string, unknown>>(`/analytics/dataset-profile/${encodeURIComponent(activeCase.case_id)}`),
      api<Histogram>(`/analytics/intensity-histogram/${encodeURIComponent(activeCase.case_id)}?bins=72`),
      api<Record<string, unknown>>(`/analytics/findings/${encodeURIComponent(activeCase.case_id)}`),
      api<Record<string, unknown>[]>(`/analytics/history/${encodeURIComponent(activeCase.case_id)}`),
    ]);
    if (profile.status === "fulfilled") setDatasetProfile(profile.value);
    if (hist.status === "fulfilled") setHistogram(hist.value);
    if (findingRows.status === "fulfilled") setFindings(findingRows.value);
    if (historyRows.status === "fulfilled") setHistory(historyRows.value);
    setToast({ kind: "good", text: "Analytics refreshed from the active source dataset." });
  }

  async function downloadModel() {
    if (!selectedModel) return;
    setBusy("model-download");
    try {
      const result = await api<Model>(`/advanced/models/${encodeURIComponent(selectedModel)}/download`, { method: "POST" });
      setModels((items) => items.map((item) => item.model_id === result.model_id ? result : item));
      setToast({ kind: "good", text: `${result.display_name} is now ${result.status}.` });
    } catch (error) {
      setToast({ kind: "bad", text: error instanceof Error ? error.message : "Model download failed." });
    } finally { setBusy(null); }
  }

  async function runInference() {
    if (!activeCase || !selectedModel) return;
    setBusy("inference");
    try {
      const response = await api<{ job_id: string; status: string }>("/ai/inference", { method: "POST", body: JSON.stringify({ case_id: activeCase.case_id, model_id: selectedModel, structure: selectedStructure || null }) });
      setJob({ job_id: response.job_id, status: response.status, progress: 0, message: "Queued" });
    } catch (error) {
      setToast({ kind: "bad", text: error instanceof Error ? error.message : "Inference could not start." });
    } finally { setBusy(null); }
  }

  async function runLungNodule() {
    if (!activeCase) return;
    setBusy("lung");
    try {
      const response = await api<{ job_id: string; status: string }>(`/ai/lung-nodule/${encodeURIComponent(activeCase.case_id)}`, { method: "POST" });
      setLungJob({ job_id: response.job_id, status: response.status, progress: 0, message: "Queued" });
    } catch (error) {
      setToast({ kind: "bad", text: error instanceof Error ? error.message : "Lung-nodule inference unavailable." });
    } finally { setBusy(null); }
  }

  async function extractRadiomics() {
    if (!activeCase) return;
    setBusy("radiomics");
    try {
      const result = await api<Record<string, unknown>>(`/analytics/radiomics?case_id=${encodeURIComponent(activeCase.case_id)}`);
      setRadiomics(result);
      setToast({ kind: "good", text: "Radiomics features measured from the current source volume." });
    } catch (error) {
      setToast({ kind: "bad", text: error instanceof Error ? error.message : "Radiomics extraction failed." });
    } finally { setBusy(null); }
  }

  async function predictRadiomics() {
    if (!radiomics) return;
    setBusy("radiomics-predict");
    try {
      const numeric: Record<string, number> = {};
      const firstOrder = radiomics.first_order && typeof radiomics.first_order === "object" ? radiomics.first_order as Record<string, unknown> : {};
      const texture = radiomics.texture_glcm && typeof radiomics.texture_glcm === "object" ? radiomics.texture_glcm as Record<string, unknown> : {};
      for (const [key, value] of Object.entries(firstOrder)) if (typeof value === "number" && Number.isFinite(value)) numeric[`first_order_${key}`] = value;
      for (const [key, value] of Object.entries(texture)) if (typeof value === "number" && Number.isFinite(value)) numeric[`texture_${key}`] = value;
      setRadiomicsPrediction(await api<Record<string, unknown>>(`/radiomics/classifier/predict?model_id=radiomics-research`, { method: "POST", body: JSON.stringify({ features: numeric }) }));
    } catch (error) {
      setRadiomicsPrediction({ status: "UNAVAILABLE", note: error instanceof Error ? error.message : "Research classifier is not configured." });
    } finally { setBusy(null); }
  }

  async function compareSelected() {
    if (selectedComparison.length < 2) return;
    try {
      setComparison(await api(`/comparison?case_ids=${selectedComparison.map(encodeURIComponent).join(",")}`));
    } catch (error) {
      setToast({ kind: "bad", text: error instanceof Error ? error.message : "Comparison failed." });
    }
  }

  async function loginUser(event: React.FormEvent) {
    event.preventDefault();
    try {
      const result = await api<{ access_token: string; user: { username: string; role: string } }>("/auth/login", { method: "POST", body: JSON.stringify(login) });
      setAuthToken(result.access_token);
      setAuthUser(result.user);
      setLogin({ username: "", password: "" });
      setToast({ kind: "good", text: `Signed in as ${result.user.username} (${result.user.role}).` });
    } catch (error) {
      setToast({ kind: "bad", text: error instanceof Error ? error.message : "Sign-in failed." });
    }
  }

  function logoutUser() {
    clearAuthToken();
    setAuthUser(null);
    setUsers([]);
    setToast({ kind: "good", text: "Signed out of MedAxis." });
  }

  async function loadUsers() {
    try { setUsers(await api("/auth/users")); }
    catch (error) { setToast({ kind: "bad", text: error instanceof Error ? error.message : "User list unavailable." }); }
  }

  async function createUser(event: React.FormEvent) {
    event.preventDefault();
    try {
      await api("/auth/users", { method: "POST", body: JSON.stringify(newUser) });
      setNewUser({ username: "", password: "", role: "viewer" });
      await loadUsers();
      setToast({ kind: "good", text: "User created with the selected RBAC role." });
    } catch (error) { setToast({ kind: "bad", text: error instanceof Error ? error.message : "User creation failed." }); }
  }

  async function updateUser(username: string, patch: { active?: boolean; role?: string }) {
    try {
      const params = new URLSearchParams(Object.entries(patch).map(([k, v]) => [k, String(v)]));
      await api(`/auth/users/${encodeURIComponent(username)}?${params.toString()}`, { method: "PATCH" });
      await loadUsers();
    } catch (error) { setToast({ kind: "bad", text: error instanceof Error ? error.message : "User update failed." }); }
  }

  async function postCalibration(probabilityText: string, labelText: string, bins: number) {
    try {
      const probabilities = probabilityText.split(/[\s,;]+/).map(Number);
      const labels = labelText.split(/[\s,;]+/).map(Number);
      if (probabilities.some((v) => !Number.isFinite(v)) || labels.some((v) => v !== 0 && v !== 1)) throw new Error("Enter finite probabilities in [0,1] and binary labels only.");
      if (probabilities.length !== labels.length) throw new Error("Probability and label counts must match exactly.");
      setCalibration(await api<Calibration>("/validation/calibration", { method: "POST", body: JSON.stringify({ probabilities, labels, bins }) }));
    } catch (error) { setToast({ kind: "bad", text: error instanceof Error ? error.message : "Calibration failed." }); }
  }

  async function fitCalibration(probabilityText: string, labelText: string) {
    try {
      const probabilities = probabilityText.split(/[\s,;]+/).map(Number);
      const labels = labelText.split(/[\s,;]+/).map(Number);
      if (probabilities.length !== labels.length) throw new Error("Probability and label counts must match exactly.");
      const result = await api<Record<string, unknown>>("/validation/calibration/fit", { method: "POST", body: JSON.stringify({ probabilities, labels }) });
      const after = result.after as Calibration | undefined;
      if (after) setCalibration(after);
      setToast({ kind: "good", text: "Research temperature scaling fitted to the supplied held-out cohort." });
    } catch (error) { setToast({ kind: "bad", text: error instanceof Error ? error.message : "Calibration fitting failed." }); }
  }

  async function downloadExport(path: string, filename: string) {
    setBusy(filename);
    try {
      await downloadEndpoint(path, filename);
      setToast({ kind: "good", text: `${filename} downloaded.` });
    } catch (error) {
      setToast({ kind: "bad", text: error instanceof Error ? error.message : "Export failed." });
    } finally { setBusy(null); }
  }

  return (
    <div className="fixed inset-0 z-[55] flex items-stretch justify-center bg-black/70 p-2 backdrop-blur-sm">
      <div className="flex h-full w-full max-w-[1550px] flex-col overflow-hidden rounded-2xl border border-slate-700/80 bg-[#070b10] shadow-2xl">
        <header className="flex min-h-14 items-center justify-between border-b border-slate-800 px-4">
          <div className="flex min-w-0 items-center gap-3">
            <div className="grid size-9 shrink-0 place-items-center rounded-lg border border-cyan-300/15 bg-cyan-300/[.04] text-cyan-200"><BarChart3 size={17} /></div>
            <div className="min-w-0"><div className="truncate text-sm font-semibold text-slate-100">Dataset & AI Analytics Suite</div><div className="truncate text-[9px] uppercase tracking-[.17em] text-slate-600">MEDAXIS 3D · data-derived research analytics</div></div>
          </div>
          <div className="flex items-center gap-2"><Badge tone="warn">RESEARCH / EDUCATIONAL</Badge><button onClick={() => void refreshAnalytics()} disabled={!activeCase} className="grid size-8 place-items-center rounded-md border border-slate-800 bg-slate-950/50 text-slate-400 hover:text-white disabled:opacity-30" title="Refresh analytics" aria-label="Refresh analytics"><RefreshCw size={14} /></button><IconButton label="Close analytics" onClick={onClose}><X size={15} /></IconButton></div>
        </header>
        <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
          <nav className="flex shrink-0 gap-1 overflow-auto border-b border-slate-800 bg-[#090e14] p-2 lg:w-56 lg:flex-col lg:border-b-0 lg:border-r">
            {TABS.map(([id, label]) => <button key={id} onClick={() => setTab(id)} className={`rounded-lg px-3 py-2 text-left text-[10px] ${tab === id ? "bg-cyan-300/10 text-cyan-100" : "text-slate-500 hover:bg-slate-900 hover:text-slate-300"}`}>{label}</button>)}
            <div className="mt-auto hidden rounded-lg border border-slate-900 bg-slate-950/45 p-3 lg:block"><div className="text-[9px] uppercase tracking-[.14em] text-slate-600">Active study</div><div className="mt-1 text-xs text-slate-200">{activeCase?.study?.study_description ?? "No study loaded"}</div><div className="mono mt-1 text-[9px] text-slate-600">{activeCase?.case_id ?? "—"}</div></div>
          </nav>
          <section className="min-h-0 flex-1 overflow-auto p-4 lg:p-5">
            {!activeCase ? <EmptySuite /> : tab === "anatomy" ? <AnatomyTab activeCase={activeCase} tissue={tissue} profile={datasetProfile} histogram={histogram} />
              : tab === "disease" ? <DiseaseTab activeCase={activeCase} models={models} radiomics={radiomics} radiomicsPrediction={radiomicsPrediction} findings={findings} onRadiomics={extractRadiomics} onPredictRadiomics={predictRadiomics} onLungNodule={runLungNodule} lungJob={lungJob} busy={busy} />
              : tab === "quant" ? <QuantTab activeCase={activeCase} cases={cases} history={history} selectedComparison={selectedComparison} setSelectedComparison={setSelectedComparison} comparison={comparison} onCompare={compareSelected} onExport={(kind) => void downloadExport(kind === "seg" ? `/export/seg/${encodeURIComponent(activeCase.case_id)}?structure=spleen` : `/export/sr/${encodeURIComponent(activeCase.case_id)}`, kind === "seg" ? "medaxis-segmentation.dcm" : "medaxis-quantitative-sr.dcm")} busy={busy} />
              : tab === "ai" ? <AITab activeCase={activeCase} models={compatibleModels} model={currentModel && compatibleModels.some((m) => m.model_id === currentModel.model_id) ? currentModel : null} selectedModel={selectedModel} setSelectedModel={setSelectedModel} selectedStructure={selectedStructure} setSelectedStructure={setSelectedStructure} onDownload={downloadModel} onRun={runInference} job={job} busy={busy} onSynthesis={() => void downloadExport(`/advanced/synthesis/ct-to-mri/${encodeURIComponent(activeCase.case_id)}`, `medaxis-ct-to-mri-${activeCase.case_id}.nii.gz`)} />
              : tab === "specialty" ? <SpecialtyTab activeCase={activeCase} setToast={setToast} />
              : tab === "validation" ? <ValidationTab activeCase={activeCase} clinicalStatus={clinicalStatus} validation={validation} setValidation={setValidation} calibration={calibration} onCalibration={postCalibration} onFitCalibration={fitCalibration} />
              : <SecurityTab diagnostics={diagnostics} capabilities={capabilities} roleMatrix={roleMatrix} authUser={authUser} login={login} setLogin={setLogin} onLogin={loginUser} onLogout={logoutUser} users={users} loadUsers={loadUsers} newUser={newUser} setNewUser={setNewUser} onCreateUser={createUser} onUpdateUser={updateUser} />}
          </section>
        </div>
      </div>
    </div>
  );
}

function EmptySuite() { return <div className="grid h-full place-items-center"><div className="max-w-md text-center"><div className="mx-auto grid size-12 place-items-center rounded-xl border border-slate-800 bg-slate-950/60 text-slate-500"><Activity size={20}/></div><div className="mt-4 text-sm text-slate-300">No active imaging study</div><div className="mt-1 text-[10px] leading-5 text-slate-600">Load a DICOM or NIfTI case before running dataset analytics. The suite never invents measurements for an empty dataset.</div></div></div>; }

function Panel({ title, kicker, children, right }: { title: string; kicker?: string; children: React.ReactNode; right?: React.ReactNode }) {
  return <section className="overflow-hidden rounded-xl border border-slate-800 bg-[#0b1016]"><div className="flex items-start justify-between gap-3 border-b border-slate-900 px-4 py-3"><div><div className="text-[9px] uppercase tracking-[.16em] text-cyan-300/60">{kicker ?? "ANALYTICS"}</div><h2 className="mt-1 text-sm font-semibold text-slate-100">{title}</h2></div>{right}</div><div className="p-4">{children}</div></section>;
}

function HistogramChart({ histogram, unit }: { histogram: Histogram | null; unit?: string }) {
  const [hovered, setHovered] = useState<number | null>(null);
  if (!histogram || !histogram.counts.length) return <div className="grid h-48 place-items-center border border-slate-900 bg-slate-950/35 text-[10px] text-slate-600">Histogram unavailable.</div>;
  const max = Math.max(1, ...histogram.counts);
  const barWidth = 100 / histogram.counts.length;
  return <div className="relative rounded-lg border border-slate-900 bg-[#070b10] p-3">
    <svg viewBox="0 0 100 46" preserveAspectRatio="none" className="h-44 w-full" role="img" aria-label={`Source intensity histogram, ${histogram.sample_count} sampled voxels`}>
      {histogram.counts.map((count, index) => <rect key={index} x={index * barWidth} y={44 - (count / max) * 40} width={Math.max(0.2, barWidth - 0.18)} height={(count / max) * 40} rx="0.1" className="fill-cyan-300/50 hover:fill-cyan-200/80" onMouseEnter={() => setHovered(index)} onMouseLeave={() => setHovered(null)} />)}
      <line x1="0" y1="44" x2="100" y2="44" className="stroke-slate-800" strokeWidth="0.4" />
    </svg>
    <div className="mt-1 flex justify-between mono text-[8px] text-slate-600"><span>{formatNumber(histogram.range[0])} {unit ?? ""}</span><span>{formatNumber(histogram.range[1])} {unit ?? ""}</span></div>
    {hovered !== null ? <div className="pointer-events-none absolute right-3 top-3 rounded border border-slate-800 bg-slate-950/95 px-2 py-1.5 text-[9px] shadow-xl"><div className="mono text-slate-200">{formatNumber(histogram.centers[hovered])} {unit ?? ""}</div><div className="mono text-slate-500">{histogram.counts[hovered].toLocaleString()} voxels</div></div> : null}
    <div className="mt-2 text-[8px] text-slate-600">{histogram.sampling}. Descriptive source intensity only; no tissue classification is inferred.</div>
  </div>;
}

function FeatureBars({ values, title }: { values: Record<string, unknown>; title: string }) {
  const numeric = Object.entries(values).filter(([, v]) => typeof v === "number" && Number.isFinite(v as number)) as Array<[string, number]>;
  const max = Math.max(1e-9, ...numeric.map(([, v]) => Math.abs(v)));
  return <div className="rounded-lg border border-slate-900 bg-slate-950/35 p-3"><div className="mb-3 text-[9px] uppercase tracking-[.13em] text-slate-600">{title}</div><div className="space-y-2">{numeric.slice(0, 10).map(([key, value]) => <div key={key}><div className="flex items-center justify-between text-[9px] text-slate-500"><span>{key.replaceAll("_", " ")}</span><span className="mono text-slate-300">{value.toFixed(4)}</span></div><div className="mt-1 h-1.5 overflow-hidden rounded bg-slate-900"><div className="h-full rounded bg-slate-500" style={{ width: `${Math.min(100, Math.abs(value) / max * 100)}%` }} /></div></div>)}</div></div>;
}

function AnatomyTab({ activeCase, tissue, profile, histogram }: { activeCase: CaseRecord; tissue: Record<string, unknown> | null; profile: Record<string, unknown> | null; histogram: Histogram | null }) {
  const percentiles = profile?.percentiles && typeof profile.percentiles === "object" ? profile.percentiles as Record<string, number> : {};
  const bands = Array.isArray(tissue?.bands) ? tissue?.bands as Array<Record<string, unknown>> : [];
  return <div className="space-y-4">
    <div className="grid gap-3 xl:grid-cols-5"><Metric label="Modality" value={String(profile?.modality ?? activeCase.summary?.modality ?? "—")} /><Metric label="Shape Z×Y×X" value={Array.isArray(profile?.shape_zyx) ? (profile?.shape_zyx as number[]).join(" × ") : "—"} /><Metric label="Spacing" value={Array.isArray(profile?.spacing_xyz_mm) ? (profile?.spacing_xyz_mm as number[]).map((v) => `${v.toFixed(3)}`).join(" × ") : "—"} unit="mm" /><Metric label="Finite voxels" value={Number(profile?.finite_voxels ?? 0).toLocaleString()} /><Metric label="Source" value="IMPORTED DATA" /></div>
    <div className="grid gap-4 xl:grid-cols-[1.35fr_.65fr]">
      <Panel title="Source intensity distribution" kicker="INTERACTIVE / DATA-DERIVED"><HistogramChart histogram={histogram} unit={activeCase.summary?.modality === "CT" ? "HU*" : "signal"} /><div className="mt-3 grid grid-cols-4 gap-2">{["1", "25", "50", "75"].map((q) => <div key={q} className="rounded border border-slate-900 bg-slate-950/40 p-2"><div className="text-[8px] uppercase tracking-[.12em] text-slate-600">P{q}</div><div className="mono mt-1 text-[10px] text-slate-300">{Number.isFinite(percentiles[q]) ? percentiles[q].toFixed(3) : "—"}</div></div>)}</div></Panel>
      <Panel title="Tissue characterization" kicker="REFERENCE BANDS"><div className="text-[9px] leading-4 text-slate-600">For CT, bands are educational reference intervals and are not diagnostic thresholds. MRI signal intensity is sequence/scanner dependent.</div><div className="mt-3 space-y-1.5">{bands.length ? bands.map((band) => <div key={String(band.name)} className="flex items-center justify-between rounded border border-slate-900 bg-slate-950/35 px-2 py-1.5"><span className="text-[9px] text-slate-300">{String(band.name)}</span><span className="mono text-[8px] text-slate-500">{String(band.lower_hu)} … {String(band.upper_hu)} HU</span></div>) : <div className="py-8 text-center text-[10px] text-slate-600">CT reference bands only.</div>}</div></Panel>
    </div>
    <Panel title="Structural mapping readiness" kicker="3D / MPR"><div className="grid gap-2 sm:grid-cols-3"><StatusMetric label="3D surface" value="SOURCE-DERIVED" tone="good" /><StatusMetric label="MPR" value="AXIAL · SAGITTAL · CORONAL" tone="good" /><StatusMetric label="Geometry" value={activeCase.summary?.orientation ?? "SOURCE METADATA"} tone="neutral" /></div></Panel>
  </div>;
}

function DiseaseTab({ activeCase, models, radiomics, radiomicsPrediction, findings, onRadiomics, onPredictRadiomics, onLungNodule, lungJob, busy }: { activeCase: CaseRecord; models: Model[]; radiomics: Record<string, unknown> | null; radiomicsPrediction: Record<string, unknown> | null; findings: Record<string, unknown> | null; onRadiomics: () => void; onPredictRadiomics: () => void; onLungNodule: () => void; lungJob: Job | null; busy: string | null }) {
  const firstOrder = radiomics?.first_order && typeof radiomics.first_order === "object" ? radiomics.first_order as Record<string, unknown> : {};
  const texture = radiomics?.texture_glcm && typeof radiomics.texture_glcm === "object" ? radiomics.texture_glcm as Record<string, unknown> : {};
  const detectionRows = Array.isArray(findings?.findings) ? findings?.findings as Array<Record<string, unknown>> : [];
  const detector = models.find((model) => model.model_id === "lung_nodule_ct_detection");
  return <div className="space-y-4">
    <div className="grid gap-4 xl:grid-cols-[1.1fr_.9fr]">
      <Panel title="Pathology identification" kicker="MODEL OUTPUT / NOT A DIAGNOSIS"><div className="grid gap-2 sm:grid-cols-2"><StatusMetric label="Lung nodule detector" value={detector?.status ?? "MODEL NOT DOWNLOADED"} tone={detector?.status === "MODEL READY" ? "good" : "warn"} /><StatusMetric label="Persisted findings" value={`${detectionRows.length} finding${detectionRows.length === 1 ? "" : "s"}`} tone={detectionRows.length ? "warn" : "neutral"} /></div><div className="mt-3 rounded border border-slate-900 bg-slate-950/40 p-3 text-[9px] leading-4 text-slate-600">Detection scores are retained as model scores unless a matching research calibrator is installed. They are not patient diagnoses or clinical probabilities.</div><button onClick={onLungNodule} disabled={busy === "lung" || activeCase.summary?.modality !== "CT"} className="mt-3 inline-flex items-center gap-2 rounded border border-cyan-400/20 bg-cyan-400/10 px-3 py-2 text-[10px] text-cyan-100 disabled:opacity-30"><TestTube2 size={13}/>{busy === "lung" ? "Queueing…" : "Run lung nodule model"}</button>{lungJob ? <JobStatus job={lungJob} /> : null}{detectionRows.length ? <div className="mt-3 space-y-1.5">{detectionRows.slice(0, 12).map((row, index) => <div key={`${String(row.label)}-${index}`} className="grid grid-cols-[1fr_auto_auto] gap-3 rounded border border-slate-900 bg-slate-950/35 px-2 py-2 text-[9px]"><span className="text-slate-300">{String(row.label ?? "Model finding")}</span><span className="mono text-slate-400">{typeof row.score === "number" ? `${(row.score * 100).toFixed(1)}%` : "—"}</span><Badge tone="warn">MODEL OUTPUT</Badge></div>)}</div> : null}</Panel>
      <Panel title="Benign / malignant radiomics" kicker="RESEARCH CLASSIFIER"><div className="text-[9px] leading-4 text-slate-600">This panel uses measured radiomics features and a user-trained research classifier. It does not simulate pathology or genomic outcomes.</div><button onClick={onRadiomics} disabled={busy === "radiomics"} className="mt-3 inline-flex items-center gap-2 rounded border border-cyan-400/20 bg-cyan-400/10 px-3 py-2 text-[10px] text-cyan-100 disabled:opacity-30"><BarChart3 size={13}/>{busy === "radiomics" ? "Extracting…" : "Extract radiomics"}</button>{radiomics ? <div className="mt-3 grid gap-3 lg:grid-cols-2"><FeatureBars values={firstOrder} title="First-order intensity" /><FeatureBars values={texture} title="GLCM texture subset" /></div> : <div className="mt-3 rounded border border-slate-900 bg-slate-950/40 p-3 text-[9px] text-slate-600">No radiomics run for this case.</div>}</Panel>
    </div>
    {radiomics ? <Panel title="Research feature record" kicker="SOURCE + METHODOLOGY"><div className="grid gap-2 sm:grid-cols-4"><Metric label="Volume" value={Number(radiomics.volume_cm3 ?? 0).toFixed(3)} unit="cm³" /><Metric label="Surface" value={Number(radiomics.surface_area_mm2 ?? 0).toFixed(3)} unit="mm²" /><Metric label="Entropy" value={Number(radiomics.entropy ?? 0).toFixed(4)} /><Metric label="Energy" value={Number(radiomics.energy ?? 0).toFixed(4)} /></div><div className="mt-3 text-[9px] leading-4 text-slate-600">{String(radiomics.method ?? "Research radiomics.")}</div></Panel> : null}
    <Panel title="Predictive radiomics" kicker="RESEARCH MODEL / NO SIMULATED GENOMICS"><div className="grid gap-3 lg:grid-cols-[1fr_auto]"><div className="text-[9px] leading-4 text-slate-600">Runs only against a user-trained research radiomics classifier. No genomic, pathology, prognosis, treatment-response, or clinical malignancy outcome is simulated or inferred.</div><button onClick={onPredictRadiomics} disabled={!radiomics || busy === "radiomics-predict"} className="inline-flex items-center justify-center gap-2 rounded border border-cyan-400/20 bg-cyan-400/10 px-3 py-2 text-[10px] text-cyan-100 disabled:opacity-30"><Sparkles size={13}/>{busy === "radiomics-predict" ? "Evaluating…" : "Run research classifier"}</button></div>{radiomicsPrediction ? <div className="mt-3 grid gap-2 sm:grid-cols-3"><Metric label="Status" value={String(radiomicsPrediction.status ?? "—")} /><Metric label="Research probability" value={typeof radiomicsPrediction.calibrated_probability === "number" ? `${(Number(radiomicsPrediction.calibrated_probability) * 100).toFixed(1)}%` : typeof radiomicsPrediction.positive_class_probability === "number" ? `${(Number(radiomicsPrediction.positive_class_probability) * 100).toFixed(1)}%` : "Not available"} /><Metric label="Class" value={String(radiomicsPrediction.class_label ?? "Not available")} /></div> : null}{radiomicsPrediction?.note ? <div className="mt-2 text-[9px] leading-4 text-amber-300/70">{String(radiomicsPrediction.note)}</div> : null}</Panel>
  </div>;
}

function QuantTab({ activeCase, cases, history, selectedComparison, setSelectedComparison, comparison, onCompare, onExport, busy }: { activeCase: CaseRecord; cases: CaseRecord[]; history: Record<string, unknown>[]; selectedComparison: string[]; setSelectedComparison: React.Dispatch<React.SetStateAction<string[]>>; comparison: Record<string, unknown> | null; onCompare: () => void; onExport: (kind: "seg" | "sr") => void; busy: string | null }) {
  const toggleCase = (id: string) => setSelectedComparison((items) => items.includes(id) ? items.filter((x) => x !== id) : items.length >= 4 ? items : [...items, id]);
  const compatibleMetrics = history.filter((row) => ["volume_cm3", "surface_area_mm2", "mean_intensity"].some((key) => typeof row[key] === "number"));
  return <div className="space-y-4">
    <Panel title="Automated segmentation & quantitative metrics" kicker="SOURCE-DERIVED / MODEL-OPTIONAL"><div className="grid gap-2 sm:grid-cols-4"><Metric label="Stored analyses" value={history.length} /><Metric label="Quantitative rows" value={compatibleMetrics.length} /><Metric label="SEG export" value="DICOM" /><Metric label="SR export" value="DICOM" /></div><div className="mt-3 grid gap-2 sm:grid-cols-2"><button onClick={() => onExport("seg")} disabled={Boolean(busy)} className="inline-flex items-center justify-center gap-2 rounded border border-cyan-400/20 bg-cyan-400/10 px-3 py-2 text-[10px] text-cyan-100 disabled:opacity-30"><FileImage size={13}/>Export DICOM SEG</button><button onClick={() => onExport("sr")} disabled={Boolean(busy)} className="inline-flex items-center justify-center gap-2 rounded border border-slate-800 bg-slate-950/60 px-3 py-2 text-[10px] text-slate-300 disabled:opacity-30"><FileCheck2 size={13}/>Export DICOM SR</button></div><div className="mt-3 text-[9px] leading-4 text-slate-600">Exports are only produced for compatible conventional DICOM source evidence and geometry-matched masks. NIfTI-only cases remain unavailable for DICOM object export.</div></Panel>
    <Panel title="Longitudinal tracking timeline" kicker="COMPATIBLE CASE COMPARISON"><div className="space-y-2">{cases.slice(0, 10).map((record) => <button key={record.case_id} onClick={() => toggleCase(record.case_id)} className={`flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left ${selectedComparison.includes(record.case_id) ? "border-cyan-400/25 bg-cyan-400/[.04]" : "border-slate-900 bg-slate-950/30"}`}><div className={`size-2 rounded-full ${selectedComparison.includes(record.case_id) ? "bg-cyan-300" : "bg-slate-700"}`} /><div className="min-w-0 flex-1"><div className="text-[10px] text-slate-300">{record.study?.study_description ?? "Imaging study"}</div><div className="mono mt-1 text-[8px] text-slate-600">{record.created_at} · {record.study?.modality ?? record.summary?.modality ?? "—"}</div></div><Badge tone={record.status === "DEMO DATA" ? "warn" : "neutral"}>{record.status}</Badge></button>)}</div><button onClick={onCompare} disabled={selectedComparison.length < 2} className="mt-3 inline-flex items-center gap-2 rounded border border-cyan-400/20 bg-cyan-400/10 px-3 py-2 text-[10px] text-cyan-100 disabled:opacity-30">Compare {selectedComparison.length || "selected"} studies</button>{comparison ? <ComparisonView comparison={comparison} /> : null}</Panel>
  </div>;
}

function ComparisonView({ comparison }: { comparison: Record<string, unknown> }) {
  const changes = Array.isArray(comparison.changes) ? comparison.changes as Array<Record<string, unknown>> : [];
  return <div className="mt-4 grid gap-2 lg:grid-cols-2">{changes.map((item, index) => <div key={index} className="rounded-lg border border-slate-900 bg-slate-950/35 p-3"><div className="mono text-[9px] text-slate-500">{String(item.baseline_case_id)} → {String(item.current_case_id)}</div><div className="mt-2 space-y-1.5">{item.changes && typeof item.changes === "object" ? Object.entries(item.changes as Record<string, unknown>).map(([key, value]) => <div key={key} className="flex items-center justify-between text-[9px]"><span className="text-slate-500">{key.replaceAll("_", " ")}</span><span className="mono text-slate-300">{value && typeof value === "object" ? `${Number((value as Record<string, unknown>).absolute_change ?? NaN).toFixed(3)} (${Number((value as Record<string, unknown>).relative_change_percent ?? NaN).toFixed(2)}%)` : "—"}</span></div>) : null}</div></div>)}</div>;
}

function AITab({ activeCase, models, model, selectedModel, setSelectedModel, selectedStructure, setSelectedStructure, onDownload, onRun, job, busy, onSynthesis }: { activeCase: CaseRecord; models: Model[]; model: Model | null; selectedModel: string; setSelectedModel: (value: string) => void; selectedStructure: string; setSelectedStructure: (value: string) => void; onDownload: () => void; onRun: () => void; job: Job | null; busy: string | null; onSynthesis: () => void }) {
  const structures = model?.structures ? Object.keys(model.structures) : [];
  return <div className="space-y-4"><div className="grid gap-4 xl:grid-cols-[1.25fr_.75fr]">
    <Panel title="MONAI production-oriented inference" kicker="ACTUAL MODEL WEIGHTS / ASYNCHRONOUS JOB"><div className="grid gap-3 sm:grid-cols-2"><FieldSelect label="Model" value={selectedModel} set={setSelectedModel} options={models.map((item) => item.model_id)} /><FieldSelect label="Structure" value={selectedStructure} set={setSelectedStructure} options={structures.length ? structures : ["No structure advertised"]} /></div><div className="mt-3 flex flex-wrap gap-2"><button onClick={onDownload} disabled={!model || busy === "model-download"} className="inline-flex items-center gap-2 rounded border border-slate-800 bg-slate-950/60 px-3 py-2 text-[10px] text-slate-300 disabled:opacity-30"><Download size={13}/>{busy === "model-download" ? "Downloading…" : "Download official bundle"}</button><button onClick={onRun} disabled={!model || model.status !== "MODEL READY" || busy === "inference"} className="inline-flex items-center gap-2 rounded border border-cyan-400/20 bg-cyan-400/10 px-3 py-2 text-[10px] text-cyan-100 disabled:opacity-30"><Sparkles size={13}/>{busy === "inference" ? "Queueing…" : "Run inference"}</button></div>{model ? <div className="mt-3 grid gap-2 sm:grid-cols-4"><Metric label="Status" value={model.status} /><Metric label="Version" value={model.version} /><Metric label="Device" value={model.device} /><Metric label="Calibration" value={model.calibration?.available ? "RESEARCH CALIBRATOR" : "NOT AVAILABLE"} /></div> : <div className="mt-3 text-[10px] text-slate-600">No compatible MONAI model for this modality.</div>}{job ? <JobStatus job={job} /> : null}<div className="mt-3 text-[9px] leading-4 text-slate-600">Publisher benchmarks are not MedAxis clinical validation. Patient-specific outputs remain research outputs unless independently validated for the intended use.</div></Panel>
    <Panel title="Cross-modality synthesis" kicker="RESEARCH-GENERATED"><div className="grid gap-2 sm:grid-cols-2"><StatusMetric label="Source" value={activeCase.summary?.modality ?? "UNKNOWN"} tone="neutral" /><StatusMetric label="CT → MRI" value={activeCase.summary?.modality === "CT" ? "MODEL CONFIG REQUIRED" : "NOT APPLICABLE"} tone="warn" /></div><button onClick={onSynthesis} disabled={activeCase.summary?.modality !== "CT"} className="mt-3 inline-flex items-center gap-2 rounded border border-slate-800 bg-slate-950/60 px-3 py-2 text-[10px] text-slate-300 disabled:opacity-30"><Sparkles size={13}/>Run CT → MRI synthesis</button><div className="mt-3 text-[9px] leading-4 text-slate-600">The generated volume is explicitly marked as synthetic. It cannot substitute for an acquired MRI study or create clinical findings.</div></Panel>
  </div></div>;
}

function SpecialtyTab({ activeCase, setToast }: { activeCase: CaseRecord; setToast: Props["setToast"] }) {
  const [mode, setMode] = useState<"cardiac" | "prostate" | "pirads">("cardiac");
  const [file, setFile] = useState<File | null>(null);
  const [mask, setMask] = useState<File | null>(null);
  const [adc, setAdc] = useState<File | null>(null);
  const [t2, setT2] = useState<File | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [zone, setZone] = useState("peripheral_zone");
  const [t2Score, setT2Score] = useState(3);
  const [dwiScore, setDwiScore] = useState(3);
  const [dce, setDce] = useState("not_assessed");
  const [size, setSize] = useState(10);
  const [readerCategory, setReaderCategory] = useState(3);
  const [reader, setReader] = useState("");
  async function run() {
    try {
      if (mode === "pirads") {
        const payload = await api<Record<string, unknown>>(`/pi-rads/${encodeURIComponent(activeCase.case_id)}`, { method: "POST", body: JSON.stringify({ case_id: activeCase.case_id, zone, t2_score: t2Score, dwi_score: dwiScore, dce, lesion_size_mm: size, final_category: readerCategory, reader }) });
        setResult(payload); return;
      }
      if (!file || !mask) throw new Error("Provide an image and a geometry-compatible segmentation mask.");
      const form = new FormData(); form.append("image_file", file); form.append("mask_file", mask);
      if (mode === "cardiac") {
        const payload = await api<Record<string, unknown>>(`/cardiac/analyze`, { method: "POST", body: form });
        setResult(payload);
      } else {
        if (adc) form.append("adc_file", adc); if (t2) form.append("t2_file", t2);
        const payload = await api<Record<string, unknown>>(`/prostate/analyze`, { method: "POST", body: form });
        setResult(payload);
      }
    } catch (error) { setToast({ kind: "bad", text: error instanceof Error ? error.message : "Specialty analysis failed." }); }
  }
  return <div className="space-y-4"><div className="flex flex-wrap gap-1.5">{[["cardiac", "Cardiac MRI"], ["prostate", "Prostate MRI"], ["pirads", "PI-RADS worksheet"]].map(([id, label]) => <button key={id} onClick={() => { setMode(id as typeof mode); setResult(null); }} className={`rounded border px-3 py-2 text-[10px] ${mode === id ? "border-cyan-400/25 bg-cyan-400/10 text-cyan-100" : "border-slate-800 text-slate-500"}`}>{label}</button>)}</div>{mode === "pirads" ? <Panel title="PI-RADS v2.1 structured worksheet" kicker="READER-ENTERED / GUIDELINE CALCULATION"><div className="grid gap-3 md:grid-cols-3"><FieldSelect label="Zone" value={zone} set={setZone} options={["peripheral_zone", "transition_zone"]} /><FieldNumber label="T2 score" value={t2Score} set={setT2Score} /><FieldNumber label="DWI score" value={dwiScore} set={setDwiScore} /><FieldSelect label="DCE" value={dce} set={setDce} options={["not_assessed", "positive", "negative"]} /><FieldNumber label="Lesion size (mm)" value={size} set={setSize} /><FieldNumber label="Reader final category" value={readerCategory} set={setReaderCategory} /></div><input value={reader} onChange={(e) => setReader(e.target.value)} placeholder="Reader name" className="mt-3 h-9 w-full border border-slate-800 bg-slate-950 px-2 text-xs text-slate-300" /><button onClick={run} className="mt-3 rounded border border-cyan-400/20 bg-cyan-400/10 px-3 py-2 text-[10px] text-cyan-100">Calculate worksheet</button>{result ? <ResultCards result={result} /> : null}</Panel> : <Panel title={mode === "cardiac" ? "LV / RV functional metrics" : "Prostate quantitative analysis"} kicker="SUPPLIED IMAGE + SEGMENTATION"><div className="grid gap-3 md:grid-cols-2"><FilePicker label="Primary image" file={file} setFile={setFile} /><FilePicker label="Segmentation / label map" file={mask} setFile={setMask} /><FilePicker label="ADC (optional)" file={adc} setFile={setAdc} /><FilePicker label="T2 (optional)" file={t2} setFile={setT2} /></div><button onClick={run} disabled={!file || !mask} className="mt-3 rounded border border-cyan-400/20 bg-cyan-400/10 px-3 py-2 text-[10px] text-cyan-100 disabled:opacity-30">Run measured analysis</button>{result ? <ResultCards result={result} /> : null}</Panel>}</div>;
}

function ValidationTab({ activeCase, clinicalStatus, validation, setValidation, calibration, onCalibration, onFitCalibration }: { activeCase: CaseRecord; clinicalStatus: Record<string, string> | null; validation: Record<string, unknown> | null; setValidation: (v: Record<string, unknown> | null) => void; calibration: Calibration | null; onCalibration: (p: string, l: string, bins: number) => void; onFitCalibration: (p: string, l: string) => void }) {
  const [prediction, setPrediction] = useState<File | null>(null);
  const [reference, setReference] = useState<File | null>(null);
  const [cohortZip, setCohortZip] = useState<File | null>(null);
  const [probs, setProbs] = useState("0.12, 0.83, 0.54, 0.71, 0.22, 0.92, 0.40, 0.64, 0.31, 0.77");
  const [labels, setLabels] = useState("0, 1, 1, 1, 0, 1, 0, 1, 0, 1");
  const [bins, setBins] = useState(10);
  async function calculateValidation(event: React.FormEvent) {
    event.preventDefault(); if (!prediction || !reference) return;
    const form = new FormData(); form.append("prediction", prediction); form.append("reference", reference);
    try { setValidation(await api<Record<string, unknown>>(`/validation/segmentation?spacing_x=1&spacing_y=1&spacing_z=1`, { method: "POST", body: form })); } catch { setValidation({ status: "FAILED", note: "Independent prediction/reference masks could not be evaluated." }); }
  }
  async function calculateCohort() {
    if (!cohortZip) return;
    const form = new FormData(); form.append("bundle_file", cohortZip);
    try { setValidation(await api<Record<string, unknown>>("/validation/segmentation-cohort", { method: "POST", body: form })); } catch { setValidation({ status: "FAILED", note: "Cohort validation could not be evaluated." }); }
  }
  return <div className="space-y-4"><div className="grid gap-3 xl:grid-cols-3"><Metric label="Application" value={clinicalStatus?.status ?? "READY FOR RESEARCH EVALUATION"} /><Metric label="Clinical validation" value={clinicalStatus?.clinical_validation ?? "NOT ESTABLISHED"} /><Metric label="Case" value={activeCase.case_id} /></div><div className="grid gap-4 xl:grid-cols-2"><Panel title="Segmentation validation" kicker="INDEPENDENT REFERENCE"><form onSubmit={calculateValidation} className="space-y-3"><FilePicker label="Prediction mask" file={prediction} setFile={setPrediction} accept=".nii,.nii.gz" /><FilePicker label="Independent reference mask" file={reference} setFile={setReference} accept=".nii,.nii.gz" /><button disabled={!prediction || !reference} className="rounded border border-cyan-400/20 bg-cyan-400/10 px-3 py-2 text-[10px] text-cyan-100 disabled:opacity-30">Calculate Dice / IoU / HD95 / ASSD</button></form>{validation ? <ResultCards result={validation} /> : null}</Panel><Panel title="Cohort validation" kicker="INDEPENDENT CASES"><div className="text-[10px] leading-5 text-slate-500">ZIP manifest: <span className="mono text-slate-300">case_id,prediction,reference</span>. Metrics are calculated independently per case with aggregate bootstrap intervals.</div><FilePicker label="Validation cohort ZIP" file={cohortZip} setFile={setCohortZip} accept=".zip" /><button onClick={() => void calculateCohort()} disabled={!cohortZip} className="mt-3 rounded border border-cyan-400/20 bg-cyan-400/10 px-3 py-2 text-[10px] text-cyan-100 disabled:opacity-30">Run cohort validation</button></Panel></div><Panel title="Calibrated confidence evaluation" kicker="HELD-OUT RESEARCH COHORT"><div className="grid gap-3 lg:grid-cols-2"><textarea value={probs} onChange={(e) => setProbs(e.target.value)} className="min-h-24 border border-slate-800 bg-slate-950 p-2 text-[10px] text-slate-300 outline-none" /><textarea value={labels} onChange={(e) => setLabels(e.target.value)} className="min-h-24 border border-slate-800 bg-slate-950 p-2 text-[10px] text-slate-300 outline-none" /></div><div className="mt-3 flex flex-wrap gap-2"><input type="number" min={2} max={50} value={bins} onChange={(e) => setBins(Number(e.target.value))} className="h-9 w-24 border border-slate-800 bg-slate-950 px-2 text-xs text-slate-300" /><button onClick={() => onCalibration(probs, labels, bins)} className="rounded border border-slate-800 px-3 py-2 text-[10px] text-slate-300">Evaluate ECE / Brier</button><button onClick={() => onFitCalibration(probs, labels)} className="rounded border border-cyan-400/20 bg-cyan-400/10 px-3 py-2 text-[10px] text-cyan-100">Fit temperature scaling</button></div>{calibration ? <div className="mt-3 grid gap-2 sm:grid-cols-3"><Metric label="ECE" value={calibration.ece.toFixed(4)} /><Metric label="Brier" value={calibration.brier_score.toFixed(4)} /><Metric label="Samples" value={calibration.sample_count ?? "—"} /></div> : null}<div className="mt-3 text-[9px] leading-4 text-slate-600">Calibration is an empirical research procedure. It becomes applicable to a model only when the calibrator is locked to that model/version and evaluated on independent data.</div></Panel></div>;
}

function SecurityTab({ diagnostics, capabilities, roleMatrix, authUser, login, setLogin, onLogin, onLogout, users, loadUsers, newUser, setNewUser, onCreateUser, onUpdateUser }: { diagnostics: Record<string, string> | null; capabilities: Record<string, unknown> | null; roleMatrix: Record<string, unknown> | null; authUser: { username: string; role: string } | null; login: { username: string; password: string }; setLogin: React.Dispatch<React.SetStateAction<{ username: string; password: string }>>; onLogin: (event: React.FormEvent) => void; onLogout: () => void; users: Array<{ id: number; username: string; role: string; active: boolean; created_at: string }>; loadUsers: () => void; newUser: { username: string; password: string; role: string }; setNewUser: React.Dispatch<React.SetStateAction<{ username: string; password: string; role: string }>>; onCreateUser: (event: React.FormEvent) => void; onUpdateUser: (username: string, patch: { active?: boolean; role?: string }) => void }) {
  const roles = Array.isArray(roleMatrix?.roles) ? roleMatrix.roles as string[] : [];
  return <div className="space-y-4"><div className="grid gap-4 xl:grid-cols-3"><Panel title="Authentication" kicker="JWT / SESSION"><div className="grid gap-2 sm:grid-cols-2"><Metric label="Auth" value={diagnostics?.authentication ?? "—"} /><Metric label="Runtime" value="SERVER ENFORCED" /></div>{authUser ? <div className="mt-3 flex items-center justify-between rounded border border-emerald-500/15 bg-emerald-500/[.03] p-3"><div><div className="text-xs text-slate-200">{authUser.username}</div><div className="mono mt-1 text-[9px] text-slate-500">{authUser.role}</div></div><button onClick={onLogout} className="inline-flex items-center gap-2 rounded border border-slate-800 px-2 py-1 text-[9px] text-slate-500"><LogOut size={12}/>Sign out</button></div> : <form onSubmit={onLogin} className="mt-3 space-y-2"><input required value={login.username} onChange={(e) => setLogin((x) => ({ ...x, username: e.target.value }))} placeholder="Username" className="h-9 w-full border border-slate-800 bg-slate-950 px-2 text-xs text-slate-300" /><input required minLength={8} type="password" value={login.password} onChange={(e) => setLogin((x) => ({ ...x, password: e.target.value }))} placeholder="Password" className="h-9 w-full border border-slate-800 bg-slate-950 px-2 text-xs text-slate-300" /><button className="inline-flex items-center gap-2 rounded border border-cyan-400/20 bg-cyan-400/10 px-3 py-2 text-[10px] text-cyan-100"><LockKeyhole size={13}/>Sign in</button></form>}<div className="mt-3 flex flex-wrap gap-1.5">{roles.map((role) => <Badge key={role}>{role.replaceAll("_", " ")}</Badge>)}</div></Panel><Panel title="Production storage" kicker="POSTGRESQL / S3"><div className="grid gap-2 sm:grid-cols-2"><Metric label="Database" value={String(capabilities?.postgresql ?? false)} /><Metric label="Object storage" value={String(capabilities?.s3 ?? false)} /><Metric label="DICOM SEG" value={String(capabilities?.dicom_seg ?? false)} /><Metric label="DICOM SR" value={String(capabilities?.dicom_sr ?? false)} /></div><div className="mt-3 text-[9px] leading-4 text-slate-600">PostgreSQL and S3 are activated by environment configuration. Local development uses SQLite and local file storage so the project runs without external infrastructure.</div></Panel><Panel title="Administrator controls" kicker="ROLE-BASED ACCESS"><div className="text-[10px] text-slate-500">User activation/deactivation and role changes are server-authorized.</div><button onClick={loadUsers} className="mt-2 rounded border border-slate-800 px-2 py-1 text-[9px] text-slate-500"><RefreshCw size={12}/></button>{authUser?.role === "administrator" ? <><form onSubmit={onCreateUser} className="mt-3 grid gap-2 sm:grid-cols-3"><input required placeholder="Username" value={newUser.username} onChange={(e) => setNewUser((x) => ({ ...x, username: e.target.value }))} className="h-9 border border-slate-800 bg-slate-950 px-2 text-xs text-slate-300" /><input required minLength={8} type="password" placeholder="Temporary password" value={newUser.password} onChange={(e) => setNewUser((x) => ({ ...x, password: e.target.value }))} className="h-9 border border-slate-800 bg-slate-950 px-2 text-xs text-slate-300" /><select value={newUser.role} onChange={(e) => setNewUser((x) => ({ ...x, role: e.target.value }))} className="h-9 border border-slate-800 bg-slate-950 px-2 text-xs text-slate-300">{["administrator","radiologist","clinician","researcher","biomedical_engineer","technician","viewer"].map((role) => <option key={role}>{role}</option>)}</select><button className="rounded border border-cyan-400/20 bg-cyan-400/10 px-3 py-2 text-[10px] text-cyan-100 sm:col-span-3"><Users size={13} className="mr-1 inline"/>Create user</button></form><div className="mt-3 space-y-1.5">{users.map((item) => <div key={item.id} className="flex items-center gap-2 rounded border border-slate-900 bg-slate-950/40 p-2"><div className="min-w-0 flex-1"><div className="text-xs text-slate-300">{item.username}</div><div className="mono mt-1 text-[9px] text-slate-600">{item.role}</div></div><button onClick={() => onUpdateUser(item.username, { active: !item.active })} className="text-[9px] text-slate-500">{item.active ? "Deactivate" : "Activate"}</button></div>)}</div></> : null}</Panel></div></div>;
}

function ResultCards({ result }: { result: Record<string, unknown> }) {
  const top = Object.entries(result).filter(([key, value]) => ["status","note","method","framework","clinical_claim","validation_claim","clinical_validation_status"].includes(key) || typeof value === "number").slice(0, 12);
  return <div className="mt-4 space-y-3"><div className="grid gap-2 sm:grid-cols-3">{top.filter(([,v]) => typeof v === "number").slice(0, 6).map(([key, value]) => <Metric key={key} label={key.replaceAll("_", " ")} value={Number(value).toFixed(4)} />)}</div><div className="rounded border border-slate-900 bg-slate-950/40 p-3 text-[9px] leading-4 text-slate-600">{String(result.note ?? result.method ?? result.status ?? "Result measured.")}</div></div>;
}

function JobStatus({ job }: { job: Job }) { return <div className="mt-3 rounded border border-slate-900 bg-slate-950/45 p-3"><div className="flex items-center justify-between text-[9px] uppercase tracking-[.12em] text-slate-600"><span>Job {job.job_id}</span><span>{job.status}</span></div><div className="mt-2 h-1.5 overflow-hidden rounded bg-slate-900"><div className="h-full bg-cyan-300/60 transition-[width]" style={{ width: `${Math.min(100, Math.max(0, job.progress))}%` }} /></div><div className="mt-2 text-[9px] text-slate-500">{job.message}{job.error ? ` · ${job.error}` : ""}</div></div>; }
function StatusMetric({ label, value, tone }: { label: string; value: string; tone: "good" | "warn" | "neutral" }) { return <div className="rounded-lg border border-slate-900 bg-slate-950/45 p-2.5"><div className="text-[8px] uppercase tracking-[.12em] text-slate-600">{label}</div><div className={`mt-1 text-[9px] ${tone === "good" ? "text-emerald-300" : tone === "warn" ? "text-amber-300" : "text-slate-300"}`}>{value}</div></div>; }
function FieldSelect({ label, value, set, options }: { label: string; value: string; set: (value: string) => void; options: string[] }) { return <label className="text-[9px] uppercase tracking-[.12em] text-slate-600">{label}<select value={value} onChange={(e) => set(e.target.value)} className="mt-1 h-9 w-full border border-slate-800 bg-slate-950 px-2 text-xs text-slate-300">{options.map((option) => <option key={option}>{option}</option>)}</select></label>; }
function FieldNumber({ label, value, set }: { label: string; value: number; set: (value: number) => void }) { return <label className="text-[9px] uppercase tracking-[.12em] text-slate-600">{label}<input type="number" min={1} max={5} value={value} onChange={(e) => set(Number(e.target.value))} className="mt-1 h-9 w-full border border-slate-800 bg-slate-950 px-2 text-xs text-slate-300" /></label>; }
function FilePicker({ label, file, setFile, accept = ".nii,.nii.gz" }: { label: string; file: File | null; setFile: (file: File | null) => void; accept?: string }) { return <label className="block rounded border border-dashed border-slate-800 bg-slate-950/30 p-3 text-[9px] text-slate-600"><div className="uppercase tracking-[.12em]">{label}</div><input type="file" accept={accept} onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="mt-2 block w-full text-[9px] text-slate-500 file:mr-2 file:rounded file:border-0 file:bg-slate-900 file:px-2 file:py-1 file:text-[9px] file:text-slate-300" />{file ? <div className="mono mt-2 truncate text-slate-400">{file.name}</div> : null}</label>; }
function formatNumber(value: number) { return Number.isFinite(value) ? new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value) : "—"; }
