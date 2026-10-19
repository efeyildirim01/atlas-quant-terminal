"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { z } from "zod";

import { useI18n } from "@/components/providers";
import { InstrumentSearch } from "@/components/search/instrument-search";
import { Badge } from "@/components/ui/primitives";
import { apiFetch } from "@/lib/api-client";
import { LOCALE_COOKIE, type Locale } from "@/lib/i18n";

export interface MarketStatus {
  session: "open" | "closed";
  local_time: string;
  basis: string;
  latest_observation: string | null;
  freshness: string;
  lag_business_days: number | null;
  fixture_mode: boolean;
  note: string;
}

export interface SessionUser {
  email: string;
  role: string;
  display_name: string | null;
}

export function MarketStatusIndicator({ status }: { status: MarketStatus | null }) {
  const { t, fmt } = useI18n();
  if (!status) return <Badge variant="danger">API offline</Badge>;
  const open = status.session === "open";
  return (
    <div className="flex items-center gap-2 text-[11px]" title={`${status.basis}\n${status.note}`} data-testid="market-status">
      <span className="flex items-center gap-1.5 text-muted">
        <span aria-hidden className={open ? "text-up" : "text-faint"}>●</span>
        BIST {open ? t.shell.marketOpen : t.shell.marketClosed}
      </span>
      <span className="text-faint">·</span>
      <span className="text-muted">{t.shell.noLiveFeed}</span>
      <span className="text-faint">·</span>
      <span className="num text-muted">
        {t.shell.latestData} {fmt.date(status.latest_observation)}
      </span>
      <Badge variant={status.freshness === "FRESH" ? "ok" : "danger"}>{status.freshness}</Badge>
    </div>
  );
}

export function LanguageSelector() {
  const { locale } = useI18n();
  const router = useRouter();
  const set = (l: Locale) => {
    document.cookie = `${LOCALE_COOKIE}=${l}; path=/; max-age=31536000; samesite=lax`;
    router.refresh();
  };
  return (
    <label className="flex items-center gap-1 text-[11px] text-muted">
      <span className="sr-only">Language</span>
      <select
        aria-label="Language"
        value={locale}
        onChange={(e) => set(e.target.value as Locale)}
        className="rounded border border-line bg-bg-2 px-1.5 py-0.5 text-[11px] text-fg"
      >
        <option value="en">EN</option>
        <option value="tr">TR</option>
      </select>
    </label>
  );
}

export function AccountMenu({ user }: { user: SessionUser | null }) {
  const { t } = useI18n();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  if (!user)
    return (
      <Link href="/login" className="rounded bg-accent px-2.5 py-1 text-[11px] font-medium text-white hover:bg-accent/90">
        {t.shell.signIn}
      </Link>
    );
  return (
    <div className="flex items-center gap-2 text-[11px]">
      <span className="text-muted" title={user.role}>
        {user.display_name ?? user.email}
      </span>
      <Badge>{user.role.replace("_", " ")}</Badge>
      <button
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            await apiFetch("/api/v1/auth/logout", z.any(), { method: "POST" });
          } finally {
            setBusy(false);
            router.refresh();
          }
        }}
        className="rounded px-2 py-0.5 text-muted ring-1 ring-line hover:text-fg"
      >
        {t.shell.signOut}
      </button>
    </div>
  );
}

export function TopBar({ status, user }: { status: MarketStatus | null; user: SessionUser | null }) {
  return (
    <header className="flex h-12 shrink-0 items-center gap-4 border-b border-line bg-bg-2 px-4">
      <InstrumentSearch />
      <div className="ml-auto flex items-center gap-4">
        <MarketStatusIndicator status={status} />
        <LanguageSelector />
        <AccountMenu user={user} />
      </div>
    </header>
  );
}
