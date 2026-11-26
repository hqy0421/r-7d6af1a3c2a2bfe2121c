"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronRight, Play } from "lucide-react";
import { api } from "@/lib/api";
import type { ManualCheckResult, Monitor } from "@/lib/types";
import { Sparkline } from "@/components/dashboard/charts";
import { Button, Card, StatusBadge } from "@/components/ui";
import { cn, formatMs, formatUptime, relativeTime } from "@/lib/utils";

/**
 * One monitor at a glance — and the "Run check now" button, which performs a
 * real check against the real target and reports what came back.
 */
export function MonitorCard({ monitor, onChanged }: { monitor: Monitor; onChanged: () => void }) {
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState<ManualCheckResult | null>(null);

  const runCheck = async () => {
    setChecking(true);
    setResult(null);
    try {
      setResult(await api.runCheck(monitor.id));
      onChanged();
    } catch (error) {
      setResult({
        outcome: "down",
        status_code: null,
        response_ms: null,
        error: error instanceof Error ? error.message : String(error),
        monitor_status: monitor.status,
        checked_at: new Date().toISOString(),
      });
    } finally {
      setChecking(false);
    }
  };

  return (
    <Card className="p-4">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Link href={`/monitors/${monitor.id}`} className="truncate text-sm font-medium hover:underline">
              {monitor.name}
            </Link>
            <StatusBadge status={monitor.status} live={monitor.enabled && monitor.status === "operational"} />
          </div>
          <p className="mt-1 truncate font-mono text-[11px] text-[var(--color-ink-subtle)]">
            {monitor.method} {monitor.url}
          </p>
        </div>
        <Link
          href={`/monitors/${monitor.id}`}
          aria-label={`Open ${monitor.name}`}
          className="rounded-md p-1 text-[var(--color-ink-subtle)] transition-colors hover:text-[var(--color-ink)]"
        >
          <ChevronRight className="h-4 w-4" aria-hidden />
        </Link>
      </div>

      <div className="mt-3">
        <Sparkline values={monitor.sparkline} />
      </div>

      <dl className="mt-3 grid grid-cols-3 gap-2 text-center">
        <Stat label="Uptime 24h" value={formatUptime(monitor.uptime_24h)} />
        <Stat label="Response" value={formatMs(monitor.last_response_ms)} />
        <Stat label="Checked" value={relativeTime(monitor.last_checked_at)} />
      </dl>

      <div className="mt-3 flex items-center justify-between gap-3 border-t border-[var(--color-border)] pt-3">
        <Button size="sm" onClick={runCheck} loading={checking}>
          <Play className="h-3.5 w-3.5" aria-hidden />
          {checking ? "Checking…" : "Run check now"}
        </Button>
        <p
          aria-live="polite"
          className={cn(
            "truncate text-right font-mono text-[11px]",
            result?.outcome === "down" ? "text-[var(--color-down)]" : "text-[var(--color-ink-muted)]",
          )}
        >
          {checking
            ? "…"
            : result
              ? result.error ?? `${result.status_code} OK · ${formatMs(result.response_ms)}`
              : monitor.last_error ?? ""}
        </p>
      </div>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-canvas)] px-2 py-1.5">
      <dt className="text-[10px] uppercase tracking-wide text-[var(--color-ink-subtle)]">{label}</dt>
      <dd className="mt-0.5 font-mono text-xs tabular-nums">{value}</dd>
    </div>
  );
}
