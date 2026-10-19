import { ErrorBlock } from "@/components/ui/primitives";
import { CompareView } from "@/features/funds/compare-view";
import type { FundRow } from "@/features/funds/fund-table";
import type { Env } from "@/lib/schemas";
import { serverApi } from "@/lib/server-api";

export const dynamic = "force-dynamic";

export default async function ComparePage({ searchParams }: { searchParams: Promise<{ codes?: string }> }) {
  const codes = ((await searchParams).codes ?? "").split(",").map((c) => c.trim()).filter(Boolean);
  try {
    const list = await serverApi<Env<{ items: FundRow[] }>>("/api/v1/funds", { page_size: 200 });
    return <CompareView funds={list.data.items} codes={[...new Set(codes)]} />;
  } catch (e) {
    return <ErrorBlock message={(e as Error).message} />;
  }
}
