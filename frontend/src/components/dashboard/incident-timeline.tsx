import { AlertTriangle, Bell, CheckCircle2, Circle } from "lucide-react";
import type { TimelineEntry } from "@/lib/types";
import { clockTime } from "@/lib/utils";

const ICONS: Record<string, { icon: typeof Circle; color: string }> = {
  detected: { icon: AlertTriangle, color: "var(--color-down)" },
  failing: { icon: Circle, color: "var(--color-degraded)" },
  notified: { icon: Bell, color: "var(--color-accent)" },
  resolved: { icon: CheckCircle2, color: "var(--color-up)" },
};

/** The incident, in order: detected → failing checks → alerted → recovered. */
export function IncidentTimeline({ entries }: { entries: TimelineEntry[] }) {
  if (entries.length === 0) {
    return <p className="px-5 py-4 text-xs text-[var(--color-ink-muted)]">No timeline entries.</p>;
  }

  return (
    <ol className="relative space-y-3 px-5 py-4">
      <span
        className="absolute top-6 bottom-6 left-[1.55rem] w-px bg-[var(--color-border)]"
        aria-hidden
      />
      {entries.map((entry, index) => {
        const { icon: Icon, color } = ICONS[entry.kind] ?? ICONS.failing;
        return (
          <li key={`${entry.at}-${index}`} className="relative flex gap-3">
            <span
              className="z-10 mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border bg-[var(--color-canvas)]"
              style={{ borderColor: `${color}66` }}
            >
              <Icon className="h-3 w-3" style={{ color }} aria-hidden />
            </span>
            <div className="min-w-0">
              <p className="font-mono text-[11px] text-[var(--color-ink-subtle)]">
                {clockTime(entry.at)}
              </p>
              <p className="text-xs text-[var(--color-ink)]">{entry.message}</p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
