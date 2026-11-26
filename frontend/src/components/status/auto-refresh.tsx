"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw } from "lucide-react";

/**
 * A status page that goes stale while someone stares at it is not much use, so
 * the server component is re-fetched on an interval. This is the only client
 * JavaScript on the public page.
 */
export function AutoRefresh({ seconds = 60 }: { seconds?: number }) {
  const router = useRouter();
  const [refreshedAt, setRefreshedAt] = useState<string | null>(null);

  useEffect(() => {
    const timer = setInterval(() => {
      router.refresh();
      setRefreshedAt(new Date().toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
    }, seconds * 1000);
    return () => clearInterval(timer);
  }, [router, seconds]);

  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] text-[var(--color-ink-subtle)]">
      <RefreshCw className="h-3 w-3" aria-hidden />
      {refreshedAt ? `updated ${refreshedAt}` : `refreshes every ${seconds}s`}
    </span>
  );
}
