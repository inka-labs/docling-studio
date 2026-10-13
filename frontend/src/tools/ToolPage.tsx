/** A Docling command as a form: its inputs, every option it has (in sections), named presets, the
 *  exact command it will run, and Run. Convert is this page with tool "convert". */
import { useEffect, useMemo, useRef, useState } from "react";
import { api, changed, loadSchema, type Field, type Input, type Preset, type Service, type Tool, type Values } from "../api";
import { differs, FieldInput, isEmpty, unmet } from "../form/FieldInput";
import { Inputs } from "../form/Inputs";
import { href, navigate } from "../router";
import { confirm, prompt, toast } from "../ui/Dialogs";

/** Sections open at first, besides any with changes. */
const OPEN_FIRST = new Set(["input", "output", "models", "service", "contents", "checks", "other"]);

function initialValues(tool: Tool): Values {
  const v: Values = {};
  for (const f of tool.fields) if (!f.input) v[f.name] = f.initial;
  return v;
}

export default function ToolPage({ toolId, from, file }: { toolId: string; from?: string; file?: string }) {
  const [tool, setTool] = useState<Tool | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [values, setValues] = useState<Values>({});
  const [inputs, setInputs] = useState<Record<string, Input[]>>({});
  const [service, setService] = useState<string>("");
  const [services, setServices] = useState<Service[] | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [preset, setPreset] = useState<string>("");
  const [notice, setNotice] = useState<string | null>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [query, setQuery] = useState("");
  const [command, setCommand] = useState<{ command: string | null; error: string | null } | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    loadSchema()
      .then(async (schema) => {
        const t = schema.tools.find((x) => x.id === toolId);
        if (!t) throw new Error(`There's no tool called ${toolId}.`);
        if (!t.available) throw new Error(t.error ?? "This tool isn't available.");
        let v = initialValues(t);
        let ins: Record<string, Input[]> = {};
        if (from) {
          const again = await api.runAgain(from);
          v = { ...v, ...again.values };
          ins = again.inputs;
          if (again.service) setService(again.service);
          const lost = again.had_secrets.map((n) => t.fields.find((f) => f.name === n)?.label ?? n);
          setNotice(`Settings from the earlier run.${lost.length ? ` ${lost.join(" and ")} ${lost.length > 1 ? "weren't" : "wasn't"} kept: type ${lost.length > 1 ? "them" : "it"} again.` : ""}`);
        }
        if (file) {
          const [run, ...rest] = file.split(":");
          const arg = t.fields.find((f) => f.input)?.name;
          if (arg) ins = { ...ins, [arg]: [{ kind: "run", run, file: rest.join(":"), name: rest.join(":").split("/").pop() }] };
        }
        if (!alive) return;
        setTool(t);
        setValues(v);
        setInputs(ins);
        const firstOpen: Record<string, boolean> = {};
        for (const f of t.fields) if (OPEN_FIRST.has(f.section) || differs(f, v[f.name])) firstOpen[f.section] = true;
        setOpen(firstOpen);
        if (t.service) api.services().then((s) => { setServices(s); setService((cur) => cur || (s[0]?.name ?? "")); }).catch(() => setServices([]));
        api.presets(t.id).then(setPresets).catch(() => {});
      })
      .catch((e) => alive && setError((e as Error).message));
    return () => {
      alive = false;
    };
  }, [toolId, from, file]);

  const byName = useMemo(() => Object.fromEntries((tool?.fields ?? []).map((f) => [f.name, f])), [tool]);
  const inputFields = (tool?.fields ?? []).filter((f) => f.input);
  const optionFields = (tool?.fields ?? []).filter((f) => !f.input);

  const sections = useMemo(() => {
    const out: { key: string; title: string; fields: Field[] }[] = [];
    const q = query.trim().toLowerCase();
    for (const f of optionFields) {
      if (q && !`${f.label} ${f.opts.join(" ")} ${f.secondary_opts.join(" ")} ${f.help}`.toLowerCase().includes(q)) continue;
      let s = out.find((x) => x.key === f.section);
      if (!s) out.push((s = { key: f.section, title: f.section_title, fields: [] }));
      s.fields.push(f);
    }
    return out;
  }, [optionFields, query]);

  // the command it will run, kept up to date as the form changes
  const request = { tool: toolId, values, inputs, service: tool?.service ? service : null };
  const requestKey = JSON.stringify(request);
  const timer = useRef<number>(undefined);
  useEffect(() => {
    if (!tool) return;
    clearTimeout(timer.current);
    timer.current = window.setTimeout(() => api.preview(request).then(setCommand).catch(() => {}), 250);
    return () => clearTimeout(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey, tool]);

  if (error) return <div className="page"><div className="banner error">{error}</div></div>;
  if (!tool) return <div className="page"><p className="muted">Reading Docling's options…</p></div>;

  const set = (name: string, v: unknown) => setValues((cur) => ({ ...cur, [name]: v }));
  const changedCount = optionFields.filter((f) => differs(f, values[f.name])).length;
  const missingInput = inputFields.some((f) => f.required && !(inputs[f.name]?.length));

  const applyPreset = (id: string) => {
    setPreset(id);
    const p = presets.find((x) => x.id === id);
    if (!p) return;
    const v = { ...initialValues(tool), ...p.values };
    setValues(v);
    setOpen((cur) => ({ ...cur, ...Object.fromEntries(optionFields.filter((f) => differs(f, v[f.name])).map((f) => [f.section, true])) }));
    toast(`Preset “${p.name}” applied`);
  };
  const savePreset = async (asNew: boolean) => {
    const current = presets.find((p) => p.id === preset);
    const name = asNew || !current ? await prompt("Save these settings as a preset", { placeholder: "e.g. Scanned contracts, German OCR", value: current && asNew ? `${current.name} (copy)` : "" }) : current.name;
    if (!name) return;
    try {
      const saved = await api.savePreset(tool.id, name, values, asNew ? undefined : current?.id);
      const list = await api.presets(tool.id);
      setPresets(list);
      setPreset(saved.id);
      toast(`Saved “${saved.name}”${optionFields.some((f) => f.secret && !isEmpty(values[f.name])) ? " (without the secrets)" : ""}`);
    } catch (e) {
      toast((e as Error).message);
    }
  };
  const deletePreset = async () => {
    const current = presets.find((p) => p.id === preset);
    if (!current || !(await confirm(`Delete the preset “${current.name}”?`, { confirm: "Delete", danger: true }))) return;
    await api.deletePreset(current.id);
    setPresets(presets.filter((p) => p.id !== current.id));
    setPreset("");
  };

  const start = async () => {
    setStarting(true);
    setStartError(null);
    try {
      const run = await api.startRun(request);
      changed();
      navigate({ page: "run", id: run.id });
    } catch (e) {
      setStartError((e as Error).message);
      setStarting(false);
    }
  };

  return (
    <div className="page wide">
      <div className="page-head">
        <div className="grow">
          <h1>{tool.title}</h1>
          <div className="lede">{tool.summary}</div>
        </div>
        <code className="muted small" style={{ alignSelf: "center" }}>{tool.command}</code>
      </div>
      {notice && <div className="banner info">{notice}</div>}

      <div className="tool-layout">
        <div className="stack">
          {tool.service && (
            <div className="card">
              <div className="card-head"><h2>Service</h2></div>
              <div className="card-body">
                {services === null ? <p className="muted">Loading…</p> : services.length === 0 ? (
                  <p>No docling-serve service is saved yet. <a href={href({ page: "services" })}>Add one under Services</a>; its API key stays in your keychain.</p>
                ) : (
                  <select value={service} onChange={(e) => setService(e.target.value)} aria-label="Service">
                    {services.map((s) => <option key={s.name} value={s.name}>{s.name} · {s.url}{s.has_key ? " · API key" : ""}</option>)}
                  </select>
                )}
              </div>
            </div>
          )}

          {inputFields.map((f) => (
            <div className="card" key={f.name}>
              <div className="card-head">
                <h2>{f.input === "sources" ? "Documents" : f.label}</h2>
                <span className="grow" />
                <span className="field-flag">{f.name.toUpperCase()}</span>
              </div>
              <div className="card-body">
                <Inputs mode={f.input!} label={f.help} items={inputs[f.name] ?? []} onChange={(items) => setInputs((cur) => ({ ...cur, [f.name]: items }))} />
              </div>
            </div>
          ))}

          <div className="card">
            <div className="card-head">
              <h2>Options</h2>
              <span className="badge">{optionFields.length}</span>
              {changedCount > 0 && <span className="badge accent">{changedCount} changed</span>}
              <span className="grow" />
              <input type="text" placeholder="Find an option…" value={query} onChange={(e) => setQuery(e.target.value)} style={{ width: 200 }} aria-label="Find an option" />
              <button className="small" onClick={() => setOpen(Object.fromEntries(sections.map((s) => [s.key, !sections.every((x) => open[x.key])])))}>
                {sections.every((s) => open[s.key]) ? "Collapse all" : "Expand all"}
              </button>
            </div>
            {sections.length === 0 && <div className="card-body muted">{query ? "No option matches." : "This command has no options."}</div>}
            {sections.map((s) => {
              const isOpen = !!query || !!open[s.key];
              const n = s.fields.filter((f) => differs(f, values[f.name])).length;
              return (
                <div className="section" key={s.key}>
                  <button className="section-head" aria-expanded={isOpen} onClick={() => setOpen({ ...open, [s.key]: !open[s.key] })}>
                    <span className="chev">▸</span>
                    {s.title}
                    <span className="muted small" style={{ fontWeight: 400 }}>{s.fields.length}</span>
                    {n > 0 && <span className="badge accent">{n} changed</span>}
                  </button>
                  {isOpen && (
                    <div className="section-body">
                      {s.fields.map((f) => (
                        <FieldInput key={f.name} field={f} value={values[f.name]} onChange={(v) => set(f.name, v)} note={unmet(f, values, byName)} />
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <aside className="tool-side">
          <div className="card">
            <div className="card-body stack" style={{ gap: 10 }}>
              <button className="primary big" onClick={start} disabled={starting || missingInput || (tool.service && !service)}>
                {starting ? "Starting…" : `Run ${tool.title.toLowerCase().startsWith("convert") ? "conversion" : tool.title.toLowerCase()}`}
              </button>
              {missingInput && <div className="muted small">{inputFields[0]?.input === "sources" ? "Add documents to convert." : `Choose the ${inputFields[0]?.label.toLowerCase()}.`}</div>}
              {startError && <div className="banner error" style={{ margin: 0 }}>{startError}</div>}
              {Array.isArray(values.to) && values.to.includes("html") && values.to.includes("html_split_page") && (
                <div className="banner warn" style={{ margin: 0 }}>html and html_split_page both write <code>name.html</code>; Docling keeps the last one.</div>
              )}
              <div className="row">
                <button className="small" onClick={() => { setValues(initialValues(tool)); setPreset(""); }} disabled={!changedCount && !preset}>Reset options</button>
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-head"><h3 style={{ margin: 0 }}>Presets</h3></div>
            <div className="card-body stack" style={{ gap: 8 }}>
              <select value={preset} onChange={(e) => applyPreset(e.target.value)} aria-label="Preset">
                <option value="">{presets.length ? "Choose a preset…" : "No presets yet"}</option>
                {presets.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
              <div className="row">
                <button className="small" onClick={() => savePreset(true)}>Save as new…</button>
                {preset && <button className="small" onClick={() => savePreset(false)}>Update</button>}
                {preset && <button className="small danger" onClick={deletePreset}>Delete</button>}
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <h3 style={{ margin: 0 }}>Command</h3>
              <span className="grow" />
              {command?.command && (
                <button className="small ghost" onClick={() => navigator.clipboard.writeText(command.command!).then(() => toast("Command copied"))}>Copy</button>
              )}
            </div>
            <div className="card-body">
              {command?.error ? <div className="field-when" style={{ color: "var(--danger)" }}>{command.error}</div> : (
                <div className="command">{command?.command ?? "…"}</div>
              )}
              <div className="muted small" style={{ marginTop: 8 }}>
                Only options that differ from Docling's defaults are passed. Secrets show as ••••••.
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
