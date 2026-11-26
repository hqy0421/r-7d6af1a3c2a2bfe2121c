import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const RELATIVE = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
const UNITS: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
  ["second", 1],
];

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "never";
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (seconds < 10) return "just now";
  for (const [unit, size] of UNITS) {
    if (seconds >= size) {
      const value = Math.round(seconds / size);
      if (unit === "day" && value > 6) break;
      return RELATIVE.format(-value, unit);
    }
  }
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function absoluteTime(iso: string | null | undefined): string {
  return iso
    ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" })
    : "—";
}

export function clockTime(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes < 60) return `${minutes}m ${String(rest).padStart(2, "0")}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${String(minutes % 60).padStart(2, "0")}m`;
}

export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(2)} s`;
}

export function formatUptime(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(value >= 99.95 ? 2 : 2)}%`;
}

export const STATUS_LABELS: Record<string, string> = {
  operational: "Operational",
  degraded: "Degraded",
  down: "Down",
  paused: "Paused",
  pending: "Pending",
};

export const STATUS_COLORS: Record<string, string> = {
  operational: "var(--color-up)",
  degraded: "var(--color-degraded)",
  down: "var(--color-down)",
  paused: "var(--color-paused)",
  pending: "var(--color-ink-subtle)",
};
