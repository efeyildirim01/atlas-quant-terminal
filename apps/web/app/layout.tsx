import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import type { ReactNode } from "react";

import { Providers } from "@/components/providers";
import { Sidebar } from "@/components/shell/sidebar";
import { TopBar, type MarketStatus, type SessionUser } from "@/components/shell/topbar";
import { getDict } from "@/lib/locale-server";
import { serverApi } from "@/lib/server-api";
import "@/styles/globals.css";

const inter = Inter({ subsets: ["latin", "latin-ext"], variable: "--font-inter" });
const mono = JetBrains_Mono({ subsets: ["latin", "latin-ext"], variable: "--font-jbmono" });

export const metadata: Metadata = {
  title: "ATLAS Quant Terminal",
  description: "Research and analytics terminal for Turkish markets. Not investment advice.",
};

async function safe<T>(p: Promise<T>): Promise<T | null> {
  try {
    return await p;
  } catch {
    return null;
  }
}

export default async function RootLayout({ children }: { children: ReactNode }) {
  const { locale, t } = await getDict();
  const [status, user] = await Promise.all([
    safe(serverApi<MarketStatus>("/api/v1/system/market-status")),
    safe(serverApi<SessionUser>("/api/v1/auth/me")),
  ]);
  return (
    <html lang={locale} className={`${inter.variable} ${mono.variable}`}>
      <body className="flex h-screen overflow-hidden font-sans antialiased">
        <Providers locale={locale}>
          <Sidebar />
          <div className="flex min-w-0 flex-1 flex-col">
            <TopBar status={status} user={user} />
            {(status === null || status.fixture_mode) && (
              <div role="note" className="border-b border-warn/30 bg-warn/10 px-4 py-1.5 text-[11.5px] text-warn" data-testid="fixture-banner">
                <strong className="mr-2 tracking-wide">{status === null ? "API" : "FIXTURE"}</strong>
                {status === null ? t.shell.apiDown : t.shell.fixtureBanner}
              </div>
            )}
            <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
