"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";
import { z } from "zod";

import { DataFreshnessBadge } from "@/components/data/financial";
import { useI18n } from "@/components/providers";
import { Badge, ErrorBlock, LoadingBlock, Panel } from "@/components/ui/primitives";
import { useDebounced } from "@/hooks/use-debounced";
import { ApiError, apiFetch } from "@/lib/api-client";
import { cn, direction } from "@/lib/format";
import { envelope } from "@/lib/schemas";
import { countConditions, fromApi, newGroup, toApi, type ApiGroup, type FieldDef, type GroupState } from "./builder";
import { GroupEditor } from "./group-editor";

export type Universe = "equities" | "funds";
export interface Preset {
  id: string;
  name: string;
  description: string;
  filter: ApiGroup;
  sort: { field: string | null; descending: boolean };
}

export const DEFAULT_COLUMNS: Record<Universe, string[]> = {
  equities: ["sector", "close", "chg_1d", "chg_1m", "chg_3m", "chg_1y", "vol_1y", "max_dd_1y", "avg_turnover_20d", "rsi_14"],
  funds: ["category", "ret_1m", "ret_1y", "ret_3y_ann", "vol_3y", "max_dd_3y", "sharpe_3y", "management_fee", "total_assets"],
};

const Result = z.object({
  universe: z.string(),
  as_of: z.string().nullable(),
  latest_data_date: z.string().nullable(),
  snapshot_id: z.string(),
  total_universe: z.number(),
  total_matches: z.number(),
  page: z.number(),
  page_size: z.number(),
  rows: z.array(z.record(z.string(), z.unknown())),
  missing_by_condition: z.array(z.object({ field: z.string(), operator: z.string(), excluded_missing: z.number() })),
  category_values: z.record(z.string(), z.array(z.string())),
});
const Saved = z.object({ screen_id: z.string(), name: z.string(), universe: z.string(), definition: z.record(z.string(), z.unknown()) });
const PAGE_SIZE = 25;

