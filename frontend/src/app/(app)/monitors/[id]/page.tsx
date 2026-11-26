"use client";

import { use, useState } from "react";
import { Pause, Play, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAsync } from "@/hooks/use-async";
import { PageHeader } from "@/components/dashboard/shell";
import { ResponseChart, Sparkline } from "@/components/dashboard/charts";
import { IncidentTimeline } from "@/components/dashboard/incident-timeline";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorNote,
  Spinner,
  StatusBadge,
} from "@/components/ui";
import { absoluteTime, clockTime, formatDuration, formatMs, formatUptime, relativeTime } from "@/lib/utils";

export default function MonitorDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const monitorId = Number(id);
  const router = useRouter();

  const monitor = useAsync(() => api.monitor(monitorId), `monitor:${monitorId}`, 15_000);
  const checks = useAsync(() => api.checks(monitorId, 25), `checks:${monitorId}`, 15_000);
  const incidents = useAsync(() => api.monitorIncidents(monitorId, 10), `incidents:${monitorId}`);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastRun, setLastRun] = useState<string | null>(null);

  if (monitor.loading && !monitor.data) return <Spinner label="Loading monitor" />;
  if (monitor.error) return <ErrorNote message={monitor.error} />;
  if (!monitor.data) return null;

  const detail = monitor.data;

  const act = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      monitor.reload();
      checks.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const runCheck = async () => {
    setBusy(true);
    setError(null);
    setLastRun("Checking…");
    try {
      const result = await api.runCheck(monitorId);
      setLastRun(
        result.error
          ? `${result.outcome.toUpperCase()} — ${result.error}`
          : `${result.status_code} OK · ${formatMs(result.response_ms)}`,
      );
      monitor.reload();
      checks.reload();
      incidents.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setLastRun(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader
        title={detail.name}
        description={`${detail.method} ${detail.url}`}
        back={{ href: "/", label: "Overview" }}
        actions={
          <>
            <Button size="sm" onClick={runCheck} loading={busy}>
              <Play className="h-3.5 w-3.5" aria-hidden />
              Run check now
            </Button>
            <Button
              size="sm"
              onClick={() => act(() => api.updateMonitor(monitorId, { enabled: !detail.enabled }))}
            >
              {detail.enabled ? <Pause className="h-3.5 w-3.5" aria-hidden /> : <Play className="h-3.5 w-3.5" aria-hidden />}
              {detail.enabled ? "Pause" : "Resume"}
            </Button>
            <Button
              size="sm"
              variant="danger"
              onClick={async () => {
                if (!confirm(`Delete "${detail.name}" and its history?`)) return;
                await act(() => api.deleteMonitor(monitorId));
                router.push("/");
              }}
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden />
            </Button>
          </>
        }
      />

      {error ? (
        <div className="mb-4">
          <ErrorNote message={error} />
        </div>
      ) : null}

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <StatusBadge status={detail.status} live={detail.enabled && detail.status === "operational"} />
        <span className="text-xs text-[var(--color-ink-muted)]">
          checked {relativeTime(detail.last_checked_at)} · next {relativeTime(detail.next_check_at)}
        </span>
        {lastRun ? (
          <span aria-live="polite" className="font-mono text-[11px] text-[var(--color-ink)]">
            {lastRun}
          </span>
        ) : null}
      </div>

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {(["24h", "7d", "30d"] as const).map((window) => {
          const value = detail.uptime[window];
          return (
            <div key={window} className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3">
              <p className="text-[10px] uppercase tracking-wide text-[var(--color-ink-subtle)]">
                Uptime {window}
              </p>
              <p className="mt-1 font-mono text-xl tabular-nums">{formatUptime(value?.uptime)}</p>
              <p className="mt-0.5 text-[11px] text-[var(--color-ink-muted)]">
                {value?.checks ?? 0} checks{value?.partial ? " · partial window" : ""}
              </p>
            </div>
          );
        })}
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3">
          <p className="text-[10px] uppercase tracking-wide text-[var(--color-ink-subtle)]">Avg response</p>
          <p className="mt-1 font-mono text-xl tabular-nums">{formatMs(detail.avg_response_ms)}</p>
          <p className="mt-0.5 text-[11px] text-[var(--color-ink-muted)]">last 24 hours</p>
        </div>
      </div>

      <Card className="mb-4">
        <CardHeader title="Response time" description="Average per bucket over the last 24 hours; failures marked in red." />
        <CardBody>
          <ResponseChart series={detail.response_series} />
        </CardBody>
      </Card>

      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader title="Recent checks" description={`${checks.data?.total ?? 0} recorded`} />
          {checks.loading && !checks.data ? (
            <Spinner />
          ) : checks.data && checks.data.items.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[26rem] text-left text-sm">
                <thead>
                  <tr className="text-[11px] uppercase tracking-wide text-[var(--color-ink-subtle)]">
                    <th className="px-5 py-2.5 font-medium">Time</th>
                    <th className="px-5 py-2.5 font-medium">Outcome</th>
                    <th className="px-5 py-2.5 font-medium">Status</th>
                    <th className="px-5 py-2.5 text-right font-medium">Response</th>
                  </tr>
                </thead>
                <tbody>
                  {checks.data.items.map((check) => (
                    <tr key={check.id} className="border-t border-[var(--color-border)]">
                      <td className="px-5 py-2 font-mono text-[11px] text-[var(--color-ink-muted)]" title={absoluteTime(check.checked_at)}>
                        {clockTime(check.checked_at)}
                        {check.manual ? <span className="ml-1.5 text-[var(--color-ink-subtle)]">manual</span> : null}
                      </td>
                      <td className="px-5 py-2">
                        <StatusBadge status={check.outcome === "up" ? "operational" : check.outcome === "degraded" ? "degraded" : "down"} />
                      </td>
                      <td className="px-5 py-2 font-mono text-[11px] text-[var(--color-ink-muted)]">
                        {check.status_code ?? check.error ?? "—"}
                      </td>
                      <td className="px-5 py-2 text-right font-mono text-[11px] tabular-nums">
                        {formatMs(check.response_ms)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="No checks recorded yet" hint="The first scheduled check runs within one interval." />
          )}
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader title="Configuration" />
          <CardBody className="space-y-2 text-xs">
            <Row label="Interval">every {detail.interval_seconds}s</Row>
            <Row label="Timeout">{detail.timeout_seconds}s</Row>
            <Row label="Expected status">{detail.expected_status}</Row>
            <Row label="Failure threshold">{detail.failure_threshold} checks</Row>
            <Row label="Degraded above">{detail.degraded_ms} ms</Row>
            <Row label="Created">{absoluteTime(detail.created_at)}</Row>
            <div className="pt-2">
              <p className="mb-1.5 text-[11px] uppercase tracking-wide text-[var(--color-ink-subtle)]">
                Recent response times
              </p>
              <Sparkline values={detail.sparkline} />
            </div>
          </CardBody>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader title="Incidents" description={`${incidents.data?.total ?? 0} recorded for this monitor`} />
        {incidents.data && incidents.data.items.length > 0 ? (
          <div className="divide-y divide-[var(--color-border)]">
            {incidents.data.items.map((incident) => (
              <div key={incident.id}>
                <div className="flex flex-wrap items-center gap-3 px-5 py-3">
                  <StatusBadge status={incident.status === "open" ? "down" : "operational"} />
                  <span className="min-w-0 flex-1 truncate text-sm">{incident.reason}</span>
                  <span className="font-mono text-[11px] text-[var(--color-ink-subtle)]">
                    {absoluteTime(incident.started_at)} · {formatDuration(incident.duration_seconds)}
                  </span>
                </div>
                <IncidentTimeline entries={incident.timeline} />
              </div>
            ))}
          </div>
        ) : (
          <EmptyState title="No incidents" hint="Nothing has failed often enough to open one." />
        )}
      </Card>
    </>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-[var(--color-border)] pb-2 last:border-0">
      <span className="text-[var(--color-ink-subtle)]">{label}</span>
      <span className="text-right font-mono">{children}</span>
    </div>
  );
}
