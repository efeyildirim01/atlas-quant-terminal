"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { z } from "zod";

import { useI18n } from "@/components/providers";
import { Badge, ErrorBlock, LoadingBlock, Panel } from "@/components/ui/primitives";
import { ApiError, apiFetch } from "@/lib/api-client";
import { cn } from "@/lib/format";
import { AnswerMarkdown } from "./answer-markdown";

const Evidence = z.object({
  id: z.string(), tool: z.string(), input: z.record(z.string(), z.unknown()), status: z.string(), data: z.unknown(),
  sources: z.array(z.record(z.string(), z.unknown())), as_of: z.string().nullable(), quality: z.string().nullable(),
  is_fixture: z.boolean(), error: z.string().nullable(),
});
const Claim = z.object({ text: z.string(), status: z.string(), cites: z.array(z.string()), matched_in: z.string().nullable() });
export const QueryOut = z.object({
  query_id: z.string(), question: z.string(), answer: z.string(), evidence: z.array(Evidence),
  verification: z.object({ status: z.string(), counts: z.record(z.string(), z.number()), invalid_citations: z.array(z.string()), claims: z.array(Claim) }),
  model: z.string(), served_by: z.string().nullable(), stop_reason: z.string(), usage: z.record(z.string(), z.unknown()),
  notes: z.array(z.string()), latency_ms: z.number(), disclaimer: z.string(),
});
type TQuery = z.infer<typeof QueryOut>;
const HistoryRow = z.object({ query_id: z.string(), question: z.string(), created_at: z.string(), verification: z.string().nullable(), stop_reason: z.string() });

export interface Status {
  configured: boolean;
  enabled: boolean;
  model: string;
  effort: string;
  setup: string;
  credential_sources: string[];
  tools: { name: string; description: string; available: boolean }[];
}

const VERIFY_BADGE: Record<string, "ok" | "warn" | "danger" | "default"> = {
  verified: "ok", no_numeric_claims: "default", partially_verified: "warn", unverified_claims: "danger",
};

