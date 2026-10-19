"use client";

import { Segmented } from "@/components/ui/primitives";
import { OPS, newCondition, newGroup, updateNode, type CondState, type FieldDef, type GroupState } from "./builder";

const UI_MAX_DEPTH = 2; // the API allows 3; two levels cover "A and (B or C)" without an unreadable UI

export function GroupEditor({
  root,
  node,
  depth,
  fields,
  categoryValues,
  onChange,
}: {
  root: GroupState;
  node: GroupState;
  depth: number;
  fields: FieldDef[];
  categoryValues: Record<string, string[]>;
  onChange: (next: GroupState) => void;
}) {
  const byId = Object.fromEntries(fields.map((f) => [f.id, f]));
  const firstAvailable = fields.find((f) => f.available)!;
  const groups = [...new Set(fields.map((f) => f.group))];
  const set = (id: string, fn: Parameters<typeof updateNode>[2]) => onChange(updateNode(root, id, fn));

  return (
    <div className={depth > 1 ? "rounded border border-line/70 bg-bg-2/40 p-2" : ""} data-testid={depth === 1 ? "screen-builder" : undefined}>
      <div className="mb-2 flex items-center gap-2 text-[11px] text-muted">
        <span>Match</span>
        <Segmented
          label={`Group logic level ${depth}`}
          options={[{ value: "and", label: "ALL (AND)" }, { value: "or", label: "ANY (OR)" }]}
          value={node.op}
          onChange={(op) => set(node.id, (n) => ({ ...(n as GroupState), op }))}
        />
        {depth > 1 && (
          <button onClick={() => set(node.id, () => null)} className="ml-auto text-faint hover:text-down" aria-label="Remove group">
            ✕ group
          </button>
        )}
      </div>
      <div className="space-y-1.5">
        {node.children.map((c) =>
          c.kind === "group" ? (
            <GroupEditor key={c.id} root={root} node={c} depth={depth + 1} fields={fields} categoryValues={categoryValues} onChange={onChange} />
          ) : (
            <ConditionRow key={c.id} c={c} f={byId[c.field]} fields={fields} groups={groups} options={categoryValues[c.field] ?? []}
              onChange={(next) => set(c.id, () => next)} onRemove={() => set(c.id, () => null)} />
          ),
        )}
      </div>
      <div className="mt-2 flex gap-2 text-[11px]">
        <button onClick={() => set(node.id, (n) => ({ ...(n as GroupState), children: [...(n as GroupState).children, newCondition(firstAvailable)] }))}
          className="rounded px-2 py-0.5 text-muted ring-1 ring-line hover:text-fg">
          + condition
        </button>
        {depth < UI_MAX_DEPTH && (
          <button onClick={() => set(node.id, (n) => ({ ...(n as GroupState), children: [...(n as GroupState).children, { ...newGroup(node.op === "and" ? "or" : "and"), children: [newCondition(firstAvailable)] }] }))}
            className="rounded px-2 py-0.5 text-muted ring-1 ring-line hover:text-fg">
            + group
          </button>
        )}
      </div>
    </div>
  );
}

function ConditionRow({
  c, f, fields, groups, options, onChange, onRemove,
}: {
  c: CondState;
  f: FieldDef | undefined;
  fields: FieldDef[];
  groups: string[];
  options: string[];
  onChange: (n: CondState) => void;
  onRemove: () => void;
}) {
  const input = "num rounded border border-line bg-bg-2 px-1.5 py-0.5 text-[11.5px] text-fg";
  const pct = f?.unit === "fraction";
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="condition-row">
      <select aria-label="Field" value={c.field} className={`${input} w-44`}
        onChange={(e) => {
          const nf = fields.find((x) => x.id === e.target.value)!;
          onChange({ ...c, field: nf.id, operator: OPS[nf.type][0].value, value: "", value2: "", values: [] });
        }}>
        {groups.map((g) => (
          <optgroup key={g} label={g}>
            {fields.filter((x) => x.group === g).map((x) => (
              <option key={x.id} value={x.id} disabled={!x.available} title={x.available ? x.description : x.reason ?? ""}>
                {x.label}{x.available ? "" : " (unavailable)"}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      {f && (
        <select aria-label="Operator" value={c.operator} onChange={(e) => onChange({ ...c, operator: e.target.value as CondState["operator"] })} className={input}>
          {OPS[f.type].map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      )}
      {f?.type === "number" && (
        <>
          <input aria-label="Value" value={c.value} onChange={(e) => onChange({ ...c, value: e.target.value })} inputMode="decimal" className={`${input} w-20 text-right`} />
          {c.operator === "between" && (
            <>
              <span className="text-faint">and</span>
              <input aria-label="Upper value" value={c.value2} onChange={(e) => onChange({ ...c, value2: e.target.value })} inputMode="decimal" className={`${input} w-20 text-right`} />
            </>
          )}
          <span className="text-faint">{pct ? "%" : f.unit === "TRY" ? "TRY" : ""}</span>
        </>
      )}
      {f?.type === "category" && (c.operator === "in" || c.operator === "not_in") && (
        <span className="flex flex-wrap gap-1">
          {options.map((o) => {
            const on = c.values.includes(o);
            return (
              <button key={o} aria-pressed={on} onClick={() => onChange({ ...c, values: on ? c.values.filter((x) => x !== o) : [...c.values, o] })}
                className={`rounded px-1.5 py-0.5 text-[11px] ring-1 ${on ? "bg-bg-2 text-fg ring-accent/60" : "text-muted ring-line"}`}>
                {o}
              </button>
            );
          })}
        </span>
      )}
      {f?.type === "category" && (c.operator === "eq" || c.operator === "neq") && (
        <select aria-label="Value" value={c.value} onChange={(e) => onChange({ ...c, value: e.target.value })} className={input}>
          <option value="">—</option>
          {options.map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>
      )}
      <button onClick={onRemove} aria-label="Remove condition" className="text-faint hover:text-down">✕</button>
    </div>
  );
}
