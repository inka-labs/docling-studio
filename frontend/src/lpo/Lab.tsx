/** The LPO lab: the test set, the experiments run on it (best first), a form for the next one, and
 *  every document with its result in a chosen experiment. */
import { useEffect, useMemo, useState } from "react";
import { href, navigate } from "../router";
import { confirm, toast } from "../ui/Dialogs";
import { ago, duration, plural } from "../ui/format";
import { describeConfig, KIND_LABEL, lpo, pct, SPLITS, SUBSETS, type Config, type DocRow, type Experiment, type Layouts, type Overview, type Split } from "./lpoApi";

export const EXP_STATUS: Record<string, { label: string; cls: string }> = {
  queued: { label: "Waiting", cls: "queued" },
  running: { label: "Running", cls: "running" },
  finished: { label: "Done", cls: "succeeded" },
  stopped: { label: "Stopped", cls: "cancelled" },
  failed: { label: "Failed", cls: "failed" },
  interrupted: { label: "Interrupted", cls: "interrupted" },
};

export default function Lab() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [experiments, setExperiments] = useState<Experiment[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    Promise.all([lpo.overview().then(setOverview), lpo.experiments().then(setExperiments)]).catch((e) => setError(e.message));

  useEffect(() => {
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, []);

  if (error) return <div className="page"><div className="banner error">{error}</div></div>;
  if (!overview || !experiments) return <div className="page"><p className="muted">Loading…</p></div>;

  return (
    <div className="page wide">
      <div className="page-head">
        <div className="grow">
          <h1>LPO lab</h1>
          <div className="lede">
            Find the Docling settings that read purchase orders best. Run strategies over a fixed test set of real LPOs, compare
            them on checks every LPO has to pass (the numbers add up), and on the documents you've labelled.
          </div>
        </div>
      </div>
      <TestSet overview={overview} reload={load} />
      <LayoutsCard overview={overview} reload={load} />
      <Leaderboard experiments={experiments} overview={overview} />
      <NewExperiment overview={overview} experiments={experiments} onStarted={load} />
      <Documents overview={overview} experiments={experiments} />
    </div>
  );
}

// The test set -----------------------------------------------------------------------------------

function TestSet({ overview, reload }: { overview: Overview; reload: () => void }) {
  const { testset: ts, job, source, clients } = overview;
  const [size, setSize] = useState(ts.documents || 1000);
  const [showClients, setShowClients] = useState(false);
  const [bucket, setBucket] = useState(source.bucket);
  const [editBucket, setEditBucket] = useState(false);
  const running = job.status === "running";
  const listed = clients.reduce((n, c) => n + c.documents, 0);

  const run = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      reload();
    } catch (e) {
      toast((e as Error).message);
    }
  };
  const toggle = (name: string, on: boolean) => {
    const off = clients.filter((c) => (c.name === name ? !on : !c.on)).map((c) => c.name);
    run(() => lpo.saveSource({ clients_off: off }));
  };

  return (
    <div className="card">
      <div className="card-head">
        <h2>Test set</h2>
        <span className="muted small">
          from{" "}
          {editBucket || !source.bucket ? (
            <form
              style={{ display: "inline-flex", gap: 6 }}
              onSubmit={(e) => {
                e.preventDefault();
                run(() => lpo.saveSource({ bucket })).then(() => setEditBucket(false));
              }}
            >
              <input type="text" placeholder="bucket name" value={bucket} onChange={(e) => setBucket(e.target.value)} />
              <button className="small" type="submit" disabled={!bucket.trim()}>Save</button>
            </form>
          ) : (
            <code title="Change the bucket" style={{ cursor: "pointer" }} onClick={() => setEditBucket(true)}>{source.bucket}</code>
          )}
          {source.listed ? ` · listed ${ago(source.listed)}` : ""} · {plural(listed, "document")} in {plural(clients.length, "folder")}
        </span>
        <span className="grow" />
        <button className="small" disabled={running} onClick={() => run(lpo.refreshListing)}>Refresh listing</button>
      </div>
      <div className="card-body stack">
        {job.status !== "idle" && (
          <div className={`banner ${job.status === "failed" ? "error" : job.status === "running" ? "info" : "warn"}`}>
            <div className="row">
              <strong>{{ listing: "Listing the bucket", survey: "Surveying layouts", build: "Building the test set" }[job.job ?? "build"] ?? "Working"}</strong>
              <span className="grow">{job.error ?? job.message}</span>
              {running && <button className="small" onClick={() => run(lpo.stopJob)}>Stop</button>}
            </div>
            {running && job.total > 0 && (
              <div className="progress" style={{ marginTop: 8 }}><div style={{ width: `${(100 * job.done) / job.total}%` }} /></div>
            )}
          </div>
        )}
        {job.status === "idle" && job.message && <div className="muted small">{job.message}</div>}
        <div className="stat-row">
          <Stat value={ts.documents.toLocaleString()} label="documents" />
          <Stat value={ts.kinds.digital.toLocaleString()} label="digital PDFs" />
          <Stat value={ts.kinds.scan.toLocaleString()} label="scanned PDFs" />
          <Stat value={ts.kinds.image.toLocaleString()} label="photos" />
          <Stat value={ts.pages.toLocaleString()} label="pages" />
          <Stat value={`${ts.labelled.toLocaleString()}`} label={`labelled${ts.documents ? ` (${pct(ts.labelled / ts.documents)})` : ""}`} />
          <Stat value={ts.holdout.toLocaleString()} label={`held out (${ts.labelled_holdout} labelled)`} />
        </div>
        <div className="muted small">
          One document in five is <strong>held out</strong>: experiments run on the working set while rules are tuned, and on the
          held-out set now and then, to check a gain is real and not just fitted to the documents we looked at. Label held-out documents
          too (that's what measures it), but don't work out rules from them.
        </div>
        <div className="row">
          <label className="row small" style={{ gap: 6 }}>
            Grow the test set to
            <input type="number" min={1} max={20000} value={size} onChange={(e) => setSize(Number(e.target.value))} style={{ width: 100 }} />
            documents
          </label>
          <button className="primary small" disabled={running || !listed || size <= ts.documents} onClick={() => run(() => lpo.buildTestset(size))}>
            {ts.documents ? "Add documents" : "Build test set"}
          </button>
          <span className="muted small">
            Documents already in it stay, so labels and results keep their meaning. Bigger clients give more, but not in proportion.
          </span>
          <span className="grow" />
          <button className="link small" onClick={() => setShowClients(!showClients)}>
            {showClients ? "Hide" : "Choose"} folders ({clients.filter((c) => c.on).length} of {clients.length} on)
          </button>
        </div>
        {showClients && (
          <div className="client-grid">
            {clients.map((c) => {
              const inSet = ts.clients.find((x) => x.name === c.name)?.documents ?? 0;
              return (
                <label key={c.name} className={`client ${c.on ? "" : "off"}`}>
                  <input type="checkbox" checked={c.on} onChange={(e) => toggle(c.name, e.target.checked)} />
                  <span className="ellipsis grow" title={c.name}>{c.name}</span>
                  <span className="muted small num">{inSet ? `${inSet} / ` : ""}{c.documents.toLocaleString()}</span>
                </label>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="stat">
      <div className="value">{value}</div>
      <div className="label">{label}</div>
    </div>
  );
}

// Layouts ---------------------------------------------------------------------------------------

function LayoutsCard({ overview, reload }: { overview: Overview; reload: () => void }) {
  const [data, setData] = useState<Layouts | null>(null);
  const [perClient, setPerClient] = useState(150);
  const [onlyGaps, setOnlyGaps] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const job = overview.job;
  const surveying = job.status === "running" && job.job === "survey";

  useEffect(() => {
    lpo.layouts().then(setData).catch(() => {});
  }, [overview.testset.documents, surveying ? Math.floor(job.done / 200) : -1]);

  const start = async () => {
    try {
      await lpo.survey(perClient);
      reload();
    } catch (e) {
      toast((e as Error).message);
    }
  };
  const add = async (id: string, count: number) => {
    setBusy(id);
    try {
      const r = await lpo.addLayout(id, count);
      toast(`Added ${plural(r.added.length, "document")} to the test set`);
      reload();
      setData(await lpo.layouts());
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const layouts = (data?.layouts ?? []).filter((l) => !onlyGaps || l.gap);
  const gaps = (data?.layouts ?? []).filter((l) => l.gap).length;
  return (
    <div className="card">
      <div className="card-head">
        <h2>Layouts</h2>
        <span className="muted small">
          {data ? `${data.surveyed.toLocaleString()} bucket documents surveyed · ${data.layouts.length} layouts${gaps ? ` · ${gaps} thin in the test set` : ""}` : "…"}
        </span>
        <span className="grow" />
        <label className="row small" style={{ gap: 6 }}>
          Survey up to
          <input type="number" min={1} max={5000} value={perClient} onChange={(e) => setPerClient(Number(e.target.value))} style={{ width: 80 }} />
          per folder
        </label>
        <button className="small" disabled={job.status === "running"} onClick={start}>{data?.surveyed ? "Survey more" : "Survey the bucket"}</button>
      </div>
      <div className="card-body stack">
        <div className="muted small">
          Documents grouped by template (the buyer's name and labels in the header; how the page looks, for scans without readable
          text). A layout that's common in the bucket but rare in the test set is where the rules haven't been tested: add some.
          The survey downloads a sample from each folder, keeps a thumbnail and the fingerprint, and deletes the file.
        </div>
        {data && data.layouts.length > 0 && (
          <label className="row small" style={{ gap: 6 }}>
            <input type="checkbox" checked={onlyGaps} onChange={(e) => setOnlyGaps(e.target.checked)} /> Only layouts thin in the test set
          </label>
        )}
        <div className="layout-grid">
          {layouts.slice(0, 40).map((l) => (
            <div key={l.id} className={`layout ${l.gap ? "gap" : ""}`}>
              <div className="thumbs">
                {l.examples.slice(0, 3).map((x) => (
                  <img key={x.id} src={lpo.thumbUrl(x.id)} alt="" loading="lazy" title={x.key}
                    onClick={() => x.in_set && navigate({ page: "lpo-doc", id: x.id })} className={x.in_set ? "in-set" : ""} />
                ))}
              </div>
              <div className="row small">
                <strong>{l.surveyed.toLocaleString()}</strong><span className="muted">in the sample</span>
                <strong>{l.in_set}</strong><span className="muted">in the test set</span>
                {l.gap && <span className="badge warn">thin</span>}
              </div>
              <div className="muted small ellipsis" title={Object.entries(l.clients).map(([c, n]) => `${c}: ${n}`).join("\n")}>
                {Object.keys(l.clients).slice(0, 4).join(", ")}{Object.keys(l.clients).length > 4 ? ` +${Object.keys(l.clients).length - 4}` : ""}
                {" · "}{Object.entries(l.kinds).map(([k, n]) => `${n} ${KIND_LABEL[k]?.toLowerCase() ?? k}`).join(", ")}
              </div>
              {l.words.length > 0 && <div className="words small ellipsis" title={l.words.join(" ")}>{l.words.join(" · ")}</div>}
              {l.addable.length > 0 && (
                <div className="row">
                  {[5, 20].filter((_, i) => i === 0 || l.addable.length > 5).map((n) => (
                    <button key={n} className="small" disabled={busy !== null || job.status === "running"} onClick={() => add(l.id, n)}>
                      {busy === l.id ? "Adding…" : `Add ${Math.min(n, l.addable.length)}`}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
        {layouts.length > 40 && <div className="muted small">And {layouts.length - 40} smaller layouts.</div>}
      </div>
    </div>
  );
}

// Leaderboard ------------------------------------------------------------------------------------

function Leaderboard({ experiments, overview }: { experiments: Experiment[]; overview: Overview }) {
  const [order, setOrder] = useState<"best" | "newest">("best");
  const engines = overview.options.ocr_engines;
  const shown = useMemo(() => {
    const xs = [...experiments];
    if (order === "best") xs.sort((a, b) => (b.summary.accuracy?.fields ?? -1) - (a.summary.accuracy?.fields ?? -1) || (b.summary.ok_rate ?? -1) - (a.summary.ok_rate ?? -1));
    return xs;
  }, [experiments, order]);
  const bestOk = Math.max(...experiments.filter((e) => e.summary.documents >= 10).map((e) => e.summary.ok_rate ?? 0), 0);

  return (
    <div className="card">
      <div className="card-head">
        <h2>Experiments</h2>
        <span className="muted small">Passed checks: LPO number and lines found, every line and the totals add up. Accuracy: against your labels.</span>
        <span className="grow" />
        <select value={order} onChange={(e) => setOrder(e.target.value as "best" | "newest")} style={{ width: "auto" }} aria-label="Order">
          <option value="best">Best first</option>
          <option value="newest">Newest first</option>
        </select>
      </div>
      {experiments.length === 0 ? (
        <div className="empty"><p>No experiments yet. Build the test set, then start one below.</p></div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table className="list">
            <thead>
              <tr>
                <th>Experiment</th><th>Status</th><th className="num">Docs</th><th className="num">Passed checks</th>
                <th className="num">LPO no.</th><th className="num">Lines</th><th className="num">Digital</th><th className="num">Scans</th>
                <th className="num" title="Passed checks on held-out documents">Held out</th>
                <th className="num">Accuracy</th><th className="num">Perfect</th><th className="num">s / doc</th><th>Started</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((e) => {
                const s = e.summary;
                const st = EXP_STATUS[e.status];
                const scans = mergeKinds(s.by_kind, ["scan", "image"]);
                return (
                  <tr key={e.id} className="clickable" onClick={() => navigate({ page: "lpo-exp", id: e.id })}>
                    <td style={{ maxWidth: 360 }}>
                      <a href={href({ page: "lpo-exp", id: e.id })} className="ellipsis" style={{ display: "block" }} onClick={(ev) => ev.stopPropagation()}>{e.name}</a>
                      <div className="muted small ellipsis">{describeConfig(e.config, engines)} · {subsetLabel(e.subset, experiments)}{e.limit ? ` · first ${e.limit}` : ""}
                        {e.split && e.split !== "dev" ? ` · ${e.split === "holdout" ? "held out" : "both sets"}` : ""}</div>
                    </td>
                    <td className="nowrap"><span className={`status ${st.cls}`}>{st.label}</span>
                      {e.status === "running" && <span className="muted small"> {e.progress.done}/{e.progress.total}</span>}</td>
                    <td className="num">{s.documents}{s.errors ? <span className="badge danger" title="failed to convert"> {s.errors}</span> : null}</td>
                    <td className="num"><strong>{pct(s.ok_rate)}</strong>{s.ok_rate != null && s.ok_rate === bestOk && bestOk > 0 ? <span className="badge ok" style={{ marginLeft: 6 }}>best</span> : null}</td>
                    <td className="num">{pct(s.fill?.lpo_number)}</td>
                    <td className="num">{pct(s.lines_found)}</td>
                    <td className="num muted">{pct(s.by_kind?.digital?.ok_rate)}</td>
                    <td className="num muted">{pct(scans)}</td>
                    <td className="num muted">{s.by_split?.holdout ? pct(s.by_split.holdout.ok_rate) : "–"}</td>
                    <td className="num">{s.accuracy ? <span title={`${s.labelled} labelled`}>{pct(s.accuracy.fields)} <span className="muted small">({s.labelled})</span></span> : <span className="muted">–</span>}</td>
                    <td className="num">{pct(s.perfect_rate)}</td>
                    <td className="num muted">{s.seconds?.convert_mean != null ? s.seconds.convert_mean.toFixed(1) : "–"}</td>
                    <td className="muted nowrap">{ago(e.created)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function mergeKinds(byKind: Experiment["summary"]["by_kind"] | undefined, kinds: string[]): number | null {
  const parts = kinds.map((k) => byKind?.[k]).filter(Boolean) as { documents: number; ok_rate: number | null }[];
  const n = parts.reduce((a, p) => a + p.documents, 0);
  if (!n) return null;
  return parts.reduce((a, p) => a + (p.ok_rate ?? 0) * p.documents, 0) / n;
}

export function subsetLabel(subset: string, experiments: Experiment[] = []): string {
  if (SUBSETS[subset]) return SUBSETS[subset];
  if (subset.startsWith("client:")) return `Client ${subset.slice(7)}`;
  if (subset.startsWith("failing:")) {
    const e = experiments.find((x) => x.id === subset.slice(8));
    return `Failing in ${e ? `“${e.name}”` : "another experiment"}`;
  }
  return subset;
}

// A new experiment ------------------------------------------------------------------------------

function NewExperiment({ overview, experiments, onStarted }: { overview: Overview; experiments: Experiment[]; onStarted: () => void }) {
  const { defaults, choices, ocr_engines } = overview.options;
  const [config, setConfig] = useState<Config>(defaults);
  const [name, setName] = useState("");
  const [subset, setSubset] = useState("all");
  const [split, setSplit] = useState<Split>("dev");
  const [limit, setLimit] = useState<number | "">(100);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof Config>(key: K, value: Config[K]) => setConfig({ ...config, [key]: value });

  const finishedRules = experiments.filter((e) => e.summary.seconds?.convert_mean);
  const perDoc = finishedRules.length ? finishedRules.reduce((a, e) => a + (e.summary.seconds.convert_mean ?? 0), 0) / finishedRules.length : 12;
  const whole = subsetCount(subset, overview, experiments);
  const count = whole == null ? null : Math.round(whole * (split === "dev" ? 0.8 : split === "holdout" ? 0.2 : 1));
  const n = limit ? Math.min(Number(limit), count ?? Number(limit)) : count;

  const start = async () => {
    setBusy(true);
    try {
      const exp = await lpo.createExperiment({ name, config, subset, split, limit: limit ? Number(limit) : null, notes });
      toast("Experiment queued");
      onStarted();
      navigate({ page: "lpo-exp", id: exp.id });
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const rules = config.extractor === "rules";
  return (
    <div className="card">
      <div className="card-head"><h2>New experiment</h2>
        <span className="muted small">Conversions are kept per setting, so a strategy that only changes the mapping reuses them.</span>
      </div>
      <div className="section-body" style={{ paddingTop: 14 }}>
        <Choice label="Strategy" value={config.extractor} onChange={(v) => set("extractor", v as Config["extractor"])}
          options={{ rules: "Docling + field rules", vlm: "Vision model (DocumentExtractor)" }}
          help={rules ? "Docling converts the page; rules find the fields and line items. Fast, explainable." : "A vision-language model fills the LPO fields from the page picture. Downloads the model (several GB) on first use; slow without a GPU."} />
        {rules ? (
          <>
            <Choice label="OCR" value={config.ocr} onChange={(v) => set("ocr", v as Config["ocr"])}
              options={{ auto: "Where there's no text layer", off: "Off (digital PDFs only)", full: "Every page" }}
              help="Digital PDFs carry their text; OCR is for scans and photos. “Every page” re-reads digital pages too." />
            <Choice label="OCR engine" value={config.ocr_engine} onChange={(v) => set("ocr_engine", v)} disabled={config.ocr === "off"}
              options={Object.fromEntries((choices.ocr_engine as string[]).map((k) => [k, ocr_engines[k] ?? k]))}
              help="Engines read dot-matrix and phone photos differently: this is the setting most worth comparing on scans." />
            <Choice label="Table structure" value={config.table_mode} onChange={(v) => set("table_mode", v as Config["table_mode"])}
              options={{ accurate: "Accurate", fast: "Fast" }} help="TableFormer's mode, for the line-item table." />
          </>
        ) : (
          <Choice label="Model" value={config.vlm_model} onChange={(v) => set("vlm_model", v)}
            options={{ nuextract: "NuExtract 2.0 (2B)", granite_vision: "Granite Vision 4.1" }} help="Docling's extraction models." />
        )}
        <div className="field">
          <div className="field-label">Straighten scans</div>
          <label className="bool-row">
            <span className="switch"><input type="checkbox" checked={config.straighten} onChange={(e) => set("straighten", e.target.checked)} /><span /></span>
            <span className="small muted">Turn sideways and upside-down scans upright before reading them (a few seconds a page).</span>
          </label>
        </div>
        <div className="field">
          <div className="field-label">Documents</div>
          <select value={subset} onChange={(e) => setSubset(e.target.value)}>
            {Object.entries(SUBSETS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            <optgroup label="One client">
              {overview.testset.clients.map((c) => <option key={c.name} value={`client:${c.name}`}>{c.name} ({c.documents})</option>)}
            </optgroup>
            {experiments.some((e) => e.summary.documents) && (
              <optgroup label="What failed before">
                {experiments.filter((e) => e.summary.documents).map((e) => <option key={e.id} value={`failing:${e.id}`}>Failing in “{e.name}”</option>)}
              </optgroup>
            )}
          </select>
          <div className="field-help">The same documents every time, so experiments compare fairly.</div>
        </div>
        <Choice label="From" value={split} onChange={(v) => setSplit(v as Split)} options={SPLITS}
          help="Tune on the working set. Run the held-out set to confirm a gain before trusting it." />
        <div className="field">
          <div className="field-label">How many</div>
          <input type="number" min={1} placeholder="All of them" value={limit} onChange={(e) => setLimit(e.target.value ? Number(e.target.value) : "")} />
          <div className="field-help">
            {n != null ? `About ${plural(n, "document")}` : ""}
            {n ? ` · about ${duration(n * perDoc)} if nothing is cached yet` : ""}. A sample of 100 is enough to compare settings.
          </div>
        </div>
        <div className="field">
          <div className="field-label">Name</div>
          <input type="text" placeholder={describeConfig(config, ocr_engines)} value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="field full">
          <div className="field-label">Notes</div>
          <input type="text" placeholder="What you're trying, so the leaderboard makes sense later" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
        <div className="full row">
          <button className="primary" disabled={busy || !overview.testset.documents} onClick={start}>Start experiment</button>
          {!overview.testset.documents && <span className="muted small">Build the test set first.</span>}
          <span className="muted small">Experiments run one at a time; the next waits its turn.</span>
        </div>
      </div>
    </div>
  );
}

function subsetCount(subset: string, overview: Overview, experiments: Experiment[]): number | null {
  const ts = overview.testset;
  if (subset === "all") return ts.documents;
  if (subset === "digital") return ts.kinds.digital;
  if (subset === "scans") return ts.kinds.scan + ts.kinds.image;
  if (subset === "labelled") return ts.labelled;
  if (subset.startsWith("client:")) return ts.clients.find((c) => c.name === subset.slice(7))?.documents ?? 0;
  if (subset.startsWith("failing:")) {
    const e = experiments.find((x) => x.id === subset.slice(8));
    return e ? Math.round((1 - (e.summary.ok_rate ?? 1)) * (e.summary.documents - e.summary.errors)) + e.summary.errors : null;
  }
  return null;
}

function Choice({ label, value, onChange, options, help, disabled }: {
  label: string; value: string; onChange: (v: string) => void; options: Record<string, string>; help?: string; disabled?: boolean;
}) {
  return (
    <div className={`field ${disabled ? "dim" : ""}`}>
      <div className="field-label">{label}</div>
      <select value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
        {Object.entries(options).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      {help && <div className="field-help">{help}</div>}
    </div>
  );
}

// Documents --------------------------------------------------------------------------------------

function Documents({ overview, experiments }: { overview: Overview; experiments: Experiment[] }) {
  const done = experiments.filter((e) => e.summary.documents > 0);
  const [exp, setExp] = useState<string>(() => done[0]?.id ?? "");
  const [rows, setRows] = useState<DocRow[] | null>(null);
  const [q, setQ] = useState("");
  const [client, setClient] = useState("");
  const [kind, setKind] = useState("");
  const [state, setState] = useState("");
  const [page, setPage] = useState(0);
  const PAGE = 50;

  useEffect(() => {
    if (!exp && done[0]) setExp(done[0].id);
  }, [done.length]);
  useEffect(() => {
    lpo.docs(exp || undefined).then(setRows).catch((e) => toast(e.message));
  }, [exp, overview.testset.documents, overview.testset.labelled]);

  const filtered = (rows ?? []).filter((r) => {
    if (client && r.client !== client) return false;
    if (kind && r.kind !== kind) return false;
    if (state === "labelled" && !r.labelled) return false;
    if (state === "unlabelled" && (r.labelled || r.excluded)) return false;
    if (state === "failing" && (!r.result || r.result.ok)) return false;
    if (state === "passing" && !r.result?.ok) return false;
    if (state === "excluded" && !r.excluded) return false;
    if (state !== "excluded" && r.excluded) return false;
    if (q && !`${r.key} ${r.result?.lpo_number ?? ""}`.toLowerCase().includes(q.toLowerCase())) return false;
    return true;
  });
  const shown = filtered.slice(page * PAGE, page * PAGE + PAGE);

  const nextUnlabelled = filtered.find((r) => !r.labelled && !r.excluded);

  return (
    <div className="card">
      <div className="card-head">
        <h2>Documents</h2>
        <input type="text" placeholder="Find a file or LPO number…" value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} style={{ maxWidth: 230 }} aria-label="Find" />
        <select value={client} onChange={(e) => { setClient(e.target.value); setPage(0); }} style={{ maxWidth: 170 }} aria-label="Client">
          <option value="">All clients</option>
          {overview.testset.clients.map((c) => <option key={c.name}>{c.name}</option>)}
        </select>
        <select value={kind} onChange={(e) => { setKind(e.target.value); setPage(0); }} style={{ maxWidth: 130 }} aria-label="Kind">
          <option value="">All kinds</option>
          {Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select value={state} onChange={(e) => { setState(e.target.value); setPage(0); }} style={{ maxWidth: 170 }} aria-label="State">
          <option value="">Any state</option>
          <option value="unlabelled">Not labelled yet</option>
          <option value="labelled">Labelled</option>
          <option value="failing">Failing checks</option>
          <option value="passing">Passing checks</option>
          <option value="excluded">Taken out</option>
        </select>
        <span className="grow" />
        <label className="row small muted" style={{ gap: 6 }}>
          Results from
          <select value={exp} onChange={(e) => setExp(e.target.value)} style={{ maxWidth: 240 }}>
            <option value="">No experiment</option>
            {done.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </select>
        </label>
        {nextUnlabelled && (
          <a className="button small primary" href={href({ page: "lpo-doc", id: nextUnlabelled.id, exp: exp || undefined })}>Label the next one</a>
        )}
      </div>
      {!rows ? (
        <p className="muted" style={{ padding: 16 }}>Loading…</p>
      ) : filtered.length === 0 ? (
        <div className="empty"><p>{rows.length ? "Nothing matches." : "The test set is empty."}</p></div>
      ) : (
        <>
          <div style={{ overflowX: "auto" }}>
            <table className="list">
              <thead>
                <tr><th>Document</th><th>Client</th><th>Kind</th><th className="num">Pages</th><th>Label</th>
                  {exp && <><th>Read as</th><th>LPO number</th><th className="num">Lines</th><th>Checks</th></>}</tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.id} className="clickable" onClick={() => navigate({ page: "lpo-doc", id: r.id, exp: exp || undefined })}>
                    <td style={{ maxWidth: 380 }}><span className="ellipsis mono small" style={{ display: "block" }} title={r.key}>{r.key.split("/").pop()}</span></td>
                    <td className="nowrap small">{r.client}</td>
                    <td className="nowrap small">{KIND_LABEL[r.kind]}</td>
                    <td className="num small">{r.pages}</td>
                    <td className="nowrap">{r.excluded ? <span className="badge">taken out</span> : r.labelled ? <span className="badge accent">labelled</span> : null}
                      {r.split === "holdout" && <span className="badge" title="Held out: label it, but don't work out rules from it"> held out</span>}</td>
                    {exp && (r.result ? (
                      <>
                        <td className="small nowrap">{r.result.error ? "" : overview.schema.document_types[r.result.document_type ?? ""] ?? "–"}</td>
                        <td className="mono small">{r.result.lpo_number ?? <span className="muted">–</span>}</td>
                        <td className="num small">{r.result.error ? "" : r.result.lines}</td>
                        <td>{r.result.error ? <span className="badge danger" title={r.result.error}>failed</span>
                          : r.result.ok ? <span className="badge ok">passed</span>
                          : <span className="badge warn" title={Object.entries(r.result.checks ?? {}).filter(([k, v]) => !v && k !== "ok").map(([k]) => overview.checks[k]).join("\n")}>
                              {Object.entries(r.result.checks ?? {}).filter(([k, v]) => !v && k !== "ok").length} failed</span>}</td>
                      </>
                    ) : <td colSpan={4} className="muted small">not in this experiment</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row" style={{ padding: "10px 16px" }}>
            <span className="muted small">{plural(filtered.length, "document")}</span>
            <span className="grow" />
            <button className="small" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
            <span className="small muted">{page + 1} / {Math.max(1, Math.ceil(filtered.length / PAGE))}</span>
            <button className="small" disabled={(page + 1) * PAGE >= filtered.length} onClick={() => setPage(page + 1)}>Next</button>
          </div>
        </>
      )}
    </div>
  );
}

export async function confirmDelete(name: string): Promise<boolean> {
  return confirm(`Delete “${name}”?`, { body: "Its results are deleted. Cached conversions stay, for other experiments.", confirm: "Delete", danger: true });
}
