"use client";

import { useState } from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, Gauge, Plus, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { useAsync } from "@/hooks/use-async";
import { PageHeader } from "@/components/dashboard/shell";
import { MonitorCard } from "@/components/dashboard/monitor-card";
import { MonitorForm } from "@/components/dashboard/monitor-form";
import { Button, Card, CardHeader, EmptyState, ErrorNote, Spinner, StatusDot } from "@/components/ui";
import { cn, formatMs, formatUptime, relativeTime } from "@/lib/utils";

/** The dashboard polls: a monitoring tool that needs a refresh button is not
 *  really monitoring anything. */
const POLL_MS = 10_000;

export default function OverviewPage() {
  const [creating, setCreating] = useState(false);
  const dashboard = useAsync(() => api.dashboard(), "dashboard", POLL_MS);
  const monitors = useAsync(() => api.monitors(), "monitors", POLL_MS);
  const incidents = useAsync(() => api.incidents({ status: "open", limit: 5 }), "open-incidents", POLL_MS);

  const summary = dashboard.data;
  const allGood = summary ? summary.open_incidents === 0 && summary.down === 0 : false;

  return (
    <>
      <PageHeader
        title="Overview"
        description="Every figure is computed from stored checks — nothing here is estimated."
        actions={
          <Button variant="primary" size="sm" onClick={() => setCreating((value) => !value)}>
            <Plus className="h-3.5 w-3.5" aria-hidden />
            New monitor
          </Button>
        }
      />

      {dashboard.error ? <ErrorNote message={dashboard.error} /> : null}

      {summary ? (
        <div
          className={cn(
            "mb-4 flex flex-wrap items-center justify-between gap-4 rounded-xl border px-5 py-4",
            allGood
              ? "border-[#1f5241] bg-[#0c1f18]"
              : "border-[#4a2630] bg-[#1c1014]",
          )}
        >
          <div className="flex items-center gap-3">
            {allGood ? (
              <ShieldCheck className="h-5 w-5 text-[var(--color-up)]" aria-hidden />
            ) : (
              <AlertTriangle className="h-5 w-5 text-[var(--color-down)]" aria-hidden />
            )}
            <div>
              <p className={cn("text-sm font-semibold", allGood ? "text-[var(--color-up)]" : "text-[var(--color-down)]")}>
                {allGood
                  ? "All systems operational"
                  : `${summary.open_incidents} active incident${summary.open_incidents === 1 ? "" : "s"}`}
              </p>
              <p className="mt-0.5 text-xs text-[var(--color-ink-muted)]">
                {summary.monitors} monitors · {summary.checks_24h.toLocaleString("en-US")} checks in the
                last 24h
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-4 text-xs text-[var(--color-ink-muted)]">
            <span className="flex items-center gap-1.5">
              <StatusDot status="operational" /> {summary.operational} operational
            </span>
            <span className="flex items-center gap-1.5">
              <StatusDot status="degraded" /> {summary.degraded} degraded
            </span>
            <span className="flex items-center gap-1.5">
              <StatusDot status="down" /> {summary.down} down
            </span>
          </div>
        </div>
      ) : null}

      {summary ? (
        <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Tile label="Monitors" value={String(summary.monitors)} hint={`${summary.paused} paused`} icon={<Gauge className="h-3 w-3" aria-hidden />} />
          <Tile label="Uptime 24h" value={formatUptime(summary.uptime_24h)} hint={`${summary.checks_24h} checks`} icon={<CheckCircle2 className="h-3 w-3" aria-hidden />} />
          <Tile label="Avg response" value={formatMs(summary.avg_response_ms)} hint="last 24 hours" />
          <Tile label="Open incidents" value={String(summary.open_incidents)} hint={summary.down ? `${summary.down} down now` : "none active"} />
        </div>
      ) : null}

      {incidents.data && incidents.data.items.length > 0 ? (
        <Card className="mb-4 border-[#4a2630]">
          <CardHeader
            title="Active incidents"
            action={
              <Link href="/incidents" className="text-xs text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]">
                All incidents
              </Link>
            }
          />
          <div className="divide-y divide-[var(--color-border)]">
            {incidents.data.items.map((incident) => (
              <Link
                key={incident.id}
                href={`/monitors/${incident.monitor_id}`}
                className="flex flex-wrap items-center gap-3 px-5 py-3 transition-colors hover:bg-[var(--color-surface-raised)]/50"
              >
                <StatusDot status="down" live />
                <span className="text-sm font-medium">{incident.monitor_name}</span>
                <span className="min-w-0 flex-1 truncate text-xs text-[var(--color-ink-muted)]">
                  {incident.reason}
                </span>
                <span className="font-mono text-[11px] text-[var(--color-ink-subtle)]">
                  since {relativeTime(incident.started_at)}
                </span>
              </Link>
            ))}
          </div>
        </Card>
      ) : null}

      {creating ? (
        <Card className="mb-4">
          <CardHeader title="New monitor" description="It starts checking as soon as it is created." />
          <MonitorForm
            onCancel={() => setCreating(false)}
            onCreated={() => {
              setCreating(false);
              monitors.reload();
              dashboard.reload();
            }}
          />
        </Card>
      ) : null}

      {monitors.loading && !monitors.data ? <Spinner label="Loading monitors" /> : null}

      {monitors.data && monitors.data.length === 0 && !creating ? (
        <Card>
          <EmptyState
            title="No monitors yet"
            hint="Add a URL and PulseWatch starts checking it on a schedule, recording every result."
            action={
              <Button variant="primary" size="sm" onClick={() => setCreating(true)}>
                Add your first monitor
              </Button>
            }
          />
        </Card>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2">
        {monitors.data?.map((monitor) => (
          <MonitorCard
            key={monitor.id}
            monitor={monitor}
            onChanged={() => {
              monitors.reload();
              dashboard.reload();
            }}
          />
        ))}
      </div>
    </>
  );
}

function Tile({
  label,
  value,
  hint,
  icon,
}: {
  label: string;
  value: string;
  hint?: string;
  icon?: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3">
      <p className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-[var(--color-ink-subtle)]">
        {icon}
        {label}
      </p>
      <p className="mt-1 font-mono text-xl tabular-nums">{value}</p>
      {hint ? <p className="mt-0.5 text-[11px] text-[var(--color-ink-muted)]">{hint}</p> : null}
    </div>
  );
}
