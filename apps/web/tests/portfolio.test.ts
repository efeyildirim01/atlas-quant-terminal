import { describe, expect, it } from "vitest";

import { TxnFormSchema } from "@/features/portfolio/transaction-form";

describe("transaction form validation", () => {
  it("requires instrument, quantity and price for trades and never fills a price in", () => {
    const missingPrice = TxnFormSchema.safeParse({ transaction_type: "buy", transaction_date: "2025-01-02", symbol: "D-BNK1", quantity: "10", price: "", commission: "" });
    expect(missingPrice.success).toBe(false);
    const ok = TxnFormSchema.safeParse({ transaction_type: "buy", transaction_date: "2025-01-02", symbol: "D-BNK1", quantity: "10", price: "20,5", commission: "" });
    expect(ok.success && ok.data).toMatchObject({ price: "20.5", commission: "0" }); // Turkish decimal comma accepted
  });

  it("rejects non-positive amounts and malformed dates", () => {
    expect(TxnFormSchema.safeParse({ transaction_type: "deposit", transaction_date: "2025-01-02", amount: "0" }).success).toBe(false);
    expect(TxnFormSchema.safeParse({ transaction_type: "deposit", transaction_date: "2025-01-02", amount: "-5" }).success).toBe(false);
    expect(TxnFormSchema.safeParse({ transaction_type: "deposit", transaction_date: "02/01/2025", amount: "5" }).success).toBe(false);
    expect(TxnFormSchema.safeParse({ transaction_type: "fee", transaction_date: "2025-01-02", amount: "12.5" }).success).toBe(true);
  });
});
