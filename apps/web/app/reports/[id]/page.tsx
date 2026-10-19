import { notFound, redirect } from "next/navigation";

import { ErrorBlock } from "@/components/ui/primitives";
import { ReportView, type ReportOut } from "@/features/reports/report-view";
import { ServerApiError, serverApi } from "@/lib/server-api";

export const dynamic = "force-dynamic";

export default async function ReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    return <ReportView report={await serverApi<ReportOut>(`/api/v1/reports/${encodeURIComponent(id)}`)} />;
  } catch (e) {
    if (e instanceof ServerApiError && e.status === 401) redirect("/login");
    if (e instanceof ServerApiError && e.status === 404) notFound();
    return <ErrorBlock message={(e as Error).message} />;
  }
}
