"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useAsync } from "@/hooks/use-async";
import { PageHeader } from "@/components/dashboard/shell";
import { IncidentTimeline } from "@/components/dashboard/incident-timeline";
import { Button, Card, CardHeader, EmptyState, ErrorNote, Select, Spinner, StatusBadge } from "@/components/ui";
import { absoluteTime, formatDuration, relativeTime } from "@/lib/utils";

const PAGE_SIZE = 20;

export default function IncidentsPage() {
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<number | null>(null);

  const page = useAsync(
    () => api.incidents({ limit: PAGE_SIZE, offset, status: status || undefined }),
    `incidents:${offset}:${status}`,
    20_000,
  );

  const total = page.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <>
      <PageHeader
        title="Incidents"
        description="Opened when failures reach a monitor's threshold, resolved on the first check that passes."
        actions={
          <Select
            aria-label="Filter by status"
            className="w-40"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">All incidents</option>
            <option value="open">Open</option>
            <option value="resolved">Resolved</option>
          </Select>
        }
      />

      {page.error ? <ErrorNote message={page.error} /> : null}

      <Card>
        <CardHeader title={`${total} incident${total === 1 ? "" : "s"}`} />
        {page.loading && !page.data ? <Spinner /> : null}
        {page.data && page.data.items.length === 0 ? (
          <EmptyState title="No incidents" hint="Nothing has failed often enough to open one." />
        ) : null}
        <div className="divide-y divide-[var(--color-border)]">
          {page.data?.items.map((incident) => (
            <div key={incident.id}>
              <button
                type="button"
                onClick={() => setExpanded(expanded === incident.id ? null : incident.id)}
                aria-expanded={expanded === incident.id}
                className="flex w-full flex-wrap items-center gap-3 px-5 py-3 text-left transition-colors hover:bg-[var(--color-surface-raised)]/50"
              >
                <StatusBadge status={incident.status === "open" ? "down" : "operational"} live={incident.status === "open"} />
                <span className="text-sm font-medium">{incident.monitor_name}</span>
                <span className="min-w-0 flex-1 truncate text-xs text-[var(--color-ink-muted)]">
                  {incident.reason}
                </span>
                <span className="font-mono text-[11px] text-[var(--color-ink-subtle)]">
                  {incident.status === "open"
                    ? `since ${relativeTime(incident.started_at)}`
                    : formatDuration(incident.duration_seconds)}
                </span>
              </button>
              {expanded === incident.id ? (
                <div className="border-t border-[var(--color-border)] bg-[var(--color-canvas)]/40">
                  <div className="flex flex-wrap items-center gap-4 px-5 pt-3 text-[11px] text-[var(--color-ink-muted)]">
                    <span>started {absoluteTime(incident.started_at)}</span>
                    {incident.resolved_at ? <span>resolved {absoluteTime(incident.resolved_at)}</span> : null}
                    <span>{incident.failure_count} failed checks</span>
                    <Link href={`/monitors/${incident.monitor_id}`} className="text-[var(--color-accent)] hover:underline">
                      open monitor
                    </Link>
                  </div>
                  <IncidentTimeline entries={incident.timeline} />
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </Card>

      {pages > 1 ? (
        <div className="mt-4 flex items-center justify-between text-xs text-[var(--color-ink-muted)]">
          <span>
            Page {Math.floor(offset / PAGE_SIZE) + 1} of {pages}
          </span>
          <div className="flex gap-2">
            <Button size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
              Previous
            </Button>
            <Button size="sm" disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>
              Next
            </Button>
          </div>
        </div>
      ) : null}
    </>
  );
}
