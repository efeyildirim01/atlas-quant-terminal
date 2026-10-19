"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { z } from "zod";

import { useI18n } from "@/components/providers";
import { ApiError, apiFetch } from "@/lib/api-client";

export const TXN_TYPES = ["deposit", "buy", "sell", "dividend", "fee", "withdrawal"] as const;
export type TxnType = (typeof TXN_TYPES)[number];
const TRADE: TxnType[] = ["buy", "sell"];

const positive = (label: string) =>
  z
    .string()
    .trim()
    .transform((s) => s.replace(",", "."))
    .refine((s) => /^\d+(\.\d+)?$/.test(s) && Number(s) > 0, `${label} must be a positive number`);

/** Client-side shape check (the server re-validates and also replays the whole ledger). */
export const TxnFormSchema = z.discriminatedUnion("transaction_type", [
  z.object({
    transaction_type: z.enum(["buy", "sell"]),
    transaction_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "Pick a date"),
    symbol: z.string().min(1, "Pick an instrument"),
    quantity: positive("Quantity"),
    price: positive("Price"),
    commission: z
      .string()
      .trim()
      .transform((s) => (s === "" ? "0" : s.replace(",", ".")))
      .refine((s) => /^\d+(\.\d+)?$/.test(s), "Commission must be ≥ 0"),
  }),
  z.object({
    transaction_type: z.enum(["deposit", "withdrawal", "dividend", "fee"]),
    transaction_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "Pick a date"),
    amount: positive("Amount"),
  }),
]);

const Out = z.object({ transaction_id: z.number() });

export function TransactionForm({
  portfolioId,
  instruments,
  defaultDate,
}: {
  portfolioId: string;
  instruments: { symbol: string; name: string; instrument_type: string }[];
  defaultDate: string;
}) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const [type, setType] = useState<TxnType>("deposit");
  const [form, setForm] = useState({ transaction_date: defaultDate, symbol: "", quantity: "", price: "", commission: "", amount: "" });
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const trade = TRADE.includes(type);

  const m = useMutation({
    mutationFn: (body: object) =>
      apiFetch(`/api/v1/portfolios/${portfolioId}/transactions`, Out, { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => {
      setError(null);
      setForm((f) => ({ ...f, quantity: "", price: "", commission: "", amount: "" }));
      qc.invalidateQueries({ queryKey: ["portfolio", portfolioId] });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : String(e)),
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const raw = trade
      ? { transaction_type: type, transaction_date: form.transaction_date, symbol: form.symbol, quantity: form.quantity, price: form.price, commission: form.commission }
      : { transaction_type: type, transaction_date: form.transaction_date, amount: form.amount };
    const parsed = TxnFormSchema.safeParse(raw);
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Invalid input");
      return;
    }
    m.mutate(parsed.data);
  };

  const input = "num w-full rounded border border-line bg-bg-2 px-2 py-1 text-[12px] text-fg";
  return (
    <form onSubmit={submit} noValidate aria-label={t.portfolio.addTransaction} aria-busy={m.isPending}>
      {/* Locked while a submission is in flight, so the post-success reset can never wipe values typed meanwhile. */}
      <fieldset disabled={m.isPending} className="grid grid-cols-2 gap-2 p-3 text-[11.5px] text-muted disabled:opacity-60 md:grid-cols-4 xl:grid-cols-8">
      <label className="col-span-1">
        Type
        <select aria-label="Transaction type" value={type} onChange={(e) => setType(e.target.value as TxnType)} className={input}>
          {TXN_TYPES.map((x) => (
            <option key={x} value={x}>{x}</option>
          ))}
        </select>
      </label>
      <label>
        Date
        <input aria-label="Date" type="date" value={form.transaction_date} max={defaultDate} onChange={set("transaction_date")} className={input} />
      </label>
      {trade ? (
        <>
          <label className="col-span-2">
            Instrument
            <select aria-label="Instrument" value={form.symbol} onChange={set("symbol")} className={input}>
              <option value="">—</option>
              {instruments.map((i) => (
                <option key={i.symbol} value={i.symbol}>
                  {i.symbol} · {i.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Quantity
            <input aria-label="Quantity" inputMode="decimal" value={form.quantity} onChange={set("quantity")} className={input} />
          </label>
          <label>
            Price (TRY)
            <input aria-label="Price" inputMode="decimal" value={form.price} onChange={set("price")} className={input} />
          </label>
          <label>
            Commission
            <input aria-label="Commission" inputMode="decimal" value={form.commission} onChange={set("commission")} placeholder="0" className={input} />
          </label>
        </>
      ) : (
        <label className="col-span-2">
          Amount (TRY)
          <input aria-label="Amount" inputMode="decimal" value={form.amount} onChange={set("amount")} className={input} />
        </label>
      )}
      <div className="flex items-end">
        <button disabled={m.isPending} className="w-full rounded bg-accent px-2 py-1.5 text-[12px] font-medium text-white hover:bg-accent/90 disabled:opacity-50">
          {t.portfolio.add}
        </button>
      </div>
      {error && (
        <p role="alert" className="col-span-full text-[12px] text-down">
          {error}
        </p>
      )}
      <p className="col-span-full text-[10.5px] text-faint">
        Enter the executed price yourself; it is never filled in from market data. Every entry is checked against the full ledger
        (no short selling, no negative cash).
      </p>
      </fieldset>
    </form>
  );
}
