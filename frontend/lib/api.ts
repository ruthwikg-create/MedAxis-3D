export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/api").replace(/\/$/, "");

export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("medaxis_access_token");
}

export function setAuthToken(token: string) {
  if (typeof window !== "undefined") window.localStorage.setItem("medaxis_access_token", token);
}

export function clearAuthToken() {
  if (typeof window !== "undefined") window.localStorage.removeItem("medaxis_access_token");
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAuthToken();
  const headers: HeadersInit = {
    Accept: "application/json",
    ...(init?.headers ?? {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(init?.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
  };
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers, cache: "no-store" });

  if (!response.ok) {
    let detail: unknown = null;
    try { detail = await response.json(); } catch { try { detail = await response.text(); } catch { detail = null; } }
    let message = `Request failed with HTTP ${response.status}.`;
    if (typeof detail === "string" && detail.trim()) message = detail;
    else if (detail && typeof detail === "object") {
      const object = detail as Record<string, unknown>;
      const problem = typeof object.problem === "string" ? object.problem : "Request failed";
      const reason = typeof object.reason === "string" ? object.reason : "";
      const action = typeof object.recommended_action === "string" ? object.recommended_action : "";
      message = [problem, reason, action].filter(Boolean).join(" — ");
      if (!message) message = JSON.stringify(detail);
    }
    throw new Error(message);
  }

  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json") || contentType.includes("text/json")) return response.json() as Promise<T>;
  return (await response.text()) as T;
}

export async function downloadEndpoint(path: string, filename: string): Promise<void> {
  const token = getAuthToken();
  const response = await fetch(`${API_BASE}${path}`, { method: "POST", headers: token ? { Authorization: `Bearer ${token}` } : {}, cache: "no-store" });
  if (!response.ok) {
    let detail = "Download failed.";
    try {
      const json = await response.json();
      if (json && typeof json === "object") detail = [json.problem, json.reason, json.recommended_action].filter(Boolean).join(" — ") || detail;
    } catch { /* keep fallback */ }
    throw new Error(detail);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function viewerUrl(caseId: string, plane: string, index: number, wl?: number | null, ww?: number | null) {
  const query = new URLSearchParams({ plane, index: String(Math.max(0, Math.floor(index))) });
  if (wl != null && Number.isFinite(wl)) query.set("wl", String(wl));
  if (ww != null && Number.isFinite(ww)) query.set("ww", String(ww));
  return `${API_BASE}/viewer/${encodeURIComponent(caseId)}/slice?${query.toString()}`;
}
