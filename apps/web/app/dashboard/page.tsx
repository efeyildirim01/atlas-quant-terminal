import { ErrorBlock } from "@/components/ui/primitives";
import { DashboardView, type SourceRow } from "@/features/dashboard/dashboard-view";
import type { OverviewEnv } from "@/features/dashboard/types";
import { serverApi } from "@/lib/server-api";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  try {
    const [overview, sources] = await Promise.all([
      serverApi<OverviewEnv>("/api/v1/market/overview"),
      serverApi<SourceRow[]>("/api/v1/system/sources"),
    ]);
    return <DashboardView overview={overview} sources={sources} />;
  } catch (e) {
    return <ErrorBlock message={(e as Error).message} />;
  }
}
