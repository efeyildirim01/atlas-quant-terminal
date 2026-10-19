// Screen builder state and its translation to the API filter language. Pure (unit-tested).
// Percent fields are edited as percentages (5 = 5%) and sent as decimals (0.05), matching API units.

export type FieldType = "number" | "category" | "boolean";

export interface FieldDef {
  id: string;
  label: string;
  group: string;
  type: FieldType;
  unit: string | null;
  description: string;
  available: boolean;
  reason: string | null;
}

export type Operator = "gt" | "gte" | "lt" | "lte" | "between" | "eq" | "neq" | "in" | "not_in" | "is_true" | "is_false";

export const OPS: Record<FieldType, { value: Operator; label: string }[]> = {
  number: [
    { value: "gt", label: ">" }, { value: "gte", label: "≥" }, { value: "lt", label: "<" }, { value: "lte", label: "≤" },
    { value: "between", label: "between" }, { value: "eq", label: "=" }, { value: "neq", label: "≠" },
  ],
  category: [
    { value: "in", label: "is any of" }, { value: "not_in", label: "is none of" }, { value: "eq", label: "=" }, { value: "neq", label: "≠" },
  ],
  boolean: [{ value: "is_true", label: "is true" }, { value: "is_false", label: "is false" }],
};

export interface CondState {
  kind: "cond";
  id: string;
  field: string;
  operator: Operator;
  value: string;
  value2: string;
  values: string[];
}

export interface GroupState {
  kind: "group";
  id: string;
  op: "and" | "or";
  children: (CondState | GroupState)[];
}

let seq = 0;
export const newId = () => `n${++seq}`;

export function newCondition(field: FieldDef): CondState {
  return { kind: "cond", id: newId(), field: field.id, operator: OPS[field.type][0].value, value: "", value2: "", values: [] };
}

export function newGroup(op: "and" | "or" = "and"): GroupState {
  return { kind: "group", id: newId(), op, children: [] };
}

const isPct = (f: FieldDef) => f.unit === "fraction";

function toNumber(raw: string, f: FieldDef): number | null {
  const s = raw.trim().replace(",", ".");
  if (!/^-?\d+(\.\d+)?$/.test(s)) return null;
  const n = Number(s);
  return isPct(f) ? n / 100 : n;
}

function fromNumber(v: number, f: FieldDef): string {
  const n = isPct(f) ? v * 100 : v;
  return String(Number(n.toPrecision(12)));
}

export type ApiCondition = { field: string; operator: Operator; value?: number | string | string[] | null; value2?: number | null };
export type ApiGroup = { op: "and" | "or"; conditions: (ApiCondition | ApiGroup)[] };

/** Builder → API. Returns the first problem as a readable message instead of sending an invalid screen. */
export function toApi(group: GroupState, fields: Record<string, FieldDef>): { ok: true; filter: ApiGroup } | { ok: false; error: string } {
  const walk = (g: GroupState): ApiGroup => ({
    op: g.op,
    conditions: g.children.map((c) => {
      if (c.kind === "group") return walk(c);
      const f = fields[c.field];
      if (!f || !f.available) throw new Error(`Field "${c.field}" is not available`);
      if (f.type === "boolean") return { field: f.id, operator: c.operator };
      if (f.type === "category") {
        if (c.operator === "in" || c.operator === "not_in") {
          if (!c.values.length) throw new Error(`${f.label}: pick at least one value`);
          return { field: f.id, operator: c.operator, value: c.values };
        }
        if (!c.value) throw new Error(`${f.label}: pick a value`);
        return { field: f.id, operator: c.operator, value: c.value };
      }
      const v = toNumber(c.value, f);
      if (v === null) throw new Error(`${f.label}: enter a number${isPct(f) ? " (in %)" : ""}`);
      if (c.operator === "between") {
        const v2 = toNumber(c.value2, f);
        if (v2 === null) throw new Error(`${f.label}: enter both bounds`);
        if (v > v2) throw new Error(`${f.label}: lower bound is above upper bound`);
        return { field: f.id, operator: "between", value: v, value2: v2 };
      }
      return { field: f.id, operator: c.operator, value: v };
    }),
  });
  try {
    return { ok: true, filter: walk(group) };
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }
}

/** API → builder (presets and saved screens). */
export function fromApi(g: ApiGroup, fields: Record<string, FieldDef>): GroupState {
  return {
    kind: "group",
    id: newId(),
    op: g.op,
    children: g.conditions.map((c) => {
      if ("conditions" in c) return fromApi(c, fields);
      const f = fields[c.field];
      const num = (x: unknown) => (typeof x === "number" && f ? fromNumber(x, f) : "");
      return {
        kind: "cond",
        id: newId(),
        field: c.field,
        operator: c.operator,
        value: typeof c.value === "string" ? c.value : num(c.value),
        value2: num(c.value2),
        values: Array.isArray(c.value) ? c.value : [],
      } satisfies CondState;
    }),
  };
}

export function countConditions(g: GroupState): number {
  return g.children.reduce((n, c) => n + (c.kind === "group" ? countConditions(c) : 1), 0);
}

export function updateNode(g: GroupState, id: string, fn: (n: CondState | GroupState) => CondState | GroupState | null): GroupState {
  if (g.id === id) return fn(g) as GroupState;
  return {
    ...g,
    children: g.children.flatMap((c) => {
      if (c.id === id) {
        const r = fn(c);
        return r ? [r] : [];
      }
      return c.kind === "group" ? [updateNode(c, id, fn)] : [c];
    }),
  };
}
