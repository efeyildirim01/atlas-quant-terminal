// shadcn/ui-style primitives (hand-written in the shadcn idiom; the CLI was not run, see README).
import type { ReactNode } from "react";

import { cn } from "@/lib/format";

export function Panel({
  title,
  right,
  children,
  className,
  bodyClassName,
  id,
}: {
  title?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  id?: string;
}) {
  return (
    <section id={id} aria-label={typeof title === "string" ? title : undefined} className={cn("flex min-w-0 flex-col rounded-md border border-line bg-panel", className)}>
      {(title || right) && (
        <header className="flex min-h-9 items-center justify-between gap-3 border-b border-line px-3 py-1.5">
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">{title}</h2>
          <div className="flex items-center gap-2 text-[11px]">{right}</div>
        </header>
      )}
      <div className={cn("min-h-0 flex-1", bodyClassName)}>{children}</div>
    </section>
  );
}

const BADGE = {
  default: "bg-bg-2 text-muted ring-line",
  accent: "bg-accent/10 text-accent ring-accent/40",
  warn: "bg-warn/10 text-warn ring-warn/40",
  danger: "bg-down/10 text-down ring-down/40",
  ok: "bg-up/10 text-up ring-up/40",
} as const;

export function Badge({ children, variant = "default", title }: { children: ReactNode; variant?: keyof typeof BADGE; title?: string }) {
  return (
    <span title={title} className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1", BADGE[variant])}>
      {children}
    </span>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: readonly T[] | { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
}) {
  const opts = (options as (T | { value: T; label: string })[]).map((o) => (typeof o === "string" ? { value: o, label: o } : o));
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded border border-line bg-bg-2 p-0.5">
      {opts.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded px-2 py-0.5 text-[11px] transition-colors",
            o.value === value ? "bg-panel text-fg ring-1 ring-line" : "text-muted hover:text-fg",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function KV({ rows }: { rows: { k: ReactNode; v: ReactNode; hint?: string }[] }) {
  return (
    <dl className="divide-y divide-line/60 text-[12px]">
      {rows.map((r, i) => (
        <div key={i} className="flex items-baseline justify-between gap-4 px-3 py-1.5" title={r.hint}>
          <dt className="text-muted">{r.k}</dt>
          <dd className="num text-right text-fg">{r.v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("animate-pulse rounded bg-bg-2", className)} />;
}

export function LoadingBlock({ label, className }: { label: string; className?: string }) {
  return (
    <div role="status" aria-live="polite" className={cn("flex h-full min-h-24 flex-col gap-2 p-3", className)}>
      <span className="sr-only">{label}</span>
      <Skeleton className="h-3 w-1/3" />
      <Skeleton className="h-full w-full" />
    </div>
  );
}

export function ErrorBlock({ message, requestId, onRetry, retryLabel = "Retry" }: { message: string; requestId?: string; onRetry?: () => void; retryLabel?: string }) {
  return (
    <div role="alert" className="m-3 rounded border border-down/40 bg-down/5 p-3 text-[12px]">
      <div className="font-medium text-down">⚠ {message}</div>
      {requestId && <div className="num mt-1 text-faint">request {requestId}</div>}
      {onRetry && (
        <button onClick={onRetry} className="mt-2 rounded bg-bg-2 px-2 py-0.5 text-muted ring-1 ring-line hover:text-fg">
          {retryLabel}
        </button>
      )}
    </div>
  );
}

export function UnavailableBlock({ title, reason, source }: { title: string; reason: string; source?: string }) {
  return (
    <div className="p-3 text-[12px]">
      <Badge variant="default">UNAVAILABLE</Badge>
      <p className="mt-2 text-muted">{reason}</p>
      {source && <p className="mt-1 text-faint">Required source: {source}</p>}
      <p className="sr-only">{title} unavailable</p>
    </div>
  );
}
