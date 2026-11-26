"use client";

import { useState } from "react";
import { cn, formatMs } from "@/lib/utils";

/**
 * Two charts, drawn as inline SVG.
 *
 * A charting library would add 40–400 KB to a page whose job is to load fast
 * and show a number; these are ~120 lines, have no dependencies, scale with
 * their container, and render identically on the server.
 */

/** The strip on a monitor card: one bar per recent check. A `null` is a failed
 *  check and is drawn as a full-height red bar, whatever its latency was. */
export function Sparkline({
  values,
  className,
}: {
  values: (number | null)[];
  className?: string;
}) {
  // "Empty" means no checks at all. A monitor whose every check failed has a
  // full strip of red bars, which is exactly what it should look like.
  if (values.length === 0) {
    return (
      <div className={cn("flex h-8 items-center text-[11px] text-[var(--color-ink-subtle)]", className)}>
        no checks yet
      </div>
    );
  }

  const points = values.filter((value): value is number => value !== null);
  const max = Math.max(...points, 1);
  const width = 100;
  const height = 28;
  const gap = 0.6;
  const barWidth = width / values.length - gap;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className={cn("h-8 w-full", className)}
      role="img"
      aria-label={`Last ${values.length} checks, most recent last; failed checks in red`}
    >
      {values.map((value, index) => {
        const barHeight = value === null ? height : Math.max(1.5, (value / max) * (height - 2));
        return (
          <rect
            key={index}
            x={index * (barWidth + gap)}
            y={height - barHeight}
            width={barWidth}
            height={barHeight}
            rx="0.4"
            fill={value === null ? "var(--color-down)" : "var(--color-accent)"}
            opacity={value === null ? 0.7 : 0.55 + (index / values.length) * 0.45}
          />
        );
      })}
    </svg>
  );
}

/** Response time over the selected window, with failures marked underneath. */
export function ResponseChart({
  series,
}: {
  series: { at: string; avg_ms: number | null; checks: number; failures: number }[];
}) {
  const [hovered, setHovered] = useState<number | null>(null);
  const values = series.map((point) => point.avg_ms).filter((v): v is number => v !== null);
  const max = Math.max(1, ...values);
  const width = 100;
  const height = 34;
  const step = series.length > 1 ? width / (series.length - 1) : width;

  const path = series
    .map((point, index) => {
      if (point.avg_ms === null) return null;
      const x = index * step;
      const y = height - (point.avg_ms / max) * (height - 3) - 1;
      return { x, y };
    })
    .filter((p): p is { x: number; y: number } => p !== null);

  const line = path.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(" ");
  const area = path.length
    ? `${line} L${path[path.length - 1].x.toFixed(2)} ${height} L${path[0].x.toFixed(2)} ${height} Z`
    : "";
  const active = hovered !== null ? series[hovered] : null;

  return (
    <div className="space-y-2">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        className="h-40 w-full"
        role="img"
        aria-label="Average response time over the selected window"
      >
        <defs>
          <linearGradient id="response-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-accent)" stopOpacity="0.28" />
            <stop offset="100%" stopColor="var(--color-accent)" stopOpacity="0" />
          </linearGradient>
        </defs>

        <line x1="0" y1={height / 2} x2={width} y2={height / 2} stroke="var(--color-border)" strokeWidth="0.15" strokeDasharray="1 1" />
        {area ? <path d={area} fill="url(#response-fill)" /> : null}
        {line ? (
          <path d={line} fill="none" stroke="var(--color-accent)" strokeWidth="0.6" vectorEffect="non-scaling-stroke" />
        ) : null}

        {series.map((point, index) => (
          <g key={point.at} onMouseEnter={() => setHovered(index)} onMouseLeave={() => setHovered(null)}>
            <rect x={index * step - step / 2} y={0} width={step} height={height} fill="transparent" />
            {point.failures > 0 ? (
              <rect
                x={index * step - step / 2}
                y={height - 1.6}
                width={step}
                height={1.6}
                fill="var(--color-down)"
              />
            ) : null}
          </g>
        ))}
      </svg>

      <div className="flex items-center justify-between text-[11px] text-[var(--color-ink-subtle)]">
        <span>{formatHour(series[0]?.at)}</span>
        <span className="text-[var(--color-ink-muted)]">
          {active
            ? `${formatHour(active.at)} · ${active.avg_ms === null ? "no data" : formatMs(active.avg_ms)}` +
              (active.failures ? ` · ${active.failures} failed` : "")
            : `peak ${formatMs(max)}`}
        </span>
        <span>now</span>
      </div>
    </div>
  );
}

function formatHour(iso: string | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}
