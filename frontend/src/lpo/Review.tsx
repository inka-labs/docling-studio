/** One document: its pages beside what an experiment read from it, corrected here into ground truth.
 *  The form starts from the saved label, or else from the experiment's result, so labelling is
 *  mostly checking. Saving and moving on is one keystroke (Ctrl/⌘ + Enter). */
import { useEffect, useMemo, useState } from "react";
import { href, navigate } from "../router";
import { confirm, toast } from "../ui/Dialogs";
import { bytes } from "../ui/format";
import { describeConfig, KIND_LABEL, lpo, type Box, type Checks, type DocDetail, type DocRow, type Experiment, type Line, type LpoRecord, type Overview, type Result } from "./lpoApi";

type Form = { fields: Record<string, string>; lines: Record<string, string>[] };

function toForm(record: LpoRecord | null | undefined, overview: Overview): Form {
  const fields: Record<string, string> = {};
  for (const f of overview.schema.fields) fields[f.name] = record?.fields?.[f.name] == null ? "" : String(record.fields[f.name]);
  const lines = (record?.lines ?? []).map((l) => Object.fromEntries(overview.schema.lines.map((c) => [c.name, l[c.name as keyof Line] == null ? "" : String(l[c.name as keyof Line])])));
  return { fields, lines };
}

function fromForm(form: Form): LpoRecord {
  const blank = (v: string) => (v.trim() === "" ? null : v.trim());
  return {
    fields: Object.fromEntries(Object.entries(form.fields).map(([k, v]) => [k, blank(v)])),
    lines: form.lines.map((l) => Object.fromEntries(Object.entries(l).map(([k, v]) => [k, blank(v)])) as unknown as Line),
  };
}