export function ResearchWorkspace({ status }: { status: Status }) {
  const { t, locale } = useI18n();
  const qc = useQueryClient();
  const [question, setQuestion] = useState("");
  const [thread, setThread] = useState<TQuery[]>([]);
  const evidenceRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const history = useQuery({ queryKey: ["research-history"], queryFn: () => apiFetch("/api/v1/research/history", z.array(HistoryRow)) });
  const ask = useMutation({
    mutationFn: (q: string) =>
      apiFetch("/api/v1/research/query", QueryOut, { method: "POST", body: JSON.stringify({ question: q, history_ids: thread.map((x) => x.query_id).slice(-5) }) }),
    onSuccess: (r) => {
      setThread((th) => [...th, r]);
      setQuestion("");
      qc.invalidateQueries({ queryKey: ["research-history"] });
    },
  });
  const open = useMutation({
    mutationFn: (id: string) => apiFetch(`/api/v1/research/history/${id}`, QueryOut),
    onSuccess: (r) => setThread([r]),
  });

  const examples = locale === "tr"
    ? ["D-BNK1 ve D-DEFN'i risk, momentum ve volatilite açısından karşılaştır.", "Son 3 yılda risk-ayarlı getirisi en güçlü hisse fonları hangileri? rf %35 kullan.",
       "Portföyümün riskini ve en büyük risk kaynağını açıkla.", "Likit ve pozitif momentumlu hisseleri bul."]
    : ["Compare D-BNK1 and D-DEFN on risk, momentum and volatility.", "Which equity funds have the strongest 3-year risk-adjusted returns? Use rf 35%.",
       "Explain my portfolio's risk and its biggest risk driver.", "Find liquid stocks with positive momentum."];

  const current = thread[thread.length - 1];
  const scrollTo = (id: string) => evidenceRefs.current[id]?.scrollIntoView({ behavior: "smooth", block: "center" });

  if (!status.configured) {
    return (
      <div className="grid max-w-3xl gap-3 p-4">
        <h1 className="text-lg font-semibold tracking-tight">{t.nav.research}</h1>
        <Panel title={status.enabled ? t.research.notConfigured : t.research.disabled}>
          <div className="space-y-2 p-4 text-[12.5px]" data-testid="ai-not-configured">
            {!status.enabled && <p className="text-fg">{t.research.disabledIntro}</p>}
            <p>{t.research.setupIntro}</p>
            <pre className="num overflow-x-auto rounded bg-bg-2 p-2 text-[12px] text-fg">setx ANTHROPIC_API_KEY "sk-ant-..."</pre>
            <p className="text-muted">{status.setup}</p>
            <p className="text-faint">Model: {status.model} · effort {status.effort}</p>
          </div>
        </Panel>
        <ToolList tools={status.tools} />
      </div>
    );
  }

  return (
    <div className="grid gap-3 p-4 xl:grid-cols-[260px_1fr_380px]">
      <Panel title={t.research.history} className="xl:max-h-[calc(100vh-140px)]" bodyClassName="overflow-y-auto">
        <div className="p-2">
          <button onClick={() => setThread([])} className="mb-2 w-full rounded px-2 py-1 text-[11.5px] text-muted ring-1 ring-line hover:text-fg">+ {t.research.newThread}</button>
          <ul className="space-y-1 text-[12px]" data-testid="research-history">
            {(history.data ?? []).map((h) => (
              <li key={h.query_id}>
                <button onClick={() => open.mutate(h.query_id)} className="w-full truncate rounded px-2 py-1 text-left text-muted hover:bg-bg-2 hover:text-fg" title={h.question}>
                  {h.question}
                </button>
              </li>
            ))}
          </ul>
        </div>
      </Panel>

      <div className="grid min-w-0 content-start gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">{t.nav.research}</h1>
          <p className="text-[12px] text-muted">{t.research.intro}</p>
        </div>
        {thread.map((q) => (
          <Panel key={q.query_id} title={q.question}
            right={<Badge variant={VERIFY_BADGE[q.verification.status] ?? "default"}>{q.verification.status.replace(/_/g, " ")}</Badge>}>
            <div className="space-y-3 p-3">
              {q.stop_reason === "refusal" ? (
                <p className="text-[12.5px] text-warn">{t.research.refused}</p>
              ) : (
                <AnswerMarkdown text={q.answer} onCite={scrollTo} known={new Set(q.evidence.map((e) => e.id))} />
              )}
              {q.notes.map((n) => <p key={n} className="text-[11.5px] text-warn">⚠ {n}</p>)}
              <Flags q={q} />
              <p className="num text-[10.5px] text-faint">
                {q.served_by ?? q.model} · {q.evidence.length} tool calls · {String(q.usage.input_tokens ?? "?")} in / {String(q.usage.output_tokens ?? "?")} out tokens · {(q.latency_ms / 1000).toFixed(1)} s
              </p>
              <p className="text-[10.5px] text-faint">{q.disclaimer}</p>
            </div>
          </Panel>
        ))}
        {ask.isPending && <LoadingBlock label={t.research.thinking} className="h-32" />}
        {ask.isError && <ErrorBlock message={ask.error instanceof ApiError ? ask.error.message : String(ask.error)} />}
        <form onSubmit={(e) => { e.preventDefault(); if (question.trim().length >= 3) ask.mutate(question.trim()); }} className="grid gap-2">
          <textarea aria-label={t.research.ask} value={question} onChange={(e) => setQuestion(e.target.value)} rows={3} maxLength={2000}
            placeholder={thread.length ? t.research.followUp : t.research.ask}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) (e.currentTarget.form as HTMLFormElement).requestSubmit(); }}
            className="rounded border border-line bg-bg-2 p-2 text-[13px] text-fg outline-none focus:border-accent/60" />
          <div className="flex flex-wrap items-center gap-2">
            <button disabled={ask.isPending || question.trim().length < 3} className="rounded bg-accent px-3 py-1.5 text-[12px] font-medium text-white disabled:opacity-40">
              {ask.isPending ? t.research.thinking : t.research.send}
            </button>
            <span className="text-[11px] text-faint">Ctrl+Enter</span>
            {!thread.length && examples.map((ex) => (
              <button key={ex} type="button" onClick={() => setQuestion(ex)} className="rounded px-2 py-1 text-[11px] text-muted ring-1 ring-line hover:text-fg">{ex}</button>
            ))}
          </div>
        </form>
      </div>

      <Panel title={t.research.evidence} className="xl:sticky xl:top-4 xl:max-h-[calc(100vh-140px)]" bodyClassName="overflow-y-auto">
        {!current ? (
          <ToolList tools={status.tools} bare />
        ) : (
          <div className="space-y-2 p-2" data-testid="evidence-list">
            {current.evidence.map((e) => (
              <div key={e.id} ref={(el) => { evidenceRefs.current[e.id] = el; }} className="rounded border border-line p-2 text-[11.5px]" data-testid={`evidence-${e.id}`}>
                <div className="flex items-center justify-between gap-2">
                  <span><span className="font-mono font-semibold text-accent">{e.id}</span> <span className="font-mono text-muted">{e.tool}</span></span>
                  <span className="flex gap-1">
                    {e.is_fixture && <Badge variant="warn">Fixture</Badge>}
                    <Badge variant={e.status === "ok" ? "ok" : e.status === "unavailable" ? "default" : "danger"}>{e.status}</Badge>
                  </span>
                </div>
                <div className="num mt-1 text-faint">{JSON.stringify(e.input)}</div>
                {e.as_of && <div className="text-muted">as of {e.as_of} · {e.quality} · {[...new Set(e.sources.map((s) => String(s.source)))].join(", ")}</div>}
                {e.error && <div className="text-down">{e.error}</div>}
                {e.data != null && (
                  <details className="mt-1">
                    <summary className="cursor-pointer text-faint hover:text-fg">data</summary>
                    <pre className="num mt-1 max-h-64 overflow-auto rounded bg-bg-2 p-1.5 text-[10.5px] text-muted">{JSON.stringify(e.data, null, 1)}</pre>
                  </details>
                )}
              </div>
            ))}
            {current.evidence.length === 0 && <p className="p-2 text-[12px] text-muted">No tools were called for this answer.</p>}
          </div>
        )}
      </Panel>
    </div>
  );
}

