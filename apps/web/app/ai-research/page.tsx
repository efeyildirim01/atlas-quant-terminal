import Link from "next/link";

import { ErrorBlock, Panel } from "@/components/ui/primitives";
import { ResearchWorkspace, type Status } from "@/features/research/research-workspace";
import { getDict } from "@/lib/locale-server";
import { ServerApiError, serverApi } from "@/lib/server-api";

export const dynamic = "force-dynamic";

export default async function AiResearchPage() {
  const { t } = await getDict();
  try {
    await serverApi("/api/v1/auth/me");
  } catch (e) {
    if (e instanceof ServerApiError && e.status === 401)
      return (
        <Panel className="m-4 max-w-lg">
          <div className="space-y-2 p-4 text-[13px]">
            <p>{t.research.signInRequired}</p>
            <Link href="/login" className="inline-block rounded bg-accent px-3 py-1 text-[12px] font-medium text-white">{t.shell.signIn}</Link>
          </div>
        </Panel>
      );
    return <ErrorBlock message={(e as Error).message} />;
  }
  return <ResearchWorkspace status={await serverApi<Status>("/api/v1/research/status")} />;
}
