// Browser-side client. Calls go to same-origin /api/* (proxied to FastAPI by next.config rewrites), so the session
// cookie is first-party and CSRF uses the double-submit header.
import type { z } from "zod";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public requestId?: string,
  ) {
    super(message);
  }
}

function csrfToken(): string | undefined {
  if (typeof document === "undefined") return undefined;
  return document.cookie
    .split("; ")
    .find((c) => c.startsWith("atlas_csrf="))
    ?.split("=")[1];
}

/** FastAPI errors: a string, an object with `message`, or a list of validation issues ({loc, msg}). */
export function errorDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => {
        const field = (d.loc ?? []).filter((x) => x !== "body" && typeof x === "string").join(".");
        const msg = (d.msg ?? "invalid value").replace(/^Value error, /, "");
        return field ? `${field}: ${msg}` : msg;
      })
      .join("; ");
  }
  if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: unknown }).message);
  return JSON.stringify(detail);
}

export async function apiFetch<S extends z.ZodTypeAny>(
  path: string,
  schema: S,
  init: RequestInit & { params?: Record<string, string | number | undefined> } = {},
): Promise<z.infer<S>> {
  const url = new URL(path, typeof window === "undefined" ? "http://localhost" : window.location.origin);
  for (const [k, v] of Object.entries(init.params ?? {})) if (v !== undefined && v !== "") url.searchParams.set(k, String(v));
  const headers = new Headers(init.headers);
  if (init.method && init.method !== "GET") {
    headers.set("content-type", "application/json");
    const token = csrfToken();
    if (token) headers.set("x-csrf-token", token);
  }
  let res: Response;
  try {
    res = await fetch(url.pathname + url.search, { ...init, headers, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, "Network error: the ATLAS API could not be reached.");
  }
  const rid = res.headers.get("x-request-id") ?? undefined;
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = errorDetail(body.detail);
    } catch {}
    throw new ApiError(res.status, detail, rid);
  }
  if (res.status === 204) return undefined as z.infer<S>;
  const json = await res.json();
  const parsed = schema.safeParse(json);
  if (!parsed.success) {
    throw new ApiError(res.status, `Response failed contract validation: ${parsed.error.issues[0]?.message ?? "unknown"}`, rid);
  }
  return parsed.data;
}