function Flags({ q }: { q: TQuery }) {
  const { t } = useI18n();
  const flagged = q.verification.claims.filter((c) => c.status !== "verified");
  const verified = q.verification.claims.length - flagged.length;
  if (!q.verification.claims.length && !q.verification.invalid_citations.length) return null;
  return (
    <div className={cn("rounded border p-2 text-[11.5px]", flagged.length || q.verification.invalid_citations.length ? "border-warn/40 bg-warn/5" : "border-up/40 bg-up/5")} data-testid="verification">
      <div className="font-medium">{t.research.verification}: {verified}/{q.verification.claims.length} {t.research.figuresVerified}</div>
      {flagged.map((c, i) => (
        <div key={i} className="text-muted">
          <span className="num text-fg">{c.text}</span> · {c.status === "mismatch" ? `not found in ${c.cites.join(", ")}` : c.status === "uncited" ? "no citation (value exists in the evidence)" : "not supported by any evidence"}
        </div>
      ))}
      {q.verification.invalid_citations.length > 0 && <div className="text-down">Invalid citations: {q.verification.invalid_citations.join(", ")}</div>}
    </div>
  );
}

function ToolList({ tools, bare = false }: { tools: Status["tools"]; bare?: boolean }) {
  const { t } = useI18n();
  const list = (
    <ul className="space-y-1.5 p-3 text-[11.5px]">
      {tools.map((tool) => (
        <li key={tool.name} title={tool.description}>
          <span className="font-mono text-fg">{tool.name}</span>{" "}
          {!tool.available && <Badge>unavailable</Badge>}
          <div className="text-faint">{tool.description}</div>
        </li>
      ))}
    </ul>
  );
  return bare ? list : <Panel title={t.research.tools}>{list}</Panel>;
}
