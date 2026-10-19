import { ErrorBlock } from "@/components/ui/primitives";
import { EquitiesView } from "@/features/equity/equities-view";
import type { OverviewEnv } from "@/features/dashboard/types";
import { serverApi } from "@/lib/server-api";

export const dynamic = "force-dynamic";

export default async function EquitiesPage() {
  try {
    return <EquitiesView overview={await serverApi<OverviewEnv>("/api/v1/market/overview")} />;
  } catch (e) {
    return <ErrorBlock message={(e as Error).message} />;
  }
}
