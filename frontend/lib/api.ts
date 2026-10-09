export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000/api").replace(/\/$/, "");

export class MedAxisApiError extends Error {
  constructor(message: string, public readonly status: number | null, public readonly endpoint: string) {
    super(message);
    this.name = "MedAxisApiError";
  }
}

function requestFailure(error: unknown, endpoint: string): MedAxisApiError {
  if (error instanceof MedAxisApiError) return error;
  const reason = error instanceof Error ? error.message : String(error);
  return new MedAxisApiError(
    `Cannot reach the MedAxis backend at ${API_BASE}. Start the Python FastAPI server on port 8000 and confirm /api/health is reachable. Details: ${reason}`,
    null,
    endpoint,
  );
}

async function readApiFailure(response: Response): Promise<string> {
  let detail: unknown = null;
  try { detail = await response.json(); } catch { detail = null; }
  if (detail && typeof detail === "object") {
    const object = detail as Record<string, unknown>;
    const body = object.detail && typeof object.detail === "object"
      ? object.detail as Record<string, unknown>
      : object;
    const explanation = [body.problem, body.reason, body.recommended_action]
      .filter((value): value is string => typeof value === "string" && Boolean(value.trim()));
    if (explanation.length) return explanation.join(" — ");
    if (typeof object.detail === "string") return object.detail;
    if (typeof object.message === "string") return object.message;
  }
  if (typeof detail === "string" && detail.trim()) return detail;
  return `HTTP ${response.status} ${response.statusText || "request failed"}`;
}

export type ApiHealth = {
  status: string;
  application: string;
  version: string;
  capabilities?: Record<string, boolean>;
};

export async function checkBackendHealth(): Promise<ApiHealth> {
  const endpoint = `${API_BASE}/health`;
  let response: Response;
  try {
    response = await fetch(endpoint, { cache: "no-store", signal: AbortSignal.timeout(12000) });
  } catch (error) {
    if (error instanceof Error && (error.name === "TimeoutError" || error.name === "AbortError")) {
      throw new MedAxisApiError(
        `The MedAxis backend did not answer its health check within 12 seconds at ${endpoint}. It may still be starting or may be busy. Check the Python CMD window, then open this URL directly and try Retry connection.`,
        null,
        endpoint,
      );
    }
    throw requestFailure(error, endpoint);
  }
  if (!response.ok) throw new MedAxisApiError(await readApiFailure(response), response.status, endpoint);
  const payload = await response.json() as ApiHealth;
  if (!payload || payload.status !== "ONLINE" || payload.application !== "MedAxis 3D") {
    throw new MedAxisApiError("The server returned an unexpected health response.", response.status, endpoint);
  }
  return payload;
}

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
  const endpoint = `${API_BASE}${path}`;
  let response: Response;
  try {
    response = await fetch(endpoint, { ...init, headers, cache: "no-store" });
  } catch (error) {
    throw requestFailure(error, endpoint);
  }

  if (!response.ok) throw new MedAxisApiError(await readApiFailure(response), response.status, endpoint);

  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json") || contentType.includes("text/json")) return response.json() as Promise<T>;
  return (await response.text()) as T;
}

export async function downloadEndpoint(path: string, filename: string): Promise<void> {
  const token = getAuthToken();
  const endpoint = `${API_BASE}${path}`;
  let response: Response;
  try {
    response = await fetch(endpoint, { method: "POST", headers: token ? { Authorization: `Bearer ${token}` } : {}, cache: "no-store" });
  } catch (error) {
    throw requestFailure(error, endpoint);
  }
  if (!response.ok) throw new MedAxisApiError(await readApiFailure(response), response.status, endpoint);
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
