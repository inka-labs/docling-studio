/** One option of a Docling command, drawn from what Docling says about it (cli_schema.py): a
 *  switch for on/off, chips or a list for fixed choices, a text box with suggestions for the
 *  options whose help lists their values, numbers, paths, and secrets (never saved). */
import { useId, useState } from "react";
import type { Field, Values } from "../api";

export function isEmpty(v: unknown): boolean {
  return v === undefined || v === null || v === "" || (Array.isArray(v) && v.length === 0);
}

/** Whether a value differs from Docling's own default (so the command will carry it). */
export function differs(field: Field, value: unknown): boolean {
  const d = field.default;
  if (field.multiple) return JSON.stringify(value ?? []) !== JSON.stringify(d ?? []);
  if (field.type === "bool") return typeof value === "boolean" && value !== (d ?? false);
  if (isEmpty(value)) return false;
  if (d === null || d === undefined) return true;
  if (field.type === "int" || field.type === "float" || field.count) return Number(value) !== Number(d);
  return String(value) !== String(d);
}

/** When an option only matters with others set ("Used with --pipeline vlm"): null when it does now. */
export function unmet(field: Field, values: Values, byName: Record<string, Field>): string | null {
  if (!field.when) return null;
  const missing: string[] = [];
  for (const [other, need] of Object.entries(field.when)) {
    const f = byName[other];
    if (!f) continue;
    const v = values[other] ?? f.initial;
    const flag = f.opts[0];
    if (need === true) {
      if (f.type === "bool" ? v !== true : isEmpty(v)) missing.push(f.type === "bool" ? flag : `${flag} set`);
    } else if (Array.isArray(need)) {
      const have = Array.isArray(v) ? v.map(String) : [String(v ?? "")];
      if (!need.some((n) => have.includes(n))) missing.push(`${flag} ${need.join(" or ")}`);
    }
  }
  return missing.length ? `Used with ${missing.join(", ")}` : null;
}

function flagText(field: Field): string {
  if (field.kind === "argument") return field.name.toUpperCase();
  const main = field.opts.find((o) => o.startsWith("--")) ?? field.opts[0];
  return field.secondary_opts.length ? `${main} / ${field.secondary_opts[0]}` : main;
}

