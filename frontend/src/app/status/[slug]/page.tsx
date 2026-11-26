import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { AlertTriangle, CheckCircle2, MinusCircle } from "lucide-react";
import { fetchPublicStatus } from "@/lib/api";
import { AutoRefresh } from "@/components/status/auto-refresh";
import { IncidentTimeline } from "@/components/dashboard/incident-timeline";
import { StatusDot } from "@/components/ui";
import { absoluteTime, formatDuration, formatUptime, relativeTime, STATUS_LABELS } from "@/lib/utils";

/** Rendered on the server on every request: a status page must never serve a
 *  cached "all good" while something is on fire. */
export const dynamic = "force-dynamic";

const OVERALL = {
  operational: {
    title: "All systems operational",
    icon: CheckCircle2,
    color: "var(--color-up)",
    border: "#1f5241",
    background: "#0c1f18",
  },
  degraded: {
    title: "Degraded performance",
    icon: AlertTriangle,
    color: "var(--color-degraded)",
    border: "#5a4520",
    background: "#1e1809",
  },
  major_outage: {
    title: "Major outage",
    icon: AlertTriangle,
    color: "var(--color-down)",
    border: "#4a2630",
    background: "#1c1014",
  },
  unknown: {
    title: "Status unknown",
    icon: MinusCircle,
    color: "var(--color-ink-muted)",
    border: "#2a3040",
    background: "#0f1218",
  },
} as const;

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const page = await fetchPublicStatus(slug);
  if (!page) return { title: "Status page not found" };
  return {
    title: `${page.title} status`,
    description: page.description ?? `Live availability for ${page.title}.`,
    openGraph: { title: `${page.title} status`, description: page.description ?? undefined },
  };
}

export default async function StatusPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const page = await fetchPublicStatus(slug);
  if (!page) notFound();

  const overall = OVERALL[page.overall] ?? OVERALL.unknown;
  const Icon = overall.icon;

  return (
    <main id="main" className="min-h-screen">
      <div className="relative border-b border-[var(--color-border)]">
        <div className="pointer-events-none absolute inset-0 bg-grid opacity-70" aria-hidden />
        <div className="relative mx-auto w-full max-w-3xl px-5 py-12 sm:px-8">
          <h1 className="text-xl font-semibold tracking-tight">{page.title}</h1>
          {page.description ? (
            <p className="mt-1.5 text-sm text-[var(--color-ink-muted)]">{page.description}</p>
          ) : null}

          <div
            className="mt-6 flex flex-wrap items-center justify-between gap-4 rounded-xl border px-5 py-4"
            style={{ borderColor: overall.border, backgroundColor: overall.background }}
          >
            <div className="flex items-center gap-3">
              <Icon className="h-5 w-5" style={{ color: overall.color }} aria-hidden />
              <p className="text-sm font-semibold" style={{ color: overall.color }}>
                {overall.title}
              </p>
            </div>
            <AutoRefresh />
          </div>
        </div>
      </div>

      <div className="mx-auto w-full max-w-3xl px-5 py-10 sm:px-8">
        <section aria-labelledby="services">
          <h2 id="services" className="mb-3 text-xs font-semibold tracking-wide text-[var(--color-ink-subtle)] uppercase">
            Services
          </h2>
          <div className="overflow-hidden rounded-xl border border-[var(--color-border)]">
            {page.services.length === 0 ? (
              <p className="px-5 py-6 text-sm text-[var(--color-ink-muted)]">
                No services are listed on this page yet.
              </p>
            ) : null}
            {page.services.map((service) => (
              <div
                key={service.name}
                className="flex flex-wrap items-center gap-3 border-b border-[var(--color-border)] px-5 py-3.5 last:border-0"
              >
                <StatusDot status={service.status} live={service.status === "operational"} />
                <span className="min-w-0 flex-1 truncate text-sm font-medium">{service.name}</span>
                <span className="text-xs" style={{ color: `var(--color-${service.status === "operational" ? "up" : service.status === "degraded" ? "degraded" : service.status === "down" ? "down" : "paused"})` }}>
                  {STATUS_LABELS[service.status] ?? service.status}
                </span>
                <span className="hidden font-mono text-[11px] text-[var(--color-ink-subtle)] sm:block">
                  {formatUptime(service.uptime_30d)} · 30d
                </span>
              </div>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-[var(--color-ink-subtle)]">
            Uptime is calculated from recorded checks. A short history reports the period it
            actually covers rather than a rounded 100%.
          </p>
        </section>

        <section aria-labelledby="incidents" className="mt-10">
          <h2 id="incidents" className="mb-3 text-xs font-semibold tracking-wide text-[var(--color-ink-subtle)] uppercase">
            Recent incidents
          </h2>
          {page.incidents.length === 0 ? (
            <div className="rounded-xl border border-[var(--color-border)] px-5 py-6 text-sm text-[var(--color-ink-muted)]">
              No incidents in the last 14 days.
            </div>
          ) : (
            <div className="space-y-3">
              {page.incidents.map((incident) => (
                <article key={incident.id} className="rounded-xl border border-[var(--color-border)]">
                  <header className="flex flex-wrap items-center gap-3 border-b border-[var(--color-border)] px-5 py-3">
                    <StatusDot status={incident.status === "open" ? "down" : "operational"} live={incident.status === "open"} />
                    <span className="text-sm font-medium">{incident.service}</span>
                    <span className="min-w-0 flex-1 truncate text-xs text-[var(--color-ink-muted)]">
                      {incident.reason}
                    </span>
                    <span className="font-mono text-[11px] text-[var(--color-ink-subtle)]">
                      {incident.status === "open"
                        ? `ongoing · started ${relativeTime(incident.started_at)}`
                        : `resolved · ${formatDuration(incident.duration_seconds)}`}
                    </span>
                  </header>
                  <IncidentTimeline entries={incident.timeline} />
                </article>
              ))}
            </div>
          )}
        </section>

        <footer className="mt-12 flex flex-wrap items-center justify-between gap-2 border-t border-[var(--color-border)] pt-6 text-[11px] text-[var(--color-ink-subtle)]">
          <span>Last updated {absoluteTime(page.updated_at)}</span>
          <span>Monitored with PulseWatch</span>
        </footer>
      </div>
    </main>
  );
}
