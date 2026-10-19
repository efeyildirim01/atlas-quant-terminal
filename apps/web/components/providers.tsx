"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { z } from "zod";

import { makeFormat, type Fmt } from "@/lib/format";
import { DICTS, type Dict, type Locale } from "@/lib/i18n";

// The production CSP forbids eval; without this Zod probes `new Function` and logs a CSP violation.
z.config({ jitless: true });

interface I18n {
  locale: Locale;
  t: Dict;
  fmt: Fmt;
}

const I18nContext = createContext<I18n | null>(null);

export function useI18n(): I18n {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n outside Providers");
  return ctx;
}

export function I18nProvider({ locale, children }: { locale: Locale; children: ReactNode }) {
  const value = useMemo(() => ({ locale, t: DICTS[locale], fmt: makeFormat(locale) }), [locale]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function Providers({ locale, children }: { locale: Locale; children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          // EOD data: a minute of client cache is plenty and avoids refetch storms when switching tabs.
          queries: { staleTime: 60_000, retry: 1, refetchOnWindowFocus: false },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <I18nProvider locale={locale}>{children}</I18nProvider>
    </QueryClientProvider>
  );
}
