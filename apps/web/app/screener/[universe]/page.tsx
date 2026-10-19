import { notFound } from "next/navigation";

import { ErrorBlock } from "@/components/ui/primitives";
import type { FieldDef } from "@/features/screener/builder";
import { ScreenerWorkspace, type Preset, type Universe } from "@/features/screener/screener-workspace";
import { serverApi } from "@/lib/server-api";

export const dynamic = "force-dynamic";

export default async function ScreenerPage({ params }: { params: Promise<{ universe: string }> }) {
  const { universe } = await params;
  if (universe !== "equities" && universe !== "funds") notFound();
  try {
    const [fields, presets, me] = await Promise.all([
      serverApi<FieldDef[]>(`/api/v1/screener/${universe}/fields`),
      serverApi<Preset[]>(`/api/v1/screener/${universe}/presets`),
      serverApi("/api/v1/auth/me").then(() => true, () => false),
    ]);
    return <ScreenerWorkspace key={universe} universe={universe as Universe} fields={fields} presets={presets} signedIn={me} />;
  } catch (e) {
    return <ErrorBlock message={(e as Error).message} />;
  }
}