export function ScreenerWorkspace({ universe, fields, presets, signedIn }: { universe: Universe; fields: FieldDef[]; presets: Preset[]; signedIn: boolean }) {
  const { t, fmt } = useI18n();
  const qc = useQueryClient();
  const byId = useMemo(() => Object.fromEntries(fields.map((f) => [f.id, f])), [fields]);
  const [root, setRoot] = useState<GroupState>(() => newGroup("and"));
  const [sort, setSort] = useState<{ field: string | null; descending: boolean }>({ field: DEFAULT_COLUMNS[universe][2] ?? null, descending: true });
  const [columns, setColumns] = useState<string[]>(DEFAULT_COLUMNS[universe]);
  const [page, setPage] = useState(1);
  const [asOf, setAsOf] = useState("");
  const [showCols, setShowCols] = useState(false);
  const [saveName, setSaveName] = useState("");

  const built = toApi(root, byId);
  const definition = built.ok ? { filter: built.filter, sort, columns } : null;
  const debounced = useDebounced(JSON.stringify({ definition, page, asOf }), 350);
  const req = JSON.parse(debounced) as { definition: typeof definition; page: number; asOf: string };

  const result = useQuery({
    queryKey: ["screen", universe, debounced],
    queryFn: () =>
      apiFetch(`/api/v1/screener/${universe}`, envelope(Result), {
        method: "POST",
        body: JSON.stringify({ ...req.definition, page: req.page, page_size: PAGE_SIZE, as_of: req.asOf || undefined }),
      }),
    enabled: !!req.definition,
    placeholderData: (prev) => prev,
  });

  const saved = useQuery({
    queryKey: ["saved-screens", universe],
    queryFn: () => apiFetch("/api/v1/screener/saved", z.array(Saved), { params: { universe } }),
    enabled: signedIn,
  });
  const save = useMutation({
    mutationFn: () => apiFetch("/api/v1/screener/saved", Saved, { method: "POST", body: JSON.stringify({ name: saveName.trim(), universe, definition }) }),
    onSuccess: () => {
      setSaveName("");
      qc.invalidateQueries({ queryKey: ["saved-screens", universe] });
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => apiFetch(`/api/v1/screener/saved/${id}`, z.any(), { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["saved-screens", universe] }),
  });

  const load = (filter: ApiGroup, s: { field: string | null; descending: boolean }, cols?: string[]) => {
    setRoot(fromApi(filter, byId));
    setSort(s);
    if (cols?.length) setColumns(cols);
    setPage(1);
  };

  const exportCsv = async () => {
    if (!definition) return;
    const res = await fetch(`/api/v1/screener/${universe}/export`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ...definition, as_of: asOf || undefined }),
    });
    if (!res.ok) return;
    const blob = await res.blob();
    const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? `screen_${universe}.csv`;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const d = result.data?.data;
  const pages = d ? Math.max(1, Math.ceil(d.total_matches / PAGE_SIZE)) : 1;
  const available = fields.filter((f) => f.available);
  const cell = (fid: string, v: unknown) => {
    const f = byId[fid];
    if (v === null || v === undefined) return <span className="text-faint">—</span>;
    if (!f) return String(v);
    if (f.type === "boolean") return v ? "✓" : "✗";
    if (f.type === "category") return <span className="text-muted">{String(v)}</span>;
    const n = v as number;
    if (f.unit === "fraction") return <span className={fid.startsWith("chg") || fid.startsWith("ret") || fid.startsWith("rel") || fid.startsWith("excess") ? direction(n).tone : ""}>{fmt.pct(n, 2, fid.startsWith("chg") || fid.startsWith("ret") || fid.startsWith("rel") || fid.startsWith("excess"))}</span>;
    if (f.unit === "TRY" || f.unit === "count") return fmt.compact(n);
    if (f.unit === "years" || f.unit === "index") return fmt.num(n, 1);
    return fmt.num(n, 2);
  };

  return (
    <div className="grid gap-3 p-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex gap-1 text-[12px]" role="tablist" aria-label="Universe">
            {(["equities", "funds"] as const).map((u) => (
              <Link key={u} href={`/screener/${u}`} role="tab" aria-selected={u === universe}
                className={cn("rounded px-2.5 py-1", u === universe ? "bg-panel text-fg ring-1 ring-line" : "text-muted hover:text-fg")}>
                {u === "equities" ? t.nav.equities : t.nav.funds}
              </Link>
            ))}
          </div>
          <h1 className="mt-1 text-lg font-semibold tracking-tight">{t.nav.screener}</h1>
          <p className="text-[12px] text-muted">
            Conditions on missing values never pass; how many instruments each condition excluded for missing data is shown below.
          </p>
        </div>
        <div className="flex items-center gap-2 text-[11px]">
          <select aria-label="Preset" value="" onChange={(e) => { const p = presets.find((x) => x.id === e.target.value); if (p) load(p.filter, p.sort); }}
            className="rounded border border-line bg-bg-2 px-1.5 py-1 text-fg">
            <option value="">Presets…</option>
            {presets.map((p) => (
              <option key={p.id} value={p.id} title={p.description}>{p.name}</option>
            ))}
          </select>
          <label className="flex items-center gap-1 text-muted" title="Run the screen on data up to this date (point-in-time)">
            As of
            <input type="date" aria-label="As of date" value={asOf} max={d?.latest_data_date ?? undefined} onChange={(e) => { setAsOf(e.target.value); setPage(1); }}
              className="num rounded border border-line bg-bg-2 px-1.5 py-0.5 text-fg" />
          </label>
          <button onClick={exportCsv} disabled={!definition} data-testid="screen-export" className="rounded px-2.5 py-1 text-muted ring-1 ring-line hover:text-fg disabled:opacity-40">
            {t.funds.exportCsv}
          </button>
        </div>
      </div>

      <div className="grid gap-3 xl:grid-cols-[1fr_300px]">
        <Panel title={`Conditions (${countConditions(root)})`} right={<button onClick={() => { setRoot(newGroup("and")); setPage(1); }} className="text-faint hover:text-fg">reset</button>}>
          <div className="p-3">
            <GroupEditor root={root} node={root} depth={1} fields={fields} categoryValues={d?.category_values ?? {}} onChange={(r) => { setRoot(r); setPage(1); }} />
            {!built.ok && <p role="alert" className="mt-2 text-[12px] text-warn">{built.error}</p>}
          </div>
        </Panel>
        <Panel title="Saved screens">
          {!signedIn ? (
            <p className="p-3 text-[12px] text-muted"><Link href="/login" className="text-accent hover:underline">{t.shell.signIn}</Link> to save screens.</p>
          ) : (
            <div className="space-y-2 p-3 text-[12px]">
              <form onSubmit={(e) => { e.preventDefault(); if (saveName.trim() && definition) save.mutate(); }} className="flex gap-1.5">
                <input aria-label="Screen name" value={saveName} onChange={(e) => setSaveName(e.target.value)} placeholder="Name this screen"
                  className="min-w-0 flex-1 rounded border border-line bg-bg-2 px-2 py-1 text-fg" />
                <button disabled={!definition || !saveName.trim()} className="rounded bg-accent px-2 py-1 text-[11px] font-medium text-white disabled:opacity-40">Save</button>
              </form>
              {save.isError && <p role="alert" className="text-down">{save.error instanceof ApiError ? save.error.message : String(save.error)}</p>}
              <ul className="divide-y divide-line/50" data-testid="saved-screens">
                {(saved.data ?? []).map((s) => (
                  <li key={s.screen_id} className="flex items-center justify-between gap-2 py-1">
                    <button className="truncate text-left text-accent hover:underline"
                      onClick={() => { const def = s.definition as { filter: ApiGroup; sort: Preset["sort"]; columns: string[] }; load(def.filter, def.sort, def.columns); }}>
                      {s.name}
                    </button>
                    <button aria-label={`Delete ${s.name}`} onClick={() => remove.mutate(s.screen_id)} className="text-faint hover:text-down">✕</button>
                  </li>
                ))}
                {saved.data?.length === 0 && <li className="py-1 text-faint">None yet.</li>}
              </ul>
            </div>
          )}
        </Panel>
      </div>

      <Panel
        title={d ? `${d.total_matches} of ${d.total_universe} match` : "Results"}
        right={
          <>
            {result.data?.provenance[0] && <DataFreshnessBadge provenance={result.data.provenance[0]} />}
            {d && <span className="num text-faint" title="Same id = same query, same data version, same as-of date">snapshot {d.snapshot_id}</span>}
            <button onClick={() => setShowCols((x) => !x)} aria-expanded={showCols} className="rounded px-2 py-0.5 text-muted ring-1 ring-line hover:text-fg">Columns</button>
          </>
        }
      >
        {showCols && (
          <div className="flex flex-wrap gap-1.5 border-b border-line p-3" role="group" aria-label="Columns">
            {available.map((f) => {
              const on = columns.includes(f.id);
              return (
                <button key={f.id} aria-pressed={on} onClick={() => setColumns((cs) => (on ? cs.filter((c) => c !== f.id) : [...cs, f.id]))}
                  className={cn("rounded px-2 py-0.5 text-[11px] ring-1", on ? "bg-bg-2 text-fg ring-accent/60" : "text-muted ring-line")}>
                  {f.label}
                </button>
              );
            })}
          </div>
        )}
        {result.isError ? (
          <ErrorBlock message={result.error instanceof ApiError ? result.error.message : String(result.error)} />
        ) : !d ? (
          <LoadingBlock label={t.common.loading} />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]" data-testid="screen-results">
                <thead>
                  <tr className="border-b border-line text-[10px] uppercase tracking-[0.06em] text-faint">
                    {["symbol", "name", ...columns].map((cid) => {
                      const sorted = sort.field === cid;
                      const label = cid === "symbol" ? "Symbol" : cid === "name" ? "Name" : byId[cid]?.label ?? cid;
                      return (
                        <th key={cid} scope="col" aria-sort={sorted ? (sort.descending ? "descending" : "ascending") : "none"}
                          className={cn("px-3 py-2 font-medium", cid === "symbol" || cid === "name" || byId[cid]?.type === "category" ? "text-left" : "text-right")}>
                          <button title={byId[cid]?.description} className="uppercase hover:text-fg"
                            onClick={() => { setSort((s) => ({ field: cid, descending: s.field === cid ? !s.descending : true })); setPage(1); }}>
                            {label}{sorted && <span className="ml-1 text-accent">{sort.descending ? "↓" : "↑"}</span>}
                          </button>
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {d.rows.map((r) => (
                    <tr key={String(r.symbol)} className="border-b border-line/50 hover:bg-bg-2">
                      <td className="px-3 py-1.5">
                        <Link href={universe === "funds" ? `/funds/${r.symbol}` : `/equities/${r.symbol}`} className="font-mono font-semibold text-accent hover:underline">{String(r.symbol)}</Link>
                      </td>
                      <td className="px-3 py-1.5 text-muted">{String(r.name ?? "")}</td>
                      {columns.map((cid) => (
                        <td key={cid} className={cn("px-3 py-1.5", byId[cid]?.type === "category" ? "text-left" : "num text-right")}>{cell(cid, r[cid])}</td>
                      ))}
                    </tr>
                  ))}
                  {d.rows.length === 0 && (
                    <tr><td colSpan={columns.length + 2} className="px-3 py-4 text-muted">No instruments match these conditions.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-3 py-2 text-[11px] text-muted">
              <span>
                {d.missing_by_condition.filter((m) => m.excluded_missing > 0).map((m) => (
                  <Badge key={`${m.field}-${m.operator}`} variant="warn">{byId[m.field]?.label ?? m.field}: {m.excluded_missing} missing</Badge>
                ))}
                {d.as_of && <span className="ml-2">as of {fmt.date(d.as_of)}</span>}
              </span>
              <span className="flex items-center gap-2">
                <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)} className="rounded px-2 py-0.5 ring-1 ring-line disabled:opacity-40">‹</button>
                <span className="num">{page} / {pages}</span>
                <button disabled={page >= pages} onClick={() => setPage((p) => p + 1)} className="rounded px-2 py-0.5 ring-1 ring-line disabled:opacity-40">›</button>
              </span>
            </div>
          </>
        )}
      </Panel>
    </div>
  );
}
