"use client";

import Link, { useLinkStatus } from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { useI18n } from "@/components/providers";
import { cn } from "@/lib/format";
import type { Dict } from "@/lib/i18n";

type NavKey = keyof Dict["nav"];
const NAV: { key: NavKey; href?: string; milestone?: string; glyph: string }[] = [
  { key: "dashboard", href: "/dashboard", glyph: "◧" },
  { key: "equities", href: "/equities", glyph: "▤" },
  { key: "funds", href: "/funds", glyph: "◫" },
  { key: "screener", href: "/screener/equities", glyph: "⊞" },
  { key: "backtest", href: "/backtest", glyph: "↻" },
  { key: "portfolio", href: "/portfolio", glyph: "◔" },
  { key: "research", href: "/ai-research", glyph: "◇" },
  { key: "reports", href: "/reports", glyph: "▦" },
  { key: "dataHealth", href: "/system/data-health", glyph: "◉" },
];
const KEY = "atlas.sidebarCollapsed";

export function Sidebar() {
  const path = usePathname();
  const { t } = useI18n();
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem(KEY) === "1");
    } catch {}
  }, []);
  const toggle = () =>
    setCollapsed((c) => {
      try {
        localStorage.setItem(KEY, c ? "0" : "1");
      } catch {}
      return !c;
    });

  return (
    <nav aria-label="Primary" className={cn("flex shrink-0 flex-col border-r border-line bg-bg-2 transition-[width]", collapsed ? "w-14" : "w-56")}>
      <div className="flex h-12 items-center justify-between border-b border-line px-3">
        {!collapsed && (
          <div>
            <div className="text-[13px] font-semibold tracking-[0.2em] text-fg">ATLAS</div>
            <div className="text-[9px] tracking-[0.24em] text-faint">QUANT TERMINAL</div>
          </div>
        )}
        <button onClick={toggle} aria-label={collapsed ? "Expand navigation" : "Collapse navigation"} className="rounded px-1.5 text-muted hover:text-fg">
          {collapsed ? "»" : "«"}
        </button>
      </div>
      <ul className="flex-1 overflow-y-auto py-2 text-[12.5px]">
        {NAV.map((n) => {
          const label = t.nav[n.key];
          const active = n.href && path.startsWith(n.href);
          const inner = (
            <>
              <span aria-hidden className="w-4 text-center text-[13px]">
                {n.glyph}
              </span>
              {!collapsed && <span className="flex-1 truncate">{label}</span>}
              {!collapsed && n.milestone && <span className="text-[9px] tracking-wide">{n.milestone}</span>}
              {n.href && <PendingDot />}
            </>
          );
          return (
            <li key={n.key}>
              {n.href ? (
                <Link
                  href={n.href}
                  title={label}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex items-center gap-2.5 border-l-2 px-4 py-1.5 transition-colors",
                    active ? "border-accent bg-panel text-fg" : "border-transparent text-muted hover:text-fg",
                  )}
                >
                  {inner}
                </Link>
              ) : (
                <span
                  title={`${label}: ${t.nav.planned} (${n.milestone})`}
                  aria-disabled
                  className="flex cursor-not-allowed items-center gap-2.5 border-l-2 border-transparent px-4 py-1.5 text-faint"
                >
                  {inner}
                </span>
              )}
            </li>
          );
        })}
      </ul>
      {!collapsed && <div className="border-t border-line px-4 py-3 text-[10px] leading-relaxed text-faint">{t.shell.disclaimer}</div>}
    </nav>
  );
}

/** Shown on the clicked item only while its page is still loading; delayed so fast (<120 ms) navigations show nothing.
 * Replaces a route-level loading skeleton, which made React hold every page back for ~300 ms. */
function PendingDot() {
  const { pending } = useLinkStatus();
  return (
    <span aria-hidden data-testid={pending ? "nav-pending" : undefined}
      className={cn("h-1.5 w-1.5 shrink-0 rounded-full bg-accent", pending ? "animate-[nav-pending_0.9s_120ms_infinite_both]" : "opacity-0")} />
  );
}
