import Link from "next/link";

import { ErrorBlock, Panel } from "@/components/ui/primitives";
import { ReportsView } from "@/features/reports/reports-view";
import { getDict } from "@/lib/locale-server";
import { ServerApiError, serverApi } from "@/lib/server-api";

export const dynamic = "force-dynamic";

export default async function ReportsPage() {
  const { t } = await getDict();
  try {
    await serverApi("/api/v1/auth/me");
  } catch (e) {
    if (e instanceof ServerApiError && e.status === 401)
      return (
        <Panel className="m-4 max-w-lg">
          <div className="space-y-2 p-4 text-[13px]">
            <p>{t.reports.signInRequired}</p>
            <Link href="/login" className="inline-block rounded bg-accent px-3 py-1 text-[12px] font-medium text-white">{t.shell.signIn}</Link>
          </div>
        </Panel>
      );
    return <ErrorBlock message={(e as Error).message} />;
  }
  const funds = await serverApi<{ data: { items: { symbol: string; fund_name: string; category: string | null }[] } }>("/api/v1/funds", { page_size: 200 });
  return <ReportsView funds={funds.data.items} />;
}
