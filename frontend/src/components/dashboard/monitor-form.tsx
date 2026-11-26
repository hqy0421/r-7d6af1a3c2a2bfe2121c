"use client";

import { useState } from "react";
import { api, API_BASE } from "@/lib/api";
import { Button, CardBody, ErrorNote, Field, Input, Select } from "@/components/ui";

const PRESETS = [
  { label: "Demo · healthy", path: "/demo/healthy" },
  { label: "Demo · slow", path: "/demo/slow?seconds=1.8" },
  { label: "Demo · failing", path: "/demo/error" },
  { label: "Demo · flaky", path: "/demo/flaky" },
];

/** Creating a monitor is four fields; the rest have sensible defaults. */
export function MonitorForm({ onCreated, onCancel }: { onCreated: () => void; onCancel: () => void }) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [method, setMethod] = useState("GET");
  const [interval, setInterval] = useState(60);
  const [expected, setExpected] = useState(200);
  const [timeout, setTimeoutSeconds] = useState(10);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.createMonitor({
        name,
        url,
        method,
        interval_seconds: interval,
        expected_status: expected,
        timeout_seconds: timeout,
      });
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSaving(false);
    }
  };

  return (
    <CardBody>
      <form onSubmit={submit} className="space-y-4">
        {error ? <ErrorNote message={error} /> : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name" htmlFor="monitor-name">
            <Input
              id="monitor-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Production API"
              maxLength={80}
              required
            />
          </Field>
          <Field label="URL" htmlFor="monitor-url" hint="Public hosts only — private addresses are refused.">
            <Input
              id="monitor-url"
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://api.example.com/health"
              required
            />
          </Field>
        </div>

        <div className="grid gap-4 sm:grid-cols-4">
          <Field label="Method" htmlFor="monitor-method">
            <Select id="monitor-method" value={method} onChange={(event) => setMethod(event.target.value)}>
              {["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"].map((item) => (
                <option key={item}>{item}</option>
              ))}
            </Select>
          </Field>
          <Field label="Interval (s)" htmlFor="monitor-interval">
            <Input
              id="monitor-interval"
              type="number"
              min={10}
              max={86400}
              value={interval}
              onChange={(event) => setInterval(Number(event.target.value))}
            />
          </Field>
          <Field label="Expected status" htmlFor="monitor-expected">
            <Input
              id="monitor-expected"
              type="number"
              min={100}
              max={599}
              value={expected}
              onChange={(event) => setExpected(Number(event.target.value))}
            />
          </Field>
          <Field label="Timeout (s)" htmlFor="monitor-timeout">
            <Input
              id="monitor-timeout"
              type="number"
              min={1}
              max={60}
              value={timeout}
              onChange={(event) => setTimeoutSeconds(Number(event.target.value))}
            />
          </Field>
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t border-[var(--color-border)] pt-4">
          <span className="text-[11px] text-[var(--color-ink-subtle)]">Try a bundled target:</span>
          {PRESETS.map((preset) => (
            <button
              key={preset.path}
              type="button"
              onClick={() => {
                setUrl(`${API_BASE}${preset.path}`);
                if (!name) setName(preset.label.replace("Demo · ", "Demo "));
              }}
              className="rounded-md border border-[var(--color-border)] px-2 py-1 text-[11px] text-[var(--color-ink-muted)] transition-colors hover:border-[var(--color-border-strong)] hover:text-[var(--color-ink)]"
            >
              {preset.label}
            </button>
          ))}
        </div>

        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={saving} disabled={!name || !url}>
            Create monitor
          </Button>
        </div>
      </form>
    </CardBody>
  );
}
