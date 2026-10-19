import { notFound } from "next/navigation";

import { ErrorBlock } from "@/components/ui/primitives";
import { FundDetailView, type FundPerformanceData, type FundProfileData } from "@/features/funds/fund-views";
import type { Env } from "@/lib/schemas";
import { ServerApiError, serverApi } from "@/lib/server-api";

export const dynamic = "force-dynamic";

export default async function FundPage({ params }: { params: Promise<{ code: string }> }) {
  const { code } = await params;
  const c = encodeURIComponent(decodeURIComponent(code));
  try {
    const [profile, perf] = await Promise.all([
      serverApi<Env<FundProfileData>>(`/api/v1/funds/${c}`),
      serverApi<Env<FundPerformanceData>>(`/api/v1/funds/${c}/performance`),
    ]);
    return <FundDetailView profile={profile} perf={perf} />;
  } catch (e) {
    if (e instanceof ServerApiError && e.status === 404) notFound();
    return <ErrorBlock message={(e as Error).message} />;
  }
}
