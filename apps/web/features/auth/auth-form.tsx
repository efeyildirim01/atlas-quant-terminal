"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { z } from "zod";

import { useI18n } from "@/components/providers";
import { ApiError, apiFetch } from "@/lib/api-client";

export const LoginSchema = z.object({
  email: z.string().trim().email("Enter a valid email address"),
  password: z.string().min(1, "Password is required"),
});
export const RegisterSchema = LoginSchema.extend({
  password: z.string().min(12, "Use at least 12 characters"),
});

const SessionOut = z.object({ user: z.object({ email: z.string(), role: z.string() }), csrf_token: z.string() });

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const { t } = useI18n();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const parsed = (mode === "login" ? LoginSchema : RegisterSchema).safeParse({ email, password });
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Invalid input");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/v1/auth/${mode}`, SessionOut, { method: "POST", body: JSON.stringify(parsed.data) });
      router.push("/dashboard");
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} noValidate className="mx-auto mt-16 w-full max-w-sm space-y-3 rounded-md border border-line bg-panel p-5" aria-label={mode}>
      <h1 className="text-base font-semibold">{mode === "login" ? t.shell.signIn : t.shell.register}</h1>
      <label className="block text-[12px] text-muted">
        Email
        <input type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} className="mt-1 w-full rounded border border-line bg-bg-2 px-2 py-1.5 text-[13px] text-fg" />
      </label>
      <label className="block text-[12px] text-muted">
        Password
        <input
          type="password"
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="mt-1 w-full rounded border border-line bg-bg-2 px-2 py-1.5 text-[13px] text-fg"
        />
      </label>
      {error && (
        <p role="alert" className="text-[12px] text-down">
          {error}
        </p>
      )}
      <button disabled={busy} className="w-full rounded bg-accent py-1.5 text-[13px] font-medium text-white hover:bg-accent/90 disabled:opacity-50">
        {busy ? t.common.loading : mode === "login" ? t.shell.signIn : t.shell.register}
      </button>
      <p className="text-center text-[12px] text-muted">
        {mode === "login" ? (
          <Link href="/register" className="text-accent hover:underline">{t.shell.register}</Link>
        ) : (
          <Link href="/login" className="text-accent hover:underline">{t.shell.signIn}</Link>
        )}
      </p>
    </form>
  );
}
