import { describe, expect, it } from "vitest";

import { direction, makeFormat } from "@/lib/format";
import { DICTS } from "@/lib/i18n";

describe("locale-aware formatting", () => {
  const en = makeFormat("en");
  const tr = makeFormat("tr");

  it("formats percentages with explicit signs and locale decimals", () => {
    expect(en.pct(0.1234, 1, true)).toBe("+12.3%");
    expect(en.pct(-0.05, 2, true)).toBe("−5.00%");
    expect(tr.pct(0.1234, 1, true)).toBe("+12,3%");
    expect(tr.num(1234.5, 2)).toBe("1.234,50");
  });

  it("renders missing values as a dash, never as zero", () => {
    for (const f of [en.pct, en.num, en.compact] as ((x: number | null) => string)[]) {
      expect(f(null)).toBe("—");
      expect(f(Number.NaN)).toBe("—");
    }
  });

  it("does not rely on colour alone for direction", () => {
    expect(direction(0.01).glyph).toBe("▲");
    expect(direction(-0.01).glyph).toBe("▼");
    expect(direction(null).glyph).toBe("■");
  });
});

describe("dictionaries", () => {
  const keys = (o: object, prefix = ""): string[] =>
    Object.entries(o).flatMap(([k, v]) => (typeof v === "object" ? keys(v, `${prefix}${k}.`) : [`${prefix}${k}`]));

  it("Turkish covers every English key with a non-empty string", () => {
    expect(keys(DICTS.tr).sort()).toEqual(keys(DICTS.en).sort());
    const flat = (o: object): string[] => Object.values(o).flatMap((v) => (typeof v === "object" ? flat(v) : [v]));
    expect(flat(DICTS.tr).every((s) => typeof s === "string" && s.length > 0)).toBe(true);
  });
});
