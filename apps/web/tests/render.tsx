import { render } from "@testing-library/react";
import type { ReactElement } from "react";

import { Providers } from "@/components/providers";
import type { Locale } from "@/lib/i18n";

export function renderWithProviders(ui: ReactElement, locale: Locale = "en") {
  return render(<Providers locale={locale}>{ui}</Providers>);
}

export function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "x-request-id": "test-req-1" } });
}
