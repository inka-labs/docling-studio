/** One conversion: what it's doing in plain words, then the files it saved, to open or find, and a
 *  look at the result. The technical log is there for when something goes wrong. */
import { useEffect, useState } from "react";
import { api, changed, type Delivered, type RunDetail } from "../api";
import { href, navigate } from "../router";
import { confirm, toast } from "../ui/Dialogs";
import { between, bytes, duration, plural } from "../ui/format";
import { FileIcon, FORMAT_INFO } from "./icons";

const ACTIVE = ["queued", "running"];

export default function Job({ id }: { id: string }) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [log, setLog] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ doc: string; url: string | null; error?: string } | null>(null);
  const [, tick] = useState(0);

  useEffect(() => {
    let alive = true;
    let timer: number;
    const load = async () => {
      try {
        const r = await api.run(id);
        if (!alive) return;
        setRun(r);
        if (ACTIVE.includes(r.status)) timer = window.setTimeout(load, 800);
        else changed();
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
    };
    load();
    const clock = setInterval(() => tick((n) => n + 1), 1000);
    return () => {
      alive = false;
      clearTimeout(timer);
      clearInterval(clock);
    };
  }, [id]);

  if (error) return <div className="page simple"><div className="banner error">{error}</div><a href={href({ page: "home" })}>Convert a document</a></div>;
  if (!run) return <div className="page simple"><p className="muted">Loading…</p></div>;

  const active = ACTIVE.includes(run.status);
  const p = run.progress;
  const sources = Object.values(run.inputs).flat();
  const delivered = (run.delivered ?? []).filter((d) => d.path) as (Delivered & { path: string })[];
  const notes = (run.delivered ?? []).filter((d) => !d.path);
  const byDoc = delivered.reduce<Record<string, typeof delivered>>((acc, d) => ((acc[d.document] ??= []).push(d), acc), {});

  const headline = run.status === "queued" ? "Waiting for the conversion before it…"
    : run.status === "running" ? (
      p.phase === "models" ? "Getting ready: downloading the reading models (only the first time)…"
        : p.phase === "saving" ? "Saving your files…"
        : p.total && p.total > 1 ? `Reading document ${Math.min(p.done + 1, p.total)} of ${p.total}…`
        : "Reading your document…")
    : run.status === "succeeded" ? "Done"
    : run.status === "partial" ? "Done, but some documents couldn't be converted"
    : run.status === "cancelled" ? "Stopped"
    : "That didn't work";

  const showLog = async () => {
    if (log !== null) return setLog(null);
    setLog((await api.runLog(run.id, 0)).text);
  };
  const openPreview = async (doc: string) => {
    setPreview({ doc, url: null });
    try {
      setPreview({ doc, url: (await api.docView(run.id, `output/${doc}.json`, true)).url });
    } catch (e) {
      setPreview({ doc, url: null, error: (e as Error).message });
    }
  };
  const remove = async () => {
    if (!(await confirm("Remove from history?", { body: "The files it saved are kept.", confirm: "Remove" }))) return;
    await api.deleteRun(run.id);
    changed();
    navigate({ page: "history" });
  };

  return (
    <div className="page simple">
      <div className="job-head">
        <div className={`job-state ${run.status}`} aria-hidden>{active ? <span className="spinner" /> : run.status === "succeeded" ? "✓" : run.status === "partial" ? "!" : run.status === "cancelled" ? "■" : "✕"}</div>
        <div className="grow" style={{ minWidth: 0 }}>
          <h1>{headline}</h1>
          <div className="muted">
            {plural(sources.length, "document")} · {run.started ? (active ? `${duration(between(run.started, null))} so far` : `took ${duration(between(run.started, run.ended))}`) : "not started yet"}
          </div>
        </div>
        {active && <button onClick={() => api.cancelRun(run.id).then((r) => setRun({ ...run, ...r }))}>Stop</button>}
      </div>

      {active && p.total && p.total > 1 && (
        <div className="progress" style={{ marginBottom: 16 }}><div style={{ width: `${Math.max(4, (p.done / p.total) * 100)}%` }} /></div>
      )}
      {active && !(p.total && p.total > 1) && <div className="progress indeterminate" style={{ marginBottom: 16 }}><div /></div>}

      {sources.length > 1 && active && (
        <ul className="picked card" style={{ padding: 8 }}>
          {sources.map((s, n) => {
            const name = s.kind === "url" ? s.url : (s.name ?? "");
            const done = (p.finished ?? []).includes(name);
            return (
              <li key={n}><FileIcon name={name} /><span className="ellipsis grow">{name}</span><span className={done ? "ok" : "muted"}>{done ? "✓ read" : "waiting"}</span></li>
            );
          })}
        </ul>
      )}

      {(run.status === "failed" || run.status === "interrupted") && (
        <div className="banner error">
          {run.status === "interrupted" ? "The app was closed before this finished." : friendly(run.error)}
          {"\n"}<button className="link" onClick={showLog}>{log === null ? "Show details" : "Hide details"}</button>
        </div>
      )}

      {Object.keys(byDoc).length > 0 && (
        <section className="stack">
          <h2 style={{ marginBottom: 0 }}>Saved in <span className="mono small" style={{ overflowWrap: "anywhere" }}>{run.finish?.folder}</span></h2>
          {Object.entries(byDoc).map(([doc, files]) => (
            <div key={doc} className="card deliverable">
              <div className="card-head">
                <strong className="ellipsis">{doc}</strong>
                <span className="grow" />
                <button className="small" onClick={() => (preview?.doc === doc ? setPreview(null) : openPreview(doc))}>{preview?.doc === doc ? "Hide preview" : "Preview"}</button>
              </div>
              <ul className="files">
                {files.map((f) => (
                  <li key={f.path}>
                    <span className="format-badge" style={{ background: FORMAT_INFO[f.format]?.color }}>{FORMAT_INFO[f.format]?.ext}</span>
                    <span className="ellipsis grow" title={f.path}>{f.path.split(/[\\/]/).pop()}</span>
                    <span className="muted small nowrap">{bytes(f.size)}</span>
                    <button className="primary small" onClick={() => api.openFile(run.id, f.path).catch((e) => toast(e.message))}>Open</button>
                    <button className="small" onClick={() => api.showFile(run.id, f.path).catch((e) => toast(e.message))}>Show in folder</button>
                  </li>
                ))}
              </ul>
              {preview?.doc === doc && (
                <div className="viewer">
                  {preview.url ? <iframe title={`Preview of ${doc}`} src={preview.url} sandbox="allow-scripts allow-popups" />
                    : preview.error ? <div className="banner error" style={{ margin: 12 }}>{preview.error}</div> : <p className="muted" style={{ padding: 16 }}>Preparing the preview…</p>}
                </div>
              )}
            </div>
          ))}
        </section>
      )}
      {notes.map((n, i) => <div key={i} className="banner warn">{n.document}, {FORMAT_INFO[n.format]?.ext ?? n.format}: {n.note}</div>)}

      {!active && (
        <div className="row" style={{ marginTop: 20 }}>
          <a className="button primary" href={href({ page: "home" })}>Convert another</a>
          {run.status !== "succeeded" && <a className="button" href={href({ page: "home" })}>Try again</a>}
          <span className="grow" />
          {!["failed", "interrupted"].includes(run.status) && <button className="ghost" onClick={showLog}>{log === null ? "Details" : "Hide details"}</button>}
          <button className="ghost" onClick={remove}>Remove from history</button>
        </div>
      )}
      {log !== null && <pre className="log" style={{ borderRadius: 10, marginTop: 12 }}>{log || "(nothing was printed)"}</pre>}
    </div>
  );
}

/** Docling's error, in words someone can act on where we know what it means. */
function friendly(error: string | null): string {
  const e = error ?? "";
  if (/password|encrypt/i.test(e)) return "This PDF is password-protected. Open it, save a copy without the password, and convert that.";
  if (/No such file|doesn't exist|is gone/i.test(e)) return "A document couldn't be found. It may have been moved or deleted.";
  if (/HTTP|Connection|resolve|timed out|SSL/i.test(e)) return "Couldn't download a document or the reading models. Check the internet connection and try again.";
  if (/memory|MemoryError|Killed/i.test(e)) return "The computer ran out of memory. Try fewer pages at a time (More options › Pages).";
  if (/not supported|unsupported|format/i.test(e)) return "This kind of file can't be converted.";
  return "Something went wrong while converting." + (e ? ` (${e.slice(0, 200)})` : "");
}
