"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";

import { useI18n } from "@/components/providers";
import { Badge } from "@/components/ui/primitives";
import { useDebounced } from "@/hooks/use-debounced";
import { useRecentSearches, type RecentItem } from "@/hooks/use-recent-searches";
import { apiFetch } from "@/lib/api-client";
import { cn } from "@/lib/format";
import { SearchResult, type TSearchHit } from "@/lib/schemas";

const GROUP_ORDER = ["equities", "indices", "funds", "other"] as const;
const GROUP_LABEL: Record<string, string> = { equities: "Equities", indices: "Indices", funds: "Funds", other: "Other" };

export function hrefFor(hit: { symbol: string; instrument_type: string }): string {
  return hit.instrument_type === "fund" ? `/funds/${hit.symbol}` : `/equities/${hit.symbol}`;
}

export function Highlighted({ text, spans }: { text: string; spans: [number, number][] }): ReactNode {
  if (!spans.length) return text;
  const [s, e] = spans[0];
  return (
    <>
      {text.slice(0, s)}
      <mark className="rounded-sm bg-accent/25 text-fg">{text.slice(s, e)}</mark>
      {text.slice(e)}
    </>
  );
}

export function InstrumentSearch() {
  const { t } = useI18n();
  const router = useRouter();
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const debounced = useDebounced(q.trim(), 150);
  const recent = useRecentSearches();

  const { data, isFetching, isError } = useQuery({
    queryKey: ["search", debounced],
    queryFn: () => apiFetch("/api/v1/search", SearchResult, { params: { q: debounced } }),
    enabled: debounced.length > 0,
    staleTime: 5 * 60_000,
  });

  const flat: (TSearchHit | RecentItem)[] = useMemo(() => {
    if (!debounced) return recent.items;
    if (!data) return [];
    return GROUP_ORDER.flatMap((g) => data.groups[g] ?? []);
  }, [data, debounced, recent.items]);

  useEffect(() => setActive(0), [debounced]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (e.key === "/" && !["INPUT", "TEXTAREA"].includes(target.tagName)) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const go = (item: TSearchHit | RecentItem) => {
    const href = "href" in item ? item.href : hrefFor(item);
    recent.push({ symbol: item.symbol, name: item.name, instrument_type: item.instrument_type, href });
    setOpen(false);
    setQ("");
    router.push(href);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((a) => Math.min(a + 1, flat.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter" && flat[active]) {
      e.preventDefault();
      go(flat[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
      inputRef.current?.blur();
    }
  };

  let index = -1;
  const row = (item: TSearchHit | RecentItem) => {
    index += 1;
    const i = index;
    const hit = "score" in item ? item : null;
    return (
      <li
        key={`${item.instrument_type}:${item.symbol}`}
        id={`${listId}-${i}`}
        role="option"
        aria-selected={i === active}
        onMouseDown={(e) => {
          e.preventDefault();
          go(item);
        }}
        onMouseEnter={() => setActive(i)}
        className={cn("flex cursor-pointer items-center gap-3 px-3 py-1.5", i === active && "bg-bg-2")}
      >
        <span className="w-20 shrink-0 font-mono text-[12px] font-semibold text-accent">
          {hit && hit.match_field === "symbol" ? <Highlighted text={item.symbol} spans={hit.highlight} /> : item.symbol}
        </span>
        <span className="min-w-0 flex-1 truncate text-[12px] text-fg">
          {hit && hit.match_field === "name" ? <Highlighted text={item.name} spans={hit.highlight} /> : item.name}
          {hit?.subtitle && (
            <span className="ml-2 text-faint">
              {hit.match_field === "management_company" ? <Highlighted text={hit.subtitle} spans={hit.highlight} /> : hit.subtitle}
            </span>
          )}
        </span>
        {hit && <span className="font-mono text-[10px] text-faint">{hit.exchange}</span>}
        {hit?.is_fixture && <Badge variant="warn">Fixture</Badge>}
      </li>
    );
  };

  const showList = open && (debounced ? true : recent.items.length > 0);

  return (
    <div className="relative w-full max-w-xl">
      <input
        ref={inputRef}
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-activedescendant={showList && flat[active] ? `${listId}-${active}` : undefined}
        aria-autocomplete="list"
        aria-label={t.shell.search}
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={onKeyDown}
        placeholder={`${t.shell.search}  ( / )`}
        className="w-full rounded border border-line bg-bg-2 px-3 py-1.5 text-[12.5px] text-fg outline-none placeholder:text-faint focus:border-accent/60"
      />
      {showList && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 max-h-[420px] overflow-y-auto rounded-md border border-line bg-panel shadow-2xl">
          <ul id={listId} role="listbox" aria-label={t.shell.search}>
            {!debounced && (
              <>
                <li className="px-3 pb-1 pt-2 text-[10px] uppercase tracking-[0.08em] text-faint">{t.common.recent}</li>
                {recent.items.map(row)}
              </>
            )}
            {debounced && isError && <li className="px-3 py-2 text-[12px] text-down">Search failed. The API is unreachable.</li>}
            {debounced && data?.corrected && <li className="px-3 pt-2 text-[11px] text-warn">{t.common.didYouMean}</li>}
            {debounced &&
              data &&
              GROUP_ORDER.filter((g) => data.groups[g]?.length).map((g) => (
                <li key={g} role="presentation">
                  <div className="px-3 pb-1 pt-2 text-[10px] uppercase tracking-[0.08em] text-faint">{GROUP_LABEL[g]}</div>
                  <ul role="group" aria-label={GROUP_LABEL[g]}>
                    {data.groups[g].map(row)}
                  </ul>
                </li>
              ))}
            {debounced && data && flat.length === 0 && !isFetching && <li className="px-3 py-2 text-[12px] text-muted">{t.common.noResults}</li>}
          </ul>
        </div>
      )}
    </div>
  );
}
