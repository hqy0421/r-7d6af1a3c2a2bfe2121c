/**
 * One fetch wrapper for the app.
 *
 * The session is an HttpOnly cookie, so requests only need
 * `credentials: "include"`. The public status page is fetched on the server,
 * where there is no cookie at all — that is the point of it being public.
 */

import type {
  Channel,
  Check,
  CheckPage,
  Dashboard,
  Incident,
  IncidentPage,
  ManualCheckResult,
  Monitor,
  MonitorDetail,
  PublicStatusPage,
  StatusPage,
  User,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

interface ErrorBody {
  error?: { code?: string; message?: string; fields?: { field: string; message: string }[] };
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: init.body ? { "Content-Type": "application/json" } : undefined,
    cache: "no-store",
    ...init,
  });

  if (response.status === 204) return undefined as T;

  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const body = payload as ErrorBody | null;
    const fields = body?.error?.fields?.map((f) => `${f.field}: ${f.message}`).join("; ");
    throw new ApiError(
      response.status,
      body?.error?.code ?? "error",
      fields || body?.error?.message || response.statusText,
    );
  }
  return payload as T;
}

function query(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const api = {
  authConfig: () =>
    request<{ registration_enabled: boolean; environment: string }>("/api/auth/config"),
  me: () => request<User>("/api/auth/me"),
  login: (email: string, password: string) =>
    request<User>("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  register: (email: string, password: string, name?: string) =>
    request<User>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, name: name || null }),
    }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),

  dashboard: () => request<Dashboard>("/api/dashboard"),

  monitors: () => request<Monitor[]>("/api/monitors"),
  monitor: (id: number, hours = 24) =>
    request<MonitorDetail>(`/api/monitors/${id}${query({ hours })}`),
  createMonitor: (body: unknown) =>
    request<Monitor>("/api/monitors", { method: "POST", body: JSON.stringify(body) }),
  updateMonitor: (id: number, body: unknown) =>
    request<Monitor>(`/api/monitors/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteMonitor: (id: number) => request<void>(`/api/monitors/${id}`, { method: "DELETE" }),
  runCheck: (id: number) =>
    request<ManualCheckResult>(`/api/monitors/${id}/check`, { method: "POST" }),
  checks: (id: number, limit = 50) =>
    request<CheckPage>(`/api/monitors/${id}/checks${query({ limit })}`),
  monitorIncidents: (id: number, limit = 10) =>
    request<IncidentPage>(`/api/monitors/${id}/incidents${query({ limit })}`),

  incidents: (params: { limit?: number; offset?: number; status?: string } = {}) =>
    request<IncidentPage>(`/api/incidents${query(params)}`),
  incident: (id: number) => request<Incident>(`/api/incidents/${id}`),

  channels: () => request<Channel[]>("/api/channels"),
  channelTypes: () =>
    request<{ type: string; label: string; fields: { name: string; secret: boolean; label: string }[] }[]>(
      "/api/channels/types",
    ),
  createChannel: (body: unknown) =>
    request<Channel>("/api/channels", { method: "POST", body: JSON.stringify(body) }),
  deleteChannel: (id: number) => request<void>(`/api/channels/${id}`, { method: "DELETE" }),
  testChannel: (id: number) =>
    request<{ delivered: boolean; detail: string; channel: string }>(
      `/api/channels/${id}/test`,
      { method: "POST" },
    ),

  statusPages: () => request<StatusPage[]>("/api/status-pages"),
  createStatusPage: (body: unknown) =>
    request<StatusPage>("/api/status-pages", { method: "POST", body: JSON.stringify(body) }),
  updateStatusPage: (id: number, body: unknown) =>
    request<StatusPage>(`/api/status-pages/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteStatusPage: (id: number) =>
    request<void>(`/api/status-pages/${id}`, { method: "DELETE" }),
};

/** Fetched on the server for the public page: no cookie, no client bundle. */
export async function fetchPublicStatus(slug: string): Promise<PublicStatusPage | null> {
  const response = await fetch(`${API_BASE}/api/status/${slug}`, { cache: "no-store" });
  if (!response.ok) return null;
  return (await response.json()) as PublicStatusPage;
}

export type { Check };
