"use client";

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div role="alert" className="m-6 rounded-md border border-down/40 bg-down/5 p-4 text-sm">
      <div className="font-medium text-down">⚠ This view failed to load</div>
      <div className="mt-1 text-muted">{error.message}</div>
      {error.digest && <div className="num mt-1 text-faint">digest {error.digest}</div>}
      <button onClick={reset} className="mt-3 rounded bg-bg-2 px-2 py-1 text-[12px] text-muted ring-1 ring-line hover:text-fg">
        Retry
      </button>
    </div>
  );
}
