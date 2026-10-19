import { ErrorBlock } from "@/components/ui/primitives";
import { HealthView, type Health } from "@/features/health/health-view";
import { serverApi } from "@/lib/server-api";

export const dynamic = "force-dynamic";

export default async function DataHealthPage() {
  try {
    return <HealthView health={await serverApi<Health>("/api/v1/system/data-health")} />;
  } catch (e) {
    return <ErrorBlock message={(e as Error).message} />;
  }
}