function Help({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  if (!text) return null;
  const long = text.length > 220;
  return (
    <div className={`field-help${long && !open ? " clamp" : ""}`} onClick={() => long && setOpen(!open)} title={long && !open ? "Show all" : undefined}>
      {text}
    </div>
  );
}

export function FieldInput({ field, value, onChange, note, highlight }: {
  field: Field;
  value: unknown;
  onChange: (v: unknown) => void;
  note?: string | null;
  highlight?: boolean;
}) {
  const id = useId();
  const changed = differs(field, value);
  const cls = `field${note ? " dim" : ""}${changed ? " changed" : ""}`;
  const wide = field.multiple && (field.choices?.length ?? field.suggestions?.length ?? 0) > 8;

  const label = (
    <div className="field-label">
      <label htmlFor={id}>{field.label}</label>
      <span className="field-flag">{flagText(field)}</span>
      {field.required && <span className="badge warn">required</span>}
      {field.secret && <span className="badge" title="Never saved with the run or in presets; blanked out of the log">not saved</span>}
    </div>
  );
  const footer = (
    <>
      <Help text={field.help} />
      {note && <div className="field-when">{note}</div>}
    </>
  );

  if (field.type === "bool") {
    return (
      <div className={cls} style={highlight ? { outline: "2px solid var(--accent-soft)" } : undefined}>
        <div className="bool-row">
          <label className="switch">
            <input id={id} type="checkbox" checked={value === true} onChange={(e) => onChange(e.target.checked)} />
            <span />
          </label>
          {label}
        </div>
        {footer}
      </div>
    );
  }

  let control;
  const choices = field.choices ?? [];
  const suggestions = field.suggestions ?? [];
  if (field.multiple && (choices.length || suggestions.length)) {
    const options = choices.length ? choices : suggestions;
    const list = Array.isArray(value) ? (value as string[]) : [];
    const custom = list.filter((v) => !options.includes(v));
    control = (
      <div className="chips" id={id} role="group" aria-label={field.label}>
        {options.map((c) => {
          const on = list.includes(c);
          return (
            <button type="button" key={c} className={`chip${on ? " on" : ""}`} aria-pressed={on}
              onClick={() => onChange(on ? list.filter((v) => v !== c) : [...list, c])}>
              {field.choice_labels?.[c] ?? c}
            </button>
          );
        })}
        {custom.map((c) => (
          <button type="button" key={c} className="chip on" onClick={() => onChange(list.filter((v) => v !== c))}>{c} <span className="x">×</span></button>
        ))}
      </div>
    );
  } else if (field.multiple) {
    const list = Array.isArray(value) ? (value as string[]) : [];
    control = (
      <textarea id={id} rows={Math.max(2, list.length + 1)} placeholder="One per line"
        value={list.join("\n")} onChange={(e) => onChange(e.target.value.split("\n").map((s) => s.trim()).filter((s, i, a) => s || i === a.length - 1))}
        onBlur={(e) => onChange(e.target.value.split("\n").map((s) => s.trim()).filter(Boolean))} />
    );
  } else if (field.type === "choice") {
    const current = value === undefined || value === null ? String(field.default ?? "") : String(value);
    control = choices.length <= 5 ? (
      <div className="chips" id={id} role="radiogroup" aria-label={field.label}>
        {choices.map((c) => (
          <button type="button" key={c} role="radio" aria-checked={current === c} className={`chip${current === c ? " on" : ""}`} onClick={() => onChange(c)}>
            {field.choice_labels?.[c] ?? c}
            {String(field.default) === c && !field.count && <span className="muted small">·default</span>}
          </button>
        ))}
      </div>
    ) : (
      <select id={id} value={current} onChange={(e) => onChange(e.target.value)}>
        {!field.default && !field.required && <option value="">(Docling chooses)</option>}
        {choices.map((c) => (
          <option key={c} value={c}>{field.choice_labels?.[c] ?? c}{String(field.default) === c ? "  (default)" : ""}</option>
        ))}
      </select>
    );
  } else if (field.secret) {
    control = <SecretInput id={id} value={(value as string) ?? ""} onChange={onChange} json={field.name.endsWith("headers")} />;
  } else {
    const listId = suggestions.length ? `${id}-list` : undefined;
    const placeholder = field.default !== null && field.default !== undefined && field.default !== "" ? `${field.default} (default)` : field.type === "path" ? "Full path on this computer" : "";
    control = (
      <>
        <input id={id} type={field.type === "int" || field.type === "float" ? "number" : "text"} step={field.type === "float" ? "any" : undefined}
          value={(value as string | number | undefined) ?? ""} placeholder={placeholder} list={listId} spellCheck={false}
          onChange={(e) => onChange(e.target.value)} />
        {listId && (
          <datalist id={listId}>
            {suggestions.map((s) => <option key={s} value={s} />)}
          </datalist>
        )}
        {suggestions.length > 0 && !field.multiple && (
          <div className="chips">
            {suggestions.slice(0, 24).map((s) => (
              <button type="button" key={s} className={`chip${value === s ? " on" : ""}`} style={{ height: 24, fontSize: 12 }} onClick={() => onChange(value === s ? "" : s)}>{s}</button>
            ))}
          </div>
        )}
      </>
    );
  }

  return (
    <div className={`${cls}${wide ? " full" : ""}`}>
      {label}
      {control}
      {footer}
    </div>
  );
}

function SecretInput({ id, value, onChange, json }: { id: string; value: string; onChange: (v: unknown) => void; json: boolean }) {
  const [shown, setShown] = useState(false);
  let invalid = false;
  if (json && value.trim()) {
    try {
      const parsed = JSON.parse(value);
      invalid = typeof parsed !== "object" || parsed === null || Array.isArray(parsed);
    } catch {
      invalid = true;
    }
  }
  return (
    <>
      <div className="row" style={{ flexWrap: "nowrap" }}>
        <input id={id} type={shown ? "text" : "password"} value={value} autoComplete="off" spellCheck={false}
          placeholder={json ? '{"Authorization": "Bearer …"}' : ""} onChange={(e) => onChange(e.target.value)} />
        <button type="button" className="small" onClick={() => setShown(!shown)}>{shown ? "Hide" : "Show"}</button>
      </div>
      {invalid && <div className="field-when">Write the headers as a JSON object.</div>}
    </>
  );
}
