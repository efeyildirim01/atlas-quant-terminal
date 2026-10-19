import "server-only";

import { cookies } from "next/headers";

import { DICTS, LOCALE_COOKIE, asLocale, type Locale } from "./i18n";

export async function getLocale(): Promise<Locale> {
  return asLocale((await cookies()).get(LOCALE_COOKIE)?.value);
}

export async function getDict() {
  const locale = await getLocale();
  return { locale, t: DICTS[locale] };
}
