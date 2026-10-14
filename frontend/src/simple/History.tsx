/** Every conversion, newest first, with the files it saved. */
import { useEffect, useState } from "react";
import { api, type Run } from "../api";
import { href } from "../router";
import { ago, plural } from "../ui/format";
import { FORMAT_INFO } from "./icons";

export default function History() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [q, setQ] = useState("");
  useEffect(() => {
    const load = () => api.runs().then((r) => setRuns(r.filter((x) => x.finish))).catch(() => setRuns([]));
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, []);
  if (!runs) return <div className="page simple"><p className="muted">Loading…</p></div>;
  const shown = runs.filter((r) => !q || r.title.toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="page simple">
      <div className="row" style={{ marginBottom: 16 }}>
        <h1 className="grow">History</h1>
        {runs.length > 5 && <input type="text" placeholder="Find…" value={q} onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 220 }} />}
      </div>
      {runs.length === 0 ? (
        <div className="card empty"><h2>Nothing converted yet</h2><p><a href={href({ page: "home" })}>Convert a document</a> and it shows up here.</p></div>
      ) : (
        <div className="card">
          <ul className="history">
            {shown.map((r) => {
              const saved = (r.delivered ?? []).filter((d) => d.path).length;
              return (
                <li key={r.id}>
                  <a href={href({ page: "job", id: r.id })}>
                    <span className={`status ${r.status}`} aria-label={r.status} />
                    <span className="grow" style={{ minWidth: 0 }}>
                      <span className="ellipsis" style={{ display: "block" }}>{r.title}</span>
                      <span className="muted small">{saved ? plural(saved, "file") + " saved" : r.status === "running" || r.status === "queued" ? "in progress" : "nothing saved"}</span>
                    </span>
                    <span className="chips">
                      {(r.finish?.formats ?? []).map((f) => <span key={f} className="format-badge" style={{ background: FORMAT_INFO[f]?.color }}>{FORMAT_INFO[f]?.ext}</span>)}
                    </span>
                    <span className="muted small nowrap">{ago(r.created)}</span>
                  </a>
                  {["succeeded", "partial"].includes(r.status) && saved > 0 && (
                    <a className="button small another" href={href({ page: "job", id: r.id, more: true })} title="Save as another format, without converting again">
                      Another format…
                    </a>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
