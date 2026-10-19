import { describe, expect, it } from "vitest";

import { countConditions, fromApi, newCondition, newGroup, toApi, type ApiGroup, type FieldDef } from "@/features/screener/builder";

const F = (id: string, type: FieldDef["type"], unit: string | null = null, available = true): FieldDef => ({
  id, label: id, group: "g", type, unit, description: "", available, reason: available ? null : "licence",
});
const fields = Object.fromEntries(
  [F("chg_1y", "number", "fraction"), F("close", "number", "TRY"), F("sector", "category"), F("above_sma200", "boolean"), F("pe", "number", "ratio", false)].map((f) => [f.id, f]),
);

describe("screen builder → API", () => {
  it("converts percent inputs to decimals and accepts a Turkish decimal comma", () => {
    const g = newGroup("and");
    g.children.push({ ...newCondition(fields.chg_1y), operator: "gt", value: "12,5" });
    g.children.push({ ...newCondition(fields.close), operator: "between", value: "10", value2: "50" });
    const r = toApi(g, fields);
    expect(r.ok && r.filter).toEqual({
      op: "and",
      conditions: [
        { field: "chg_1y", operator: "gt", value: 0.125 },
        { field: "close", operator: "between", value: 10, value2: 50 },
      ],
    });
  });

  it("builds nested OR groups and category/boolean conditions", () => {
    const g = newGroup("and");
    const inner = newGroup("or");
    inner.children.push({ ...newCondition(fields.sector), operator: "in", values: ["Banking", "Energy"] });
    inner.children.push({ ...newCondition(fields.above_sma200), operator: "is_true" });
    g.children.push(inner);
    const r = toApi(g, fields);
    expect(r.ok && r.filter.conditions[0]).toEqual({
      op: "or",
      conditions: [{ field: "sector", operator: "in", value: ["Banking", "Energy"] }, { field: "above_sma200", operator: "is_true" }],
    });
    expect(countConditions(g)).toBe(2);
  });

  it("reports incomplete or invalid conditions instead of sending them", () => {
    const g = newGroup("and");
    g.children.push({ ...newCondition(fields.close), operator: "between", value: "50", value2: "10" });
    expect(toApi(g, fields)).toEqual({ ok: false, error: "close: lower bound is above upper bound" });
    g.children[0] = { ...newCondition(fields.chg_1y), value: "abc" };
    expect(toApi(g, fields)).toMatchObject({ ok: false, error: expect.stringContaining("(in %)") });
    g.children[0] = { ...newCondition(fields.pe), value: "10" };
    expect(toApi(g, fields)).toMatchObject({ ok: false, error: expect.stringContaining("not available") });
  });

  it("round-trips presets/saved screens through the builder", () => {
    const api: ApiGroup = {
      op: "or",
      conditions: [{ op: "and", conditions: [{ field: "chg_1y", operator: "gt", value: 0.2 }] }, { field: "sector", operator: "eq", value: "Banking" }],
    };
    const g = fromApi(api, fields);
    expect(g.children[0].kind === "group" && g.children[0].children[0].kind === "cond" && g.children[0].children[0].value).toBe("20");
    const back = toApi(g, fields);
    expect(back.ok && back.filter).toEqual(api);
  });
});
