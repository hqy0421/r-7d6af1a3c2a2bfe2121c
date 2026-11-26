"use client";

import { useState } from "react";
import { Bell, Plus, Send, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { useAsync } from "@/hooks/use-async";
import { PageHeader } from "@/components/dashboard/shell";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorNote,
  Field,
  Input,
  Select,
  Spinner,
} from "@/components/ui";
import { relativeTime } from "@/lib/utils";

type ChannelType = "discord" | "telegram" | "webhook";

const FIELDS: Record<ChannelType, { name: string; label: string; secret: boolean; placeholder: string }[]> = {
  discord: [{ name: "webhook_url", label: "Webhook URL", secret: true, placeholder: "https://discord.com/api/webhooks/…" }],
  telegram: [
    { name: "bot_token", label: "Bot token", secret: true, placeholder: "123456:ABC-DEF…" },
    { name: "chat_id", label: "Chat ID", secret: false, placeholder: "-1001234567890" },
  ],
  webhook: [{ name: "url", label: "Endpoint URL", secret: true, placeholder: "https://example.com/alerts" }],
};

export default function ChannelsPage() {
  const channels = useAsync(() => api.channels(), "channels");
  const [creating, setCreating] = useState(false);
  const [type, setType] = useState<ChannelType>("discord");
  const [name, setName] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [testResult, setTestResult] = useState<Record<number, string>>({});

  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.createChannel({ name, type, config: values });
      setCreating(false);
      setName("");
      setValues({});
      channels.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const test = async (id: number) => {
    setTestResult((current) => ({ ...current, [id]: "Sending…" }));
    try {
      const result = await api.testChannel(id);
      setTestResult((current) => ({ ...current, [id]: result.detail }));
    } catch (err) {
      setTestResult((current) => ({
        ...current,
        [id]: err instanceof Error ? err.message : String(err),
      }));
    }
    channels.reload();
  };

  return (
    <>
      <PageHeader
        title="Alert channels"
        description="Where PulseWatch sends a notification when a monitor goes down and when it recovers."
        actions={
          <Button variant="primary" size="sm" onClick={() => setCreating((value) => !value)}>
            <Plus className="h-3.5 w-3.5" aria-hidden />
            Add channel
          </Button>
        }
      />

      {channels.error ? <ErrorNote message={channels.error} /> : null}

      {creating ? (
        <Card className="mb-4">
          <CardHeader title="New channel" description="Credentials are encrypted before they are stored and never returned." />
          <CardBody>
            <form onSubmit={create} className="space-y-4">
              {error ? <ErrorNote message={error} /> : null}
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Name" htmlFor="channel-name">
                  <Input
                    id="channel-name"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder="Ops channel"
                    required
                  />
                </Field>
                <Field label="Type" htmlFor="channel-type">
                  <Select
                    id="channel-type"
                    value={type}
                    onChange={(event) => {
                      setType(event.target.value as ChannelType);
                      setValues({});
                    }}
                  >
                    <option value="discord">Discord webhook</option>
                    <option value="telegram">Telegram bot</option>
                    <option value="webhook">Generic webhook</option>
                  </Select>
                </Field>
              </div>

              {FIELDS[type].map((field) => (
                <Field key={field.name} label={field.label} htmlFor={`channel-${field.name}`}>
                  <Input
                    id={`channel-${field.name}`}
                    type={field.secret ? "password" : "text"}
                    value={values[field.name] ?? ""}
                    onChange={(event) =>
                      setValues((current) => ({ ...current, [field.name]: event.target.value }))
                    }
                    placeholder={field.placeholder}
                    required
                  />
                </Field>
              ))}

              <div className="flex justify-end gap-2">
                <Button type="button" variant="ghost" onClick={() => setCreating(false)}>
                  Cancel
                </Button>
                <Button type="submit" variant="primary" loading={busy} disabled={!name}>
                  Add channel
                </Button>
              </div>
            </form>
          </CardBody>
        </Card>
      ) : null}

      <Card>
        <CardHeader title="Your channels" />
        {channels.loading && !channels.data ? <Spinner /> : null}
        {channels.data && channels.data.length === 0 ? (
          <EmptyState
            title="No alert channels"
            hint="Without one, incidents are still recorded — you just will not be told about them."
          />
        ) : null}
        <div className="divide-y divide-[var(--color-border)]">
          {channels.data?.map((channel) => (
            <div key={channel.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
              <Bell className="h-4 w-4 shrink-0 text-[var(--color-ink-subtle)]" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">
                  {channel.name}
                  <span className="ml-2 text-[11px] text-[var(--color-ink-subtle)]">{channel.type}</span>
                </p>
                <p className="truncate font-mono text-[11px] text-[var(--color-ink-subtle)]">
                  {Object.entries(channel.config)
                    .map(([key, value]) => `${key}: ${value}`)
                    .join("  ")}
                </p>
              </div>
              <div className="text-right text-[11px] text-[var(--color-ink-muted)]">
                <p>
                  {channel.delivered_count} delivered · {channel.failed_count} failed
                </p>
                <p className="text-[var(--color-ink-subtle)]">
                  {testResult[channel.id] ?? (channel.last_error ?? `used ${relativeTime(channel.last_used_at)}`)}
                </p>
              </div>
              <div className="flex gap-1">
                <Button size="sm" onClick={() => test(channel.id)}>
                  <Send className="h-3.5 w-3.5" aria-hidden />
                  Test
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Delete ${channel.name}`}
                  onClick={async () => {
                    if (!confirm(`Delete "${channel.name}"?`)) return;
                    await api.deleteChannel(channel.id).catch(() => undefined);
                    channels.reload();
                  }}
                >
                  <Trash2 className="h-3.5 w-3.5" aria-hidden />
                </Button>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </>
  );
}
