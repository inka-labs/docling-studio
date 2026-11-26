/** One experiment: how it scored (checks on everything, accuracy on the labelled), where it fails
 *  (by field, by kind of document, by client), the documents behind each number, and its log. */
import { useEffect, useRef, useState } from "react";
import { href, navigate } from "../router";
import { prompt, toast } from "../ui/Dialogs";
import { ago, between, duration, plural } from "../ui/format";
import { confirmDelete, EXP_STATUS, subsetLabel } from "./Lab";
import { describeConfig, KIND_LABEL, lpo, pct, type DocRow, type Experiment as Exp, type GroupScore, type Overview } from "./lpoApi";

export default function Experiment({ id }: { id: string }) {
  const [exp, setExp] = useState<Exp | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [all, setAll] = useState<Exp[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    lpo.overview().then(setOverview).catch(() => {});
    lpo.experiments().then(setAll).catch(() => {});
  }, []);
  useEffect(() => {
    let stop = false;
    const load = () => lpo.experiment(id).then((e) => !stop && setExp(e)).catch((e) => setError(e.message));
    load();
    const t = setInterval(load, 3000);
    return () => {
      stop = true;
      clearInterval(t);
    };
  }, [id]);

  if (error) return <div className="page"><div className="banner error">{error}</div><a href={href({ page: "lpo" })}>Back to the LPO lab</a></div>;
  if (!exp || !overview) return <div className="page"><p className="muted">Loading…</p></div>;

  const s = exp.summary;
  const st = EXP_STATUS[exp.status];
  const active = exp.status === "queued" || exp.status === "running";
  const act = async (fn: () => Promise<unknown>, done?: string) => {
    setBusy(true);
    try {
      const out = await fn();
      if (done) toast(done);
      if (out && typeof out === "object" && "id" in out) setExp(out as Exp);
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const rename = async () => {
    const name = await prompt("Rename the experiment", { value: exp.name });
    if (name) act(() => lpo.renameExperiment(exp.id, { name }));
  };
  const retryFailing = () =>
    act(async () => {
      const next = await lpo.createExperiment({ name: `${exp.name} – failing`, config: exp.config, subset: `failing:${exp.id}` });
      navigate({ page: "lpo-exp", id: next.id });
    });
  const remove = async () => {
    if (await confirmDelete(exp.name)) act(async () => {
      await lpo.deleteExperiment(exp.id);
      navigate({ page: "lpo" });
    });
  };

  return (
    <div className="page wide">
      <div className="page-head">
        <div className="grow">
          <div className="small"><a href={href({ page: "lpo" })}>LPO lab</a> ›</div>
          <h1>{exp.name} <button className="link small" onClick={rename}>Rename</button></h1>
          <div className="lede">
            {describeConfig(exp.config, overview.options.ocr_engines)} · {subsetLabel(exp.subset, all)}{exp.limit ? `, first ${exp.limit}` : ""} ·{" "}
            <span className={`status ${st.cls}`}>{st.label}</span>
            {exp.started && <span className="muted"> · {exp.ended ? `took ${duration(between(exp.started, exp.ended))}` : `started ${ago(exp.started)}`}</span>}
          </div>
          {exp.notes && <div className="muted small" style={{ marginTop: 4 }}>{exp.notes}</div>}
        </div>
        <div className="row">
          {active && <button disabled={busy} onClick={() => act(() => lpo.stopExperiment(exp.id))}>Stop</button>}
          {!active && exp.progress.done < exp.docs && <button disabled={busy} onClick={() => act(() => lpo.resumeExperiment(exp.id), "Picking up where it stopped")}>Resume</button>}
          {!active && exp.config.extractor === "rules" && s.documents > 0 && (
            <button disabled={busy} title="Map fields again from the cached conversions, after a change to the rules" className={exp.stale_mapper ? "primary" : ""}
              onClick={() => act(() => lpo.remapExperiment(exp.id).then((r) => (toast(`Re-mapped ${r.remapped} documents`), r)))}>Re-map</button>
          )}
          {!active && s.documents - s.errors > 0 && (s.ok_rate ?? 1) < 1 && <button disabled={busy} onClick={retryFailing}>New run on what failed</button>}
          {s.documents > 0 && <a className="button" href={lpo.exportUrl(exp.id)}>Download results</a>}
          {!active && <button className="danger" disabled={busy} onClick={remove}>Delete</button>}
        </div>
      </div>

      {exp.stale_mapper && !active && (
        <div className="banner warn">The field rules changed since these results were made. <strong>Re-map</strong> to score them with the current rules (from the cache, in seconds).</div>
      )}
      {active && (
        <div className="card"><div className="card-body">
          <div className="row small"><strong>{exp.status === "queued" ? "Waiting for another experiment to finish" : `${exp.progress.done} of ${exp.progress.total} documents`}</strong>
            {exp.progress.failed ? <span className="badge danger">{exp.progress.failed} failed</span> : null}</div>
          <div className="progress" style={{ marginTop: 8 }}><div style={{ width: `${exp.progress.total ? (100 * exp.progress.done) / exp.progress.total : 0}%` }} /></div>
        </div></div>
      )}

      <div className="card"><div className="card-body">
        <div className="stat-row">
          <Stat value={s.documents.toLocaleString()} label={`documents${s.errors ? ` (${s.errors} failed)` : ""}`} />
          <Stat value={pct(s.ok_rate)} label="passed every check" strong />
          <Stat value={pct(s.fill.lpo_number)} label="LPO number found" />
          <Stat value={pct(s.lines_found)} label="line items found" />
          <Stat value={s.accuracy ? pct(s.accuracy.fields) : "–"} label={`fields right (${s.labelled} labelled)`} strong={!!s.accuracy} />
          <Stat value={pct(s.perfect_rate)} label="labelled read perfectly" />
          <Stat value={s.seconds.convert_mean != null ? `${s.seconds.convert_mean.toFixed(1)} s` : "–"} label={`per document (${s.seconds.converted} converted)`} />
        </div>
        {s.labelled === 0 && s.documents > 0 && (
          <p className="muted small" style={{ marginTop: 10 }}>
            Checks say whether a result is consistent, not whether it's right. Label a few documents (open one below) to measure accuracy;
            every experiment is scored against the same labels.
          </p>
        )}
      </div></div>

      <div className="two-col">
        <div className="card">
          <div className="card-head"><h2>Checks</h2></div>
          <div className="card-body bar-chart">
            {Object.entries(overview.checks).filter(([k]) => k !== "ok").map(([k, label]) => (
              <Bar key={k} label={label} value={s.checks[k]} note={s.check_counts?.[k] != null ? `of ${s.check_counts[k]}` : ""} />
            ))}
            <div className="muted small">A check that can't be made (no subtotal printed, say) is left out, not failed.</div>
          </div>
        </div>
        <div className="card">
          <div className="card-head"><h2>Fields</h2><span className="muted small">found on every document · right on the labelled ones</span></div>
          <div style={{ overflowX: "auto" }}>
            <table className="list">
              <thead><tr><th>Field</th><th className="num">Found</th><th className="num">Right</th></tr></thead>
              <tbody>
                {overview.schema.fields.map((f) => {
                  const a = s.accuracy?.by_field[f.name];
                  return (
                    <tr key={f.name}>
                      <td>{f.label}</td>
                      <td className="num">{pct(s.fill[f.name])}</td>
                      <td className="num">{a && a.of ? <>{pct(a.rate)} <span className="muted small">{a.right}/{a.of}</span></> : <span className="muted">–</span>}</td>
                    </tr>
                  );
                })}
                {s.accuracy && (
                  <>
                    <tr><td>Line items found (recall)</td><td /><td className="num">{pct(s.accuracy.line_recall)}</td></tr>
                    <tr><td>Line items that are real (precision)</td><td /><td className="num">{pct(s.accuracy.line_precision)}</td></tr>
                    <tr><td>Quantities, prices and amounts</td><td /><td className="num">{pct(s.accuracy.line_numbers)}</td></tr>
                  </>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="two-col">
        <Groups title="By kind of document" groups={{ ...s.by_kind, ...Object.fromEntries(Object.entries(s.by_split ?? {}).map(([k, v]) => [`split:${k}`, v])) }}
          names={{ ...KIND_LABEL, "split:dev": "Working set", "split:holdout": "Held-out set" }} />
        <Groups title="By client" groups={s.by_client ?? {}} />
      </div>

      <ExpDocs exp={exp} overview={overview} />
      <Log id={exp.id} live={active} />
    </div>
  );
}

function Stat({ value, label, strong }: { value: string; label: string; strong?: boolean }) {
  return (
    <div className={`stat ${strong ? "strong" : ""}`}>
      <div className="value">{value}</div>
      <div className="label">{label}</div>
    </div>
  );
}

function Bar({ label, value, note }: { label: string; value: number | null | undefined; note?: string }) {
  return (
    <div className="bar-row">
      <span className="ellipsis" title={label}>{label}</span>
      <div className="bar-track"><div className={`bar ${value != null && value < 0.8 ? "low" : ""}`} style={{ width: `${(value ?? 0) * 100}%` }} /></div>
      <span className="num small">{pct(value)} <span className="muted">{note}</span></span>
    </div>
  );
}

function Groups({ title, groups, names = {} }: { title: string; groups: Record<string, GroupScore>; names?: Record<string, string> }) {
  const rows = Object.entries(groups);
  return (
    <div className="card">
      <div className="card-head"><h2>{title}</h2></div>
      {rows.length === 0 ? <p className="muted small" style={{ padding: 16 }}>No results yet.</p> : (
        <div style={{ overflowX: "auto", maxHeight: 360 }}>
          <table className="list">
            <thead><tr><th /><th className="num">Docs</th><th className="num">Passed checks</th><th className="num">LPO no.</th><th className="num">Lines</th></tr></thead>
            <tbody>
              {rows.map(([k, g]) => (
                <tr key={k}>
                  <td>{names[k] ?? k}</td><td className="num">{g.documents}</td>
                  <td className="num"><strong>{pct(g.ok_rate)}</strong></td><td className="num">{pct(g.lpo_number)}</td><td className="num">{pct(g.lines_found)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ExpDocs({ exp, overview }: { exp: Exp; overview: Overview }) {
  const [rows, setRows] = useState<DocRow[] | null>(null);
  const [tab, setTab] = useState<"failing" | "passing" | "errors">("failing");
  const [check, setCheck] = useState("");
  useEffect(() => {
    lpo.docs(exp.id).then((r) => setRows(r.filter((x) => x.result))).catch((e) => toast(e.message));
  }, [exp.id, exp.progress.done, exp.summary.labelled]);
  if (!rows) return null;
  const groups = {
    failing: rows.filter((r) => !r.result!.error && !r.result!.ok),
    passing: rows.filter((r) => r.result!.ok),
    errors: rows.filter((r) => r.result!.error),
  };
  const shown = groups[tab].filter((r) => !check || r.result!.checks?.[check] === false).slice(0, 200);
  return (
    <div className="card">
      <div className="tabs" style={{ padding: "0 8px" }}>
        {(["failing", "passing", "errors"] as const).map((t) => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
            {{ failing: "Failing checks", passing: "Passing", errors: "Couldn't convert" }[t]}<span className="count">{groups[t].length}</span>
          </button>
        ))}
        <span className="grow" />
        {tab === "failing" && (
          <select value={check} onChange={(e) => setCheck(e.target.value)} style={{ width: "auto", margin: 4 }} aria-label="Check">
            <option value="">Any check</option>
            {Object.entries(overview.checks).filter(([k]) => k !== "ok").map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        )}
      </div>
      {shown.length === 0 ? <p className="muted small" style={{ padding: 16 }}>None.</p> : (
        <div style={{ overflowX: "auto" }}>
          <table className="list">
            <thead><tr><th>Document</th><th>Client</th><th>Kind</th><th>LPO number</th><th className="num">Lines</th><th>{tab === "errors" ? "Error" : "Failed checks"}</th><th>Label</th></tr></thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.id} className="clickable" onClick={() => navigate({ page: "lpo-doc", id: r.id, exp: exp.id })}>
                  <td style={{ maxWidth: 320 }}><span className="ellipsis mono small" style={{ display: "block" }} title={r.key}>{r.key.split("/").pop()}</span></td>
                  <td className="small">{r.client}</td>
                  <td className="small">{KIND_LABEL[r.kind]}</td>
                  <td className="mono small">{r.result!.lpo_number ?? <span className="muted">–</span>}</td>
                  <td className="num small">{r.result!.error ? "" : r.result!.lines}</td>
                  <td className="small">{r.result!.error ? <span className="ellipsis" style={{ display: "block", maxWidth: 360 }} title={r.result!.error}>{r.result!.error}</span>
                    : Object.entries(r.result!.checks ?? {}).filter(([k, v]) => !v && k !== "ok").map(([k]) => overview.checks[k]).join(" · ")}</td>
                  <td>{r.labelled ? <span className="badge accent">labelled</span> : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {groups[tab].length > 200 && <p className="muted small" style={{ padding: "8px 16px" }}>The first 200 of {plural(groups[tab].length, "document")}.</p>}
        </div>
      )}
    </div>
  );
}

function Log({ id, live }: { id: string; live: boolean }) {
  const [open, setOpen] = useState(live);
  const [text, setText] = useState("");
  const offset = useRef(0);
  const box = useRef<HTMLPreElement>(null);
  useEffect(() => {
    if (!open) return;
    let stop = false;
    const load = () =>
      lpo.experimentLog(id, offset.current).then((r) => {
        if (stop) return;
        if (r.text) {
          setText((t) => (t + r.text).slice(-200_000));
          offset.current = r.offset;
          setTimeout(() => box.current && (box.current.scrollTop = box.current.scrollHeight), 0);
        }
      }).catch(() => {});
    load();
    const t = live ? setInterval(load, 2000) : undefined;
    return () => {
      stop = true;
      clearInterval(t);
    };
  }, [id, open, live]);
  return (
    <div className="card">
      <button className="section-head" aria-expanded={open} onClick={() => setOpen(!open)}><span className="chev">›</span> Log</button>
      {open && <pre className="log" ref={box}>{text || "Nothing yet."}</pre>}
    </div>
  );
}
