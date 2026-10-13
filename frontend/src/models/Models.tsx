/** The models on this computer (Docling's models folder and the Hugging Face cache) and fetching
 *  more: `docling-tools models download` and `download-hf-repo` are Tools; this page links there. */
import { useEffect, useState } from "react";
import { api, type Model } from "../api";
import { href } from "../router";
import { confirm, toast } from "../ui/Dialogs";
import { bytes, plural } from "../ui/format";

export default function Models() {
  const [data, setData] = useState<Awaited<ReturnType<typeof api.models>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [all, setAll] = useState(false);

  const load = () => api.models().then(setData).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const remove = async (m: Model) => {
    if (!(await confirm(`Delete ${m.name}?`, { body: `${bytes(m.size)} is freed. Docling downloads it again the next time a conversion needs it.`, confirm: "Delete", danger: true }))) return;
    try {
      await api.deleteModel(m);
      toast(`Deleted ${m.name}`);
      load();
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const shown = (data?.models ?? []).filter((m) => all || m.docling);
  return (
    <div className="page">
      <div className="page-head">
        <div className="grow">
          <h1>Models</h1>
          <div className="lede">
            Docling downloads the models a conversion needs the first time it needs them. Download them ahead of time for a computer that will
            work offline, or to make the first conversion quick.
          </div>
        </div>
        <div className="row">
          <a className="button primary" href={href({ page: "tool", id: "models" })}>Download models…</a>
          <a className="button" href={href({ page: "tool", id: "hf-models" })}>From Hugging Face…</a>
        </div>
      </div>
      {error && <div className="banner error">{error}</div>}
      {!data && !error && <p className="muted">Measuring the model folders…</p>}
      {data && (
        <div className="card">
          <div className="card-head">
            <h2>On this computer</h2>
            <span className="muted small">{plural(shown.length, "model")} · {bytes(shown.reduce((a, m) => a + m.size, 0))}</span>
            <span className="grow" />
            <label className="row small"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> Show every Hugging Face model</label>
            <button className="small" onClick={load}>Refresh</button>
          </div>
          {shown.length === 0 ? (
            <div className="card-body muted">No models yet. They're downloaded by the first conversion, or with Download models.</div>
          ) : (
            <table className="list">
              <thead><tr><th>Model</th><th>Where</th><th className="num">Size</th><th /></tr></thead>
              <tbody>
                {shown.map((m) => (
                  <tr key={m.where + m.folder}>
                    <td className="mono small" style={{ wordBreak: "break-all" }}>{m.name}</td>
                    <td className="muted small">{m.where === "docling" ? "Docling models folder" : "Hugging Face cache"}</td>
                    <td className="num">{bytes(m.size)}</td>
                    <td style={{ textAlign: "right" }}><button className="small danger ghost" onClick={() => remove(m)}>Delete</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="card-body small muted" style={{ borderTop: "1px solid var(--border)" }}>
            <div>Docling models folder: <code>{data.roots.docling}</code> (what <code>--artifacts-path</code> points to after Download models)</div>
            <div>Hugging Face cache: <code>{data.roots.huggingface}</code></div>
          </div>
        </div>
      )}
    </div>
  );
}
