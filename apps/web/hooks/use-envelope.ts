import { useQuery } from "@tanstack/react-query";
import type { z } from "zod";

import { apiFetch } from "@/lib/api-client";
import { envelope } from "@/lib/schemas";

/** Fetch + validate an API envelope whose `data` matches `schema`. */
export function useEnvelope<S extends z.ZodTypeAny>(
  path: string,
  schema: S,
  params: Record<string, string | number | undefined> = {},
  enabled = true,
) {
  return useQuery({
    queryKey: [path, params],
    queryFn: () => apiFetch(path, envelope(schema), { params }),
    enabled,
    placeholderData: (prev) => prev, // keep the previous window on screen while the next loads
  });
}
