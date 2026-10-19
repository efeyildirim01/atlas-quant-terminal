import { ErrorBlock } from "@/components/ui/primitives";
import { BacktestWorkspace, type StrategySpec } from "@/features/backtest/backtest-workspace";
import { serverApi } from "@/lib/server-api";

export const dynamic = "force-dynamic";

export default async function BacktestPage() {
  try {
    const [strategies, equities, indices] = await Promise.all([
      serverApi<StrategySpec[]>("/api/v1/backtests/strategies"),
      serverApi<{ items: { symbol: string; name: string }[] }>("/api/v1/instruments", { instrument_type: "equity", page_size: 200 }),
      serverApi<{ items: { symbol: string; name: string }[] }>("/api/v1/instruments", { instrument_type: "index", page_size: 50 }),
    ]);
    const symbols = [...equities.items, ...indices.items].map(({ symbol, name }) => ({ symbol, name }));
    return <BacktestWorkspace strategies={strategies} symbols={symbols} />;
  } catch (e) {
    return <ErrorBlock message={(e as Error).message} />;
  }
}
