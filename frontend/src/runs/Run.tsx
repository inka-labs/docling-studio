/** One run: how it's going (or went), the command, its log as it's written, and what it made. */
import { useEffect, useRef, useState } from "react";
import { api, changed, type RunDetail } from "../api";
import { itemName } from "../form/Inputs";
import { href, navigate } from "../router";
import { confirm, prompt, toast } from "../ui/Dialogs";
import { between, bytes, duration, plural, STATUS_LABEL, when } from "../ui/format";
import Results from "./Results";

const ACTIVE = ["queued", "running"];

export default function Run({ id, doc, view }: { id: string; doc?: string; view?: string }) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [, tick] = useState(0);

  useEffect(() => {
    let alive = true;
    let timer: number;
    const load = async () => {
      try {
        const r = await api.run(id);
        if (!alive) return;
        setRun(r);
        if (ACTIVE.includes(r.status)) timer = window.setTimeout(load, 1000);
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

  if (error) return <div className="page"><div className="banner error">{error}</div><a href={href({ page: "runs" })}>All runs</a></div>;
  if (!run) return <div className="page"><p className="muted">Loading…</p></div>;

  const active = ACTIVE.includes(run.status);
  const { done, total, failed } = run.progress;
  const sources = Object.values(run.inputs).flat();
  const editHref = run.tool === "convert" ? href({ page: "convert", from: run.id }) : href({ page: "tool", id: run.tool, from: run.id });

  const rename = async () => {
    const title = await prompt("Rename this run", { value: run.title });
    if (title) setRun({ ...run, ...(await api.renameRun(run.id, title)) });
  };
  const stop = async () => setRun({ ...run, ...(await api.cancelRun(run.id)) });
  const remove = async () => {
    if (!(await confirm("Delete this run?", { body: "Its log and every file it made are deleted. The documents it read aren't touched.", confirm: "Delete", danger: true }))) return;
    await api.deleteRun(run.id);
    changed();
    navigate({ page: "runs" });
  };

  return (
    <div className="page wide">
      <div className="page-head">
        <div className="grow" style={{ minWidth: 0 }}>
          <div className="muted small"><a href={href({ page: "runs" })}>Runs</a> › {run.tool_title}</div>
          <div className="row" style={{ flexWrap: "nowrap" }}>
            <h1 className="ellipsis" title={run.title}>{run.title}</h1>
            <button className="ghost small" onClick={rename} aria-label="Rename">✎</button>
          </div>
          <div className="row small muted" style={{ marginTop: 4 }}>
            <span className={`status ${run.status}`}>{STATUS_LABEL[run.status]}</span>
            {run.started && <span>· {active ? "running for" : "took"} {duration(between(run.started, run.ended))}</span>}
            <span>· started {when(run.started ?? run.created)}</span>
            {run.service && <span>· on {run.service}</span>}
          </div>
        </div>
        <div className="row">
          {active && <button className="danger" onClick={stop}>Stop</button>}
          <a className="button" href={editHref}>Change and run again</a>
          {run.files.files.length > 0 && <a className="button" href={`/api/runs/${run.id}/zip`} download>Download all</a>}
          <button onClick={() => api.reveal(run.id).catch((e) => toast(e.message))}>Show folder</button>
          {!active && <button className="danger ghost" onClick={remove}>Delete</button>}
        </div>
      </div>

      {active && (
        <div className="card" style={{ marginBottom: 14 }}>
          <div className="card-body stack" style={{ gap: 8 }}>
            <div className="row small">
              <strong>{run.status === "queued" ? "Waiting for another run to finish…" : total ? `${done} of ${plural(total, "document")} converted` : done ? `${plural(done, "document")} converted` : "Working…"}</strong>
              <span className="muted">The first conversion downloads Docling's models, which can take a few minutes.</span>
            </div>
            <div className={`progress${total ? "" : " indeterminate"}`}><div style={{ width: total ? `${Math.max(3, (done / total) * 100)}%` : undefined }} /></div>
          </div>
        </div>
      )}
      {run.error && !active && <div className="banner error"><strong>{run.status === "partial" ? `${failed} document${failed === 1 ? "" : "s"} couldn't be converted.` : "The run didn't finish."}</strong>{"\n"}{run.error}</div>}
      {run.status === "partial" && <div className="banner warn">Docling carried on past the documents it couldn't convert; the log says why.</div>}

      <div className="stack">
        {run.files.files.length > 0 && <Results run={run} doc={doc} view={view} />}

        <div className="card">
          <div className="card-head"><h2>What it ran</h2></div>
          <div className="card-body stack" style={{ gap: 10 }}>
            <div className="command">{run.command}</div>
            <div className="row">
              <button className="small" onClick={() => navigator.clipboard.writeText(run.command).then(() => toast("Command copied"))}>Copy command</button>
              {run.had_secrets.length > 0 && <span className="muted small">Secrets ({run.had_secrets.join(", ")}) weren't kept.</span>}
            </div>
            {sources.length > 0 && (
              <div>
                <div className="muted small" style={{ marginBottom: 4 }}>Read {plural(sources.length, "input")}:</div>
                <div className="input-list" style={{ marginTop: 0 }}>
                  {sources.map((s, n) => (
                    <div key={n} className="input-item">
                      <span className="kind">{s.kind === "upload" ? "File" : s.kind === "path" ? (s.folder ? "Folder" : "On disk") : s.kind === "url" ? "Web" : "From run"}</span>
                      <span className="ellipsis grow mono small">{itemName(s)}</span>
                      {s.kind === "upload" && s.size != null && <span className="muted small">{bytes(s.size)}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        <Log id={run.id} active={active} />
      </div>
    </div>
  );
}

/** The log as it's written: what's new is fetched every second while the run goes. */
function Log({ id, active }: { id: string; active: boolean }) {
  const [text, setText] = useState("");
  const [truncated, setTruncated] = useState(false);
  const [follow, setFollow] = useState(true);
  const offset = useRef(0);
  const box = useRef<HTMLPreElement>(null);

  useEffect(() => {
    let alive = true;
    let timer: number;
    const load = async () => {
      try {
        const part = await api.runLog(id, offset.current);
        if (!alive) return;
        if (part.text) {
          if (offset.current === 0 && part.truncated) setTruncated(true);
          setText((t) => (t + part.text).slice(-2_000_000));
        }
        offset.current = part.offset;
      } catch {
        /* next time */
      }
      if (alive && active) timer = window.setTimeout(load, 1000);
    };
    load();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [id, active]);

  useEffect(() => {
    if (follow && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [text, follow]);

  const lines = text.split("\n");
  return (
    <div className="card">
      <div className="card-head">
        <h2>Log</h2>
        <span className="grow" />
        <label className="row small"><input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> Follow</label>
        <button className="small ghost" onClick={() => navigator.clipboard.writeText(text).then(() => toast("Log copied"))}>Copy</button>
      </div>
      <pre className="log" ref={box} onScroll={(e) => {
        const el = e.currentTarget;
        const atEnd = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
        if (atEnd !== follow) setFollow(atEnd);
      }}>
        {truncated && <span className="warn">… (the start of a long log is left out; Download all has the whole of it in the run folder){"\n"}</span>}
        {lines.map((line, n) => (
          <span key={n} className={/\b(ERROR|Error|Traceback|Exception|failed)\b/.test(line) && !/of which 0 failed/.test(line) ? "err" : /\bWARN(ING)?\b/.test(line) ? "warn" : undefined}>
            {line}{n < lines.length - 1 ? "\n" : ""}
          </span>
        ))}
        {!text && (active ? "Starting…" : "(nothing was printed)")}
      </pre>
    </div>
  );
}
