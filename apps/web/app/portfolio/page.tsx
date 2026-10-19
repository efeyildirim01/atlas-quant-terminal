import Link from "next/link";

import { ErrorBlock, Panel } from "@/components/ui/primitives";
import { PortfolioWorkspace, type InstrumentOption } from "@/features/portfolio/portfolio-workspace";
import { getDict } from "@/lib/locale-server";
import { ServerApiError, serverApi } from "@/lib/server-api";

export const dynamic = "force-dynamic";

export default async function PortfolioPage() {
  const { t } = await getDict();
  try {
    await serverApi("/api/v1/auth/me");
  } catch (e) {
    if (e instanceof ServerApiError && e.status === 401) {
      return (
        <Panel className="m-4 max-w-lg">
          <div className="space-y-2 p-4 text-[13px]">
            <p>{t.portfolio.signInRequired}</p>
            <Link href="/login" className="inline-block rounded bg-accent px-3 py-1 text-[12px] font-medium text-white">{t.shell.signIn}</Link>
          </div>
        </Panel>
      );
    }
    return <ErrorBlock message={(e as Error).message} />;
  }
  const inst = await serverApi<{ items: InstrumentOption[] }>("/api/v1/instruments", { page_size: 200 });
  const status = await serverApi<{ local_time: string }>("/api/v1/system/market-status");
  const instruments = inst.items.filter((i) => i.instrument_type === "equity" || i.instrument_type === "fund");
  return <PortfolioWorkspace instruments={instruments} today={status.local_time.slice(0, 10)} />;
}
