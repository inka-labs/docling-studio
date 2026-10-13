/** Every run, newest first: what it read, how it went, what it made. */
import { useEffect, useState } from "react";
import { api, changed, type Run } from "../api";
import { href, navigate } from "../router";
import { confirm } from "../ui/Dialogs";
import { ago, between, bytes, duration, plural, STATUS_LABEL } from "../ui/format";

export default function Runs() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [tool, setTool] = useState("");

  useEffect(() => {
    const load = () => api.runs().then(setRuns).catch((e) => setError(e.message));
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, []);

  if (error) return <div className="page"><div className="banner error">{error}</div></div>;
  if (!runs) return <div className="page"><p className="muted">Loading…</p></div>;

  const tools = [...new Set(runs.map((r) => r.tool_title))];
  const q = filter.trim().toLowerCase();
  const shown = runs.filter((r) => (!tool || r.tool_title === tool) && (!q || `${r.title} ${r.command} ${r.status}`.toLowerCase().includes(q)));
  const finished = runs.filter((r) => !["queued", "running"].includes(r.status));

  const clear = async () => {
    const old = finished.filter((r) => r.status !== "succeeded");
    if (!old.length || !(await confirm(`Delete ${plural(old.length, "run")} that failed or were stopped?`, { body: "Their logs and any files they made are deleted.", confirm: "Delete", danger: true }))) return;
    await Promise.all(old.map((r) => api.deleteRun(r.id).catch(() => {})));
    setRuns(await api.runs());
    changed();
  };

  return (
    <div className="page wide">
      <div className="page-head">
        <div className="grow">
          <h1>Runs</h1>
          <div className="lede">Each run keeps its log and everything it made, until you delete it.</div>
        </div>
        <a className="button primary" href={href({ page: "convert" })}>New conversion</a>
      </div>
      {runs.length === 0 ? (
        <div className="card empty">
          <h2>No runs yet</h2>
          <p>Convert a document and it shows up here.</p>
        </div>
      ) : (
        <div className="card">
          <div className="card-head">
            <input type="text" placeholder="Find a run…" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ maxWidth: 260 }} aria-label="Find a run" />
            <select value={tool} onChange={(e) => setTool(e.target.value)} style={{ maxWidth: 220 }} aria-label="Tool">
              <option value="">All tools</option>
              {tools.map((t) => <option key={t}>{t}</option>)}
            </select>
            <span className="grow" />
            <button className="small" onClick={clear} disabled={!finished.some((r) => r.status !== "succeeded")}>Delete failed and stopped</button>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table className="list">
              <thead>
                <tr><th>Run</th><th>Tool</th><th>Status</th><th className="num">Took</th><th className="num">Made</th><th>Started</th></tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.id} className="clickable" onClick={() => navigate({ page: "run", id: r.id })}>
                    <td style={{ maxWidth: 420 }}><a href={href({ page: "run", id: r.id })} className="ellipsis" style={{ display: "block" }} onClick={(e) => e.stopPropagation()}>{r.title}</a></td>
                    <td className="muted nowrap">{r.tool_title}</td>
                    <td><span className={`status ${r.status}`}>{STATUS_LABEL[r.status]}</span>
                      {r.status === "running" && r.progress.total ? <span className="muted small"> {r.progress.done}/{r.progress.total}</span> : null}</td>
                    <td className="num muted">{duration(between(r.started, r.ended))}</td>
                    <td className="num muted nowrap">{r.outputs ? `${plural(r.outputs.count, "file")} · ${bytes(r.outputs.size)}` : ""}</td>
                    <td className="muted nowrap" title={new Date(r.created).toLocaleString()}>{ago(r.created)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
