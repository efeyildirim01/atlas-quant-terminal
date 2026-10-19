// Server-side (RSC) fetch straight to FastAPI, forwarding the user's cookies. Never imported by client components.
import "server-only";

import { cookies } from "next/headers";

export const API_URL = process.env.ATLAS_API_URL ?? "http://127.0.0.1:8000";

export class ServerApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function serverApi<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const url = new URL(path, API_URL);
  for (const [k, v] of Object.entries(params ?? {})) if (v !== undefined && v !== "") url.searchParams.set(k, String(v));
  const jar = await cookies();
  let res: Response;
  try {
    res = await fetch(url, { cache: "no-store", headers: { cookie: jar.toString() } });
  } catch {
    throw new ServerApiError(0, `Cannot reach the ATLAS API at ${API_URL}.`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const b = await res.json();
      detail = typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail);
    } catch {}
    throw new ServerApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}
