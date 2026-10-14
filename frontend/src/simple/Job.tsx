/** One conversion: what it's doing in plain words, then the files it saved, to open or find, a look
 *  at the result, and saving it as another format without converting again. */
import { useEffect, useRef, useState } from "react";
import { api, changed, type Delivered, type RunDetail } from "../api";
import { href, navigate } from "../router";
import { confirm, toast } from "../ui/Dialogs";
import { between, bytes, duration, plural } from "../ui/format";
import { FileIcon, FORMAT_INFO } from "./icons";

const ACTIVE = ["queued", "running"];

export default function Job({ id, more }: { id: string; more?: boolean }) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
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

      {["succeeded", "partial"].includes(run.status) && delivered.length > 0 && (
        <SaveMore run={run} open={!!more} onSaved={(r) => setRun({ ...run, ...r })} />
      )}

      {!active && (
        <div className="row" style={{ marginTop: 20 }}>
          <a className="button primary" href={href({ page: "home" })}>Convert another</a>
          {run.status !== "succeeded" && <a className="button" href={href({ page: "home" })}>Try again</a>}
          <span className="grow" />
          <button className="ghost" onClick={remove}>Remove from history</button>
        </div>
      )}
    </div>
  );
}

/** Save a finished conversion as more formats: made from what was already read, so it takes seconds. */
function SaveMore({ run, open, onSaved }: { run: RunDetail; open: boolean; onSaved: (r: RunDetail) => void }) {
  const [shown, setShown] = useState(open);
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [picked, setPicked] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const made = new Set(run.finish?.formats ?? []);

  useEffect(() => {
    api.jobOptions().then((o) => setLabels(o.formats)).catch(() => {});
  }, []);
  useEffect(() => {
    if (open) setTimeout(() => box.current?.scrollIntoView({ behavior: "smooth", block: "center" }), 300);
  }, [open]);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const updated = await api.saveMore(run.id, picked);
      onSaved(await api.run(updated.id));
      toast(`Saved as ${picked.map((f) => FORMAT_INFO[f]?.ext ?? f).join(", ")}`);
      setPicked([]);
      setShown(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  if (!shown) {
    return <div style={{ marginTop: 14 }}><button onClick={() => setShown(true)}>Save as another format…</button></div>;
  }
  return (
    <div className="card" ref={box} style={{ marginTop: 14 }}>
      <div className="card-head"><h2>Save as another format</h2><span className="grow" /><button className="ghost small" onClick={() => setShown(false)}>Close</button></div>
      <div className="card-body stack">
        <p className="muted" style={{ margin: 0 }}>Made from what was already read, so it only takes a few seconds.</p>
        <div className="format-grid">
          {Object.entries(labels).map(([key, label]) => {
            const on = picked.includes(key);
            return (
              <button key={key} className={`format${on ? " on" : ""}`} aria-pressed={on}
                onClick={() => setPicked(on ? picked.filter((f) => f !== key) : [...picked, key])}>
                <span className="format-badge" style={{ background: FORMAT_INFO[key]?.color }}>{FORMAT_INFO[key]?.ext}</span>
                <span className="format-label">{label}</span>
                <span className="format-note">{made.has(key) ? "Already saved: makes another copy" : FORMAT_INFO[key]?.note}</span>
                {on && <span className="format-check" aria-hidden>✓</span>}
              </button>
            );
          })}
        </div>
        {error && <div className="banner error" style={{ margin: 0 }}>{error}</div>}
        <div><button className="primary" onClick={save} disabled={!picked.length || saving}>{saving ? "Saving…" : "Save"}</button></div>
      </div>
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
