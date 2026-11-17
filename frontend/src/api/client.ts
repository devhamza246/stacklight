import type { Approval, Chunk, DocRef, Mode, StatusInfo, Tone } from "./types";

export type ApiErrorKind =
  | "busy" | "rate_limited" | "too_many_streams" | "demo_paused" | "resetting"
  | "not_found" | "conflict" | "unprocessable" | "unavailable" | "network" | "unknown";

export class ApiError extends Error {
  constructor(
    readonly kind: ApiErrorKind,
    readonly status: number,
    message: string,
    readonly retryAfterS?: number,
    readonly resetsAt?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function retryAfter(res: Response, body: Record<string, unknown> | null, fallback: number): number {
  const fromBody = typeof body?.retry_after_s === "number" ? body.retry_after_s : NaN;
  const fromHeader = Number(res.headers.get("Retry-After"));
  const n = Number.isFinite(fromBody) ? fromBody : Number.isFinite(fromHeader) && fromHeader > 0 ? fromHeader : fallback;
  return Math.max(1, Math.ceil(n));
}

async function toError(res: Response): Promise<ApiError> {
  let body: Record<string, unknown> | null = null;
  try { body = await res.json(); } catch { /* non-JSON error body */ }
  const detail = typeof body?.detail === "string" ? body.detail : res.statusText || `HTTP ${res.status}`;
  if (res.status === 429) {
    const kind = body?.error === "busy" ? "busy" : body?.error === "too_many_streams" ? "too_many_streams" : "rate_limited";
    return new ApiError(kind, 429, "Too many requests", retryAfter(res, body, 10));
  }
  if (res.status === 503) {
    if (body?.status === "demo_paused") {
      return new ApiError("demo_paused", 503, "Demo paused", undefined, typeof body.resets_at === "string" ? body.resets_at : undefined);
    }
    if (body?.status === "resetting") return new ApiError("resetting", 503, "Resetting", retryAfter(res, body, 5));
    return new ApiError("unavailable", 503, detail);
  }
  if (res.status === 404) return new ApiError("not_found", 404, detail);
  if (res.status === 409) return new ApiError("conflict", 409, detail);
  if (res.status === 422) return new ApiError("unprocessable", 422, detail);
  return new ApiError("unknown", res.status, detail);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError("network", 0, "Could not reach the server");
  }
  if (!res.ok) throw await toError(res);
  return (await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

export const api = {
  startRun: (message: string, mode: Exclude<Mode, "curate">, tone: Tone = "support") =>
    request<{ run_id: string }>("/api/chat", json({ message, mode, tone })),
  startAudit: () => request<{ run_id: string }>("/api/curate", { method: "POST" }),
  status: () => request<StatusInfo>("/api/status"),
  approvals: (status: "pending" | "approved" | "rejected" | "all" = "pending") =>
    request<Approval[]>(`/api/approvals?status=${status}`),
  decide: (id: number, approve: boolean, reason?: string) =>
    request<Approval>(`/api/approvals/${id}/decision`, json({ approve, ...(reason ? { reason } : {}) })),
  chunk: (id: number) => request<Chunk>(`/api/chunks/${id}`),
  documents: (ids: number[]) =>
    ids.length ? request<DocRef[]>(`/api/documents?ids=${ids.join(",")}`) : Promise.resolve([] as DocRef[]),
};

export type Api = typeof api;
