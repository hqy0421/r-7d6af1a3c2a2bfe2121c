/** Mirrors the Pydantic schemas served by the FastAPI backend. */

export interface User {
  id: number;
  email: string;
  name: string | null;
  is_demo: boolean;
  created_at: string;
}

export type MonitorState = "operational" | "degraded" | "down" | "paused" | "pending";

export interface Monitor {
  id: number;
  name: string;
  url: string;
  method: string;
  headers: Record<string, string>;
  interval_seconds: number;
  timeout_seconds: number;
  expected_status: number;
  failure_threshold: number;
  degraded_ms: number;
  enabled: boolean;
  status: MonitorState;
  consecutive_failures: number;
  last_checked_at: string | null;
  next_check_at: string | null;
  last_response_ms: number | null;
  last_error: string | null;
  created_at: string;
  uptime_24h: number | null;
  sparkline: (number | null)[];
  open_incident_id: number | null;
}

export interface UptimeWindow {
  window: string;
  checks: number;
  uptime: number | null;
  covers_from: string | null;
  partial: boolean;
}

export interface MonitorDetail extends Monitor {
  uptime: Record<string, UptimeWindow>;
  response_series: { at: string; avg_ms: number | null; checks: number; failures: number }[];
  avg_response_ms: number | null;
}

export interface Check {
  id: number;
  monitor_id: number;
  outcome: "up" | "degraded" | "down";
  status_code: number | null;
  response_ms: number | null;
  error: string | null;
  manual: boolean;
  checked_at: string;
}

export interface CheckPage {
  items: Check[];
  total: number;
  limit: number;
  offset: number;
}

export interface TimelineEntry {
  at: string;
  kind: string;
  message: string;
}

export interface Incident {
  id: number;
  monitor_id: number;
  monitor_name: string | null;
  monitor_url: string | null;
  status: "open" | "resolved";
  reason: string;
  failure_count: number;
  started_at: string;
  resolved_at: string | null;
  duration_seconds: number | null;
  timeline: TimelineEntry[];
  notes: string | null;
}

export interface IncidentPage {
  items: Incident[];
  total: number;
  limit: number;
  offset: number;
}

export interface ManualCheckResult {
  outcome: string;
  status_code: number | null;
  response_ms: number | null;
  error: string | null;
  monitor_status: MonitorState;
  checked_at: string;
}

export interface Channel {
  id: number;
  name: string;
  type: "discord" | "telegram" | "webhook";
  enabled: boolean;
  config: Record<string, string>;
  last_used_at: string | null;
  last_error: string | null;
  delivered_count: number;
  failed_count: number;
  created_at: string;
}

export interface StatusPage {
  id: number;
  slug: string;
  title: string;
  description: string | null;
  monitor_ids: number[];
  published: boolean;
  created_at: string;
}

export interface PublicStatusPage {
  slug: string;
  title: string;
  description: string | null;
  overall: "operational" | "degraded" | "major_outage" | "unknown";
  services: {
    name: string;
    status: MonitorState;
    uptime_24h: number | null;
    uptime_30d: number | null;
    last_checked_at: string | null;
  }[];
  incidents: {
    id: number;
    service: string;
    status: string;
    reason: string;
    started_at: string;
    resolved_at: string | null;
    duration_seconds: number | null;
    timeline: TimelineEntry[];
  }[];
  updated_at: string;
}

export interface Dashboard {
  monitors: number;
  operational: number;
  degraded: number;
  down: number;
  paused: number;
  pending: number;
  open_incidents: number;
  checks_24h: number;
  uptime_24h: number | null;
  avg_response_ms: number | null;
}
