import { ErrorBlock } from "@/components/ui/primitives";
import type { FundRow } from "@/features/funds/fund-table";
import { FundsView } from "@/features/funds/fund-views";
import type { Env } from "@/lib/schemas";
import { serverApi } from "@/lib/server-api";

export const dynamic = "force-dynamic";

export default async function FundsPage() {
  try {
    return <FundsView env={await serverApi<Env<{ items: FundRow[]; total: number }>>("/api/v1/funds", { page_size: 200 })} />;
  } catch (e) {
    return <ErrorBlock message={(e as Error).message} />;
  }
}
