import { notFound } from "next/navigation";

import { ErrorBlock } from "@/components/ui/primitives";
import { EquityWorkspace } from "@/features/equity/equity-workspace";
import type { EquityProfile } from "@/features/equity/types";
import { ServerApiError, serverApi } from "@/lib/server-api";

export const dynamic = "force-dynamic";

export default async function EquityPage({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = await params;
  let profile: EquityProfile;
  try {
    profile = await serverApi<EquityProfile>(`/api/v1/equities/${encodeURIComponent(decodeURIComponent(symbol))}`);
  } catch (e) {
    if (e instanceof ServerApiError && e.status === 404) notFound();
    return <ErrorBlock message={(e as Error).message} />;
  }
  return <EquityWorkspace profile={profile} />;
}
