"use client";

import { useState } from "react";
import { ExternalLink, Globe, Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { useAsync } from "@/hooks/use-async";
import { PageHeader } from "@/components/dashboard/shell";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  CodeBlock,
  EmptyState,
  ErrorNote,
  Field,
  Input,
  Spinner,
  Toggle,
} from "@/components/ui";

export default function StatusPagesPage() {
  const pages = useAsync(() => api.statusPages(), "status-pages");
  const monitors = useAsync(() => api.monitors(), "monitors-for-pages");

  const [creating, setCreating] = useState(false);
  const [slug, setSlug] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [selected, setSelected] = useState<number[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.createStatusPage({
        slug,
        title,
        description: description || null,
        monitor_ids: selected,
      });
      setCreating(false);
      setSlug("");
      setTitle("");
      setDescription("");
      setSelected([]);
      pages.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Status pages"
        description="A public page for your users: what is up, what is not, and what happened recently."
        actions={
          <Button variant="primary" size="sm" onClick={() => setCreating((value) => !value)}>
            <Plus className="h-3.5 w-3.5" aria-hidden />
            New status page
          </Button>
        }
      />

      {pages.error ? <ErrorNote message={pages.error} /> : null}

      {creating ? (
        <Card className="mb-4">
          <CardHeader title="New status page" description="Published pages are readable by anyone with the link." />
          <CardBody>
            <form onSubmit={create} className="space-y-4">
              {error ? <ErrorNote message={error} /> : null}
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Address" htmlFor="page-slug" hint="Lowercase letters, numbers and dashes.">
                  <Input
                    id="page-slug"
                    value={slug}
                    onChange={(event) => setSlug(event.target.value.toLowerCase())}
                    placeholder="acme"
                    pattern="[a-z0-9][a-z0-9-]*[a-z0-9]"
                    required
                  />
                </Field>
                <Field label="Title" htmlFor="page-title">
                  <Input
                    id="page-title"
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                    placeholder="Acme Platform"
                    required
                  />
                </Field>
              </div>
              <Field label="Description" htmlFor="page-description" hint="Optional line under the title.">
                <Input
                  id="page-description"
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder="Live availability of the Acme platform services."
                />
              </Field>

              <fieldset className="space-y-2">
                <legend className="text-xs font-medium text-[var(--color-ink-muted)]">
                  Services to show
                </legend>
                <div className="grid gap-1.5 sm:grid-cols-2">
                  {monitors.data?.map((monitor) => (
                    <label
                      key={monitor.id}
                      className="flex items-center gap-2 rounded-lg border border-[var(--color-border)] px-3 py-2 text-sm"
                    >
                      <input
                        type="checkbox"
                        checked={selected.includes(monitor.id)}
                        onChange={(event) =>
                          setSelected((current) =>
                            event.target.checked
                              ? [...current, monitor.id]
                              : current.filter((id) => id !== monitor.id),
                          )
                        }
                        className="accent-[var(--color-accent)]"
                      />
                      <span className="truncate">{monitor.name}</span>
                    </label>
                  ))}
                </div>
              </fieldset>

              <div className="flex justify-end gap-2">
                <Button type="button" variant="ghost" onClick={() => setCreating(false)}>
                  Cancel
                </Button>
                <Button type="submit" variant="primary" loading={busy} disabled={!slug || !title}>
                  Create page
                </Button>
              </div>
            </form>
          </CardBody>
        </Card>
      ) : null}

      {pages.loading && !pages.data ? <Spinner /> : null}
      {pages.data && pages.data.length === 0 && !creating ? (
        <Card>
          <EmptyState
            title="No status pages yet"
            hint="Pick a few monitors and publish them at a public address."
          />
        </Card>
      ) : null}

      <div className="space-y-3">
        {pages.data?.map((page) => (
          <Card key={page.id}>
            <CardHeader
              title={
                <span className="flex items-center gap-2">
                  <Globe className="h-4 w-4 text-[var(--color-ink-subtle)]" aria-hidden />
                  {page.title}
                </span>
              }
              description={page.description ?? `${page.monitor_ids.length} services`}
              action={
                <div className="flex items-center gap-2">
                  <a href={`/status/${page.slug}`} target="_blank" rel="noreferrer">
                    <Button size="sm">
                      View
                      <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                    </Button>
                  </a>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`Delete ${page.title}`}
                    onClick={async () => {
                      if (!confirm(`Delete the status page "${page.title}"?`)) return;
                      await api.deleteStatusPage(page.id).catch(() => undefined);
                      pages.reload();
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden />
                  </Button>
                </div>
              }
            />
            <CardBody className="space-y-3">
              <CodeBlock label="Public address" value={`/status/${page.slug}`} />
              <Toggle
                label="Published"
                description="An unpublished page answers 404 to visitors."
                checked={page.published}
                onChange={async (value) => {
                  await api.updateStatusPage(page.id, { published: value }).catch(() => undefined);
                  pages.reload();
                }}
              />
            </CardBody>
          </Card>
        ))}
      </div>
    </>
  );
}