export default function Review({ id, exp }: { id: string; exp?: string }) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [doc, setDoc] = useState<DocDetail | null>(null);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [result, setResult] = useState<Result | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [checks, setChecks] = useState<Checks | null>(null);
  const [order, setOrder] = useState<DocRow[]>([]);
  const [focus, setFocus] = useState<string | null>(null);
  const [straight, setStraight] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    Promise.all([lpo.overview(), lpo.doc(id), lpo.experiments(), exp ? lpo.result(exp, id).catch(() => null) : Promise.resolve(null)])
      .then(([o, d, xs, r]) => {
        setOverview(o);
        setDoc(d);
        setExperiments(xs.filter((x) => x.summary.documents > 0));
        setResult(r);
        setForm(toForm(d.label ?? r?.record, o));
      })
      .catch((e) => setError(e.message));
    lpo.docs(exp).then(setOrder).catch(() => {});
  }, [id, exp]);

  // checks as you type
  const record = useMemo(() => (form ? fromForm(form) : null), [form]);
  useEffect(() => {
    if (!record) return;
    const t = setTimeout(() => lpo.check(record).then((r) => setChecks(r.checks)).catch(() => {}), 300);
    return () => clearTimeout(t);
  }, [record]);

  const nextId = useMemo(() => {
    const live = order.filter((r) => !r.excluded);
    const at = live.findIndex((r) => r.id === id);
    const after = [...live.slice(at + 1), ...live.slice(0, Math.max(at, 0))];
    return (after.find((r) => !r.labelled && (!exp || r.result)) ?? after[0])?.id;
  }, [order, id, exp]);

  const save = async (opts: { next?: boolean; notLpo?: boolean } = {}) => {
    if (!record || !doc) return;
    try {
      const saved = await lpo.saveLabel(doc.id, { ...record, not_lpo: !!opts.notLpo, notes: "", from_experiment: exp ?? null });
      setDirty(false);
      toast(opts.notLpo ? "Marked as not an LPO" : saved.checks.ok ? "Label saved" : "Label saved (it doesn't pass every check: double-check the numbers)");
      if (opts.next && nextId) navigate({ page: "lpo-doc", id: nextId, exp });
      else setDoc({ ...doc, label: saved, labelled: true });
    } catch (e) {
      toast((e as Error).message);
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        save({ next: true });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (error) return <div className="page"><div className="banner error">{error}</div><a href={href({ page: "lpo" })}>Back to the LPO lab</a></div>;
  if (!overview || !doc || !form) return <div className="page"><p className="muted">Loading…</p></div>;

  const setField = (name: string, value: string) => {
    setForm({ ...form, fields: { ...form.fields, [name]: value } });
    setDirty(true);
  };
  const setCell = (i: number, name: string, value: string) => {
    const lines = form.lines.map((l, j) => (j === i ? { ...l, [name]: value } : l));
    setForm({ ...form, lines });
    setDirty(true);
  };
  const addLine = () => {
    setForm({ ...form, lines: [...form.lines, Object.fromEntries(overview.schema.lines.map((c) => [c.name, ""]))] });
    setDirty(true);
  };
  const dropLine = (i: number) => {
    setForm({ ...form, lines: form.lines.filter((_, j) => j !== i) });
    setDirty(true);
  };
  const fromResult = () => {
    if (result?.record) {
      setForm(toForm(result.record, overview));
      setDirty(true);
    }
  };
  const exclude = async () => {
    if (!(await confirm("Take this document out of the test set?", { body: "It stays on disk and can be put back; experiments skip it from now on.", confirm: "Take out" }))) return;
    await lpo.excludeDoc(doc.id, !doc.excluded);
    toast(doc.excluded ? "Back in the test set" : "Taken out of the test set");
    if (nextId && !doc.excluded) navigate({ page: "lpo-doc", id: nextId, exp });
    else setDoc({ ...doc, excluded: !doc.excluded });
  };
  const removeLabel = async () => {
    if (!(await confirm("Delete this label?", { confirm: "Delete", danger: true }))) return;
    await lpo.deleteLabel(doc.id);
    setDoc({ ...doc, label: null, labelled: false });
    setForm(toForm(result?.record, overview));
  };

  const read = result?.record;
  const cmp = result?.comparison;
  const boxes: Record<string, Box> = result?.where ?? {};
  const name = doc.key.split("/").pop();
  const pages = Array.from({ length: doc.pages || 1 }, (_, i) => i + 1);

  return (
    <div className="page wide review">
      <div className="page-head">
        <div className="grow" style={{ minWidth: 0 }}>
          <div className="small"><a href={href({ page: "lpo" })}>LPO lab</a>{exp && <> › <a href={href({ page: "lpo-exp", id: exp })}>{experiments.find((e) => e.id === exp)?.name ?? "experiment"}</a></>} ›</div>
          <h1 className="ellipsis" title={doc.key}>{name}</h1>
          <div className="lede">
            {doc.client} · {KIND_LABEL[doc.kind]} · {doc.pages} page{doc.pages === 1 ? "" : "s"} · {bytes(doc.size)}
            {doc.orientation?.some(Boolean) && <> · turned {doc.orientation.join("°, ")}°</>}
            {doc.excluded && <> · <span className="badge">taken out</span></>}
            {doc.label && <> · <span className="badge accent">{doc.label.not_lpo ? "not an LPO" : "labelled"}</span></>}
          </div>
        </div>
        <div className="row">
          <a className="button" href={lpo.fileUrl(doc.id)} target="_blank" rel="noreferrer">Original</a>
          <button onClick={exclude}>{doc.excluded ? "Put back" : "Take out"}</button>
          {nextId && <a className="button" href={href({ page: "lpo-doc", id: nextId, exp })}>Skip</a>}
        </div>
      </div>

      <div className="review-layout">
        <div className="pages card">
          <div className="card-head">
            <h2>Pages</h2>
            <span className="grow" />
            {doc.orientation?.some(Boolean) && (
              <label className="row small" style={{ gap: 6 }}>
                <span className="switch"><input type="checkbox" checked={straight} onChange={(e) => setStraight(e.target.checked)} /><span /></span>
                Straightened
              </label>
            )}
          </div>
          <div className="page-stack">
            {pages.map((n) => (
              <div className="page-img" key={n}>
                <img src={lpo.pageUrl(doc.id, n, straight)} alt={`Page ${n}`} loading={n > 2 ? "lazy" : "eager"} />
                {straight && Object.entries(boxes).filter(([, b]) => b.page === n).map(([field, b]) => (
                  <div key={field} className={`hl ${focus === field ? "on" : ""}`} title={field}
                    style={{ left: `${b.box[0] * 100}%`, top: `${b.box[1] * 100}%`, width: `${(b.box[2] - b.box[0]) * 100}%`, height: `${(b.box[3] - b.box[1]) * 100}%` }} />
                ))}
              </div>
            ))}
          </div>
        </div>

        <div className="editor stack">
          <div className="card">
            <div className="card-head">
              <h2>{doc.label ? "Label" : "Check and correct"}</h2>
              <span className="grow" />
              <select value={exp ?? ""} onChange={(e) => navigate({ page: "lpo-doc", id: doc.id, exp: e.target.value || undefined }, true)} style={{ maxWidth: 260 }} aria-label="Experiment">
                <option value="">No experiment</option>
                {experiments.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
              </select>
            </div>
            <div className="card-body stack">
              {doc.split === "holdout" && (
                <div className="banner info small">Held out: label it, but don't work out rules from it. It's what checks that a gain is real.</div>
              )}
              {result?.error && <div className="banner error">This experiment couldn't read it: {result.error}</div>}
              {exp && !result && <div className="banner warn">Not in this experiment.</div>}
              {result && !result.error && (
                <div className="muted small">
                  {describeConfig(experiments.find((e) => e.id === exp)?.config ?? overview.options.defaults, overview.options.ocr_engines)}
                  {" · lines from "}{result.lines_from}{result.seconds?.convert != null ? ` · ${result.seconds.convert.toFixed(1)} s` : " · cached"}
                  {cmp && <> · <strong>{cmp.perfect ? "matches the label" : `${Object.values(cmp.fields).filter((v) => !v).length} field(s) and ${cmp.lines.true - cmp.lines.matched + cmp.lines.predicted - cmp.lines.matched} line(s) differ`}</strong></>}
                  {doc.label && read && <> · <button className="link small" onClick={fromResult}>Start over from this result</button></>}
                </div>
              )}
              <CheckList checks={checks} labels={overview.checks} />
              <div className="field-grid">
                {overview.schema.fields.map((f) => {
                  const seen = read?.fields?.[f.name];
                  const differs = doc.label && read && cmp && f.name in cmp.fields && !cmp.fields[f.name];
                  return (
                    <label key={f.name} className={`field ${differs ? "differs" : ""}`} onFocus={() => setFocus(f.name)} onBlur={() => setFocus(null)}>
                      <span className="field-label">{f.label}{boxes[f.name] && <span className="dot" title="Shown on the page" />}</span>
                      {f.kind === "choice" ? (
                        <select value={form.fields[f.name]} onChange={(e) => setField(f.name, e.target.value)}>
                          <option value="">–</option>
                          {Object.entries(overview.schema.document_types).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                        </select>
                      ) : (
                        <input type={f.kind === "date" ? "date" : "text"} inputMode={f.kind === "number" ? "decimal" : undefined}
                          value={form.fields[f.name]} onChange={(e) => setField(f.name, e.target.value)} />
                      )}
                      {differs && <span className="field-help">read: {seen == null ? "nothing" : String(seen)}</span>}
                    </label>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <h2>Line items</h2><span className="muted small">{form.lines.length}</span>
              <span className="grow" />
              <button className="small" onClick={addLine}>Add a line</button>
            </div>
            <div className="lines-edit">
              <table>
                <thead><tr>{overview.schema.lines.map((c) => <th key={c.name} className={c.kind === "number" ? "num" : ""}>{c.label}</th>)}<th /></tr></thead>
                <tbody>
                  {form.lines.map((l, i) => {
                    const q = parseFloat((l.quantity || "").replace(/,/g, ""));
                    const p = parseFloat((l.unit_price || "").replace(/,/g, ""));
                    const a = parseFloat((l.amount || "").replace(/,/g, ""));
                    const bad = [q, p, a].every((x) => !isNaN(x)) && Math.abs(q * p - a) > Math.max(0.06, a * 0.005) && Math.abs(q * p * 1.16 - a) > Math.max(0.06, a * 0.005);
                    return (
                      <tr key={i} className={bad ? "bad" : ""}>
                        {overview.schema.lines.map((c) => (
                          <td key={c.name} className={`${c.name} ${c.kind === "number" ? "num" : ""}`}>
                            <input value={l[c.name]} onChange={(e) => setCell(i, c.name, e.target.value)} aria-label={`${c.label}, line ${i + 1}`}
                              inputMode={c.kind === "number" ? "decimal" : undefined} />
                          </td>
                        ))}
                        <td><button className="ghost small" onClick={() => dropLine(i)} aria-label={`Remove line ${i + 1}`}>×</button></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {form.lines.length === 0 && <p className="muted small" style={{ padding: "10px 16px" }}>No lines. Add them from the page, or mark the document as not an LPO.</p>}
            </div>
          </div>

          <div className="save-bar">
            <button className="primary" onClick={() => save({ next: true })} disabled={!nextId && !dirty && !!doc.label}>
              Save{nextId ? " and next" : ""} <kbd>⌘↵</kbd>
            </button>
            <button onClick={() => save()}>Save</button>
            <button onClick={() => save({ next: true, notLpo: true })} title="An email, a delivery note on its own, a blank page…">Not an LPO</button>
            <span className="grow" />
            {doc.label && <button className="danger ghost" onClick={removeLabel}>Delete label</button>}
          </div>
        </div>
      </div>
    </div>
  );
}

function CheckList({ checks, labels }: { checks: Checks | null; labels: Record<string, string> }) {
  if (!checks) return null;
  return (
    <div className="chips">
      {Object.entries(labels).filter(([k]) => k !== "ok" && k in checks).map(([k, label]) => (
        <span key={k} className={`badge ${checks[k] ? "ok" : "warn"}`}>{checks[k] ? "✓" : "✗"} {label}</span>
      ))}
    </div>
  );
}
