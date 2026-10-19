import { useCallback, useEffect, useState } from "react";

const KEY = "atlas.recentSearches.v1";
const MAX = 6;

export interface RecentItem {
  symbol: string;
  name: string;
  instrument_type: string;
  href: string;
}

// Per-browser convenience only; storage may be unavailable (private mode), so every access is guarded.
export function useRecentSearches() {
  const [items, setItems] = useState<RecentItem[]>([]);
  useEffect(() => {
    try {
      setItems(JSON.parse(localStorage.getItem(KEY) ?? "[]"));
    } catch {
      setItems([]);
    }
  }, []);
  const push = useCallback((item: RecentItem) => {
    setItems((prev) => {
      const next = [item, ...prev.filter((p) => p.href !== item.href)].slice(0, MAX);
      try {
        localStorage.setItem(KEY, JSON.stringify(next));
      } catch {}
      return next;
    });
  }, []);
  return { items, push };
}
