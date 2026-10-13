/** What a run reads: files dropped or chosen here (uploaded straight away), files and folders on
 *  this computer (by path: Docling reads them where they are), web addresses, and files of an
 *  earlier run. mode "sources" takes any number of these; "file" takes one file. */
import { useEffect, useRef, useState } from "react";
import { api, type Input, type OutputFile, type Run } from "../api";
import { bytes } from "../ui/format";

type Pending = { key: string; name: string; error?: string };

export function itemName(i: Input): string {
  if (i.kind === "url") return i.url;
  if (i.kind === "path") return i.path;
  if (i.kind === "run") return i.name ?? i.file.split("/").pop() ?? i.file;
  return i.name;
}

const KIND_LABEL = { upload: "File", path: "On disk", url: "Web", run: "From run" } as const;

export function Inputs({ mode, items, onChange, label }: {
  mode: "sources" | "file";
  items: Input[];
  onChange: (items: Input[]) => void;
  label: string;
}) {
  const [over, setOver] = useState(false);
  const [pending, setPending] = useState<Pending[]>([]);
  const [adding, setAdding] = useState<"path" | "url" | "run" | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const latest = useRef(items);
  latest.current = items;
  const many = mode === "sources";

  const put = (added: Input[]) => onChange(many ? [...latest.current, ...added] : added.slice(-1));

  const upload = async (files: FileList | File[]) => {
    const list = Array.from(files);
    if (!list.length) return;
    const chosen = many ? list : list.slice(0, 1);
    const keys = chosen.map((f) => ({ key: Math.random().toString(36).slice(2), name: f.name }));
    setPending((p) => [...p, ...keys]);
    await Promise.all(chosen.map(async (file, n) => {
      try {
        const done = await api.upload(file);
        put([done]);
        setPending((p) => p.filter((x) => x.key !== keys[n].key));
      } catch (e) {
        setPending((p) => p.map((x) => (x.key === keys[n].key ? { ...x, error: (e as Error).message } : x)));
      }
    }));
  };

  const addTyped = async () => {
    const value = text.trim();
    if (!value) return;
    setError(null);
    try {
      const lines = many ? value.split("\n").map((s) => s.trim()).filter(Boolean) : [value];
      const checked = [];
      for (const line of lines) {
        checked.push(await api.checkInput(adding === "url" ? { kind: "url", url: line } : { kind: "path", path: line }));
      }
      put(checked);
      setText("");
      setAdding(null);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const remove = (n: number) => {
    const item = items[n];
    if (item.kind === "upload") api.discardUpload(item.id).catch(() => {});
    onChange(items.filter((_, i) => i !== n));
  };

  return (
    <div>
      {(many || items.length === 0) && (
        <div className={`dropzone${over ? " over" : ""}`} role="button" tabIndex={0}
          onClick={() => fileRef.current?.click()}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && fileRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files); }}>
          <div><strong>Drop {many ? "documents" : "a file"} here</strong> or click to choose {many ? "them" : "one"}</div>
          <div className="muted small">
            {many ? "PDF, Word, PowerPoint, Excel, HTML, Markdown, images, audio, video, e-mail, EPUB, LaTeX, XML and more" : label}
          </div>
          <input ref={fileRef} type="file" multiple={many} hidden onChange={(e) => { upload(e.target.files ?? []); e.target.value = ""; }} />
        </div>
      )}

      {(items.length > 0 || pending.length > 0) && (
        <div className="input-list">
          {items.map((item, n) => (
            <div className="input-item" key={n}>
              <span className="kind">{item.kind === "path" && item.folder ? "Folder" : KIND_LABEL[item.kind]}</span>
              <span className="ellipsis grow mono small" title={itemName(item)}>{itemName(item)}</span>
              {item.kind === "upload" && item.size != null && <span className="muted small nowrap">{bytes(item.size)}</span>}
              <button type="button" className="ghost small" onClick={() => remove(n)} aria-label={`Remove ${itemName(item)}`}>Remove</button>
            </div>
          ))}
          {pending.map((p) => (
            <div className="input-item uploading" key={p.key}>
              <span className="kind">File</span>
              <span className="ellipsis grow small">{p.name}</span>
              {p.error ? (
                <>
                  <span className="small" style={{ color: "var(--danger)" }}>{p.error}</span>
                  <button type="button" className="ghost small" onClick={() => setPending((x) => x.filter((y) => y.key !== p.key))}>Dismiss</button>
                </>
              ) : <span className="muted small">Adding…</span>}
            </div>
          ))}
        </div>
      )}

      <div className="row" style={{ marginTop: 10 }}>
        <button type="button" className={`small${adding === "path" ? " primary" : ""}`} onClick={() => { setAdding(adding === "path" ? null : "path"); setError(null); }}>
          + Path on this computer
        </button>
        {many && (
          <button type="button" className={`small${adding === "url" ? " primary" : ""}`} onClick={() => { setAdding(adding === "url" ? null : "url"); setError(null); }}>
            + Web address
          </button>
        )}
        <button type="button" className={`small${adding === "run" ? " primary" : ""}`} onClick={() => { setAdding(adding === "run" ? null : "run"); setError(null); }}>
          + From an earlier run
        </button>
      </div>

      {(adding === "path" || adding === "url") && (
        <div className="stack" style={{ marginTop: 10, gap: 6 }}>
          {many ? (
            <textarea autoFocus rows={2} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false}
              placeholder={adding === "url" ? "https://arxiv.org/pdf/2206.01062   (one per line)" : "/Users/me/Documents/report.pdf  or a folder   (one per line)"} />
          ) : (
            <input autoFocus value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addTyped())}
              placeholder="/Users/me/Documents/report.json" spellCheck={false} />
          )}
          {adding === "path" && many && <div className="muted small">A folder converts every document in it (Input formats in Input narrows which).</div>}
          {error && <div className="field-when" style={{ color: "var(--danger)" }}>{error}</div>}
          <div className="row"><button type="button" className="small primary" onClick={addTyped} disabled={!text.trim()}>Add</button></div>
        </div>
      )}
      {adding === "run" && <FromRun onPick={(i) => { put([i]); setAdding(null); }} />}
    </div>
  );
}

/** Pick a file an earlier run made (a Docling JSON to export, a DocLang file to validate…). */
function FromRun({ onPick }: { onPick: (i: Input) => void }) {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [run, setRun] = useState("");
  const [files, setFiles] = useState<OutputFile[] | null>(null);
  useEffect(() => {
    api.runs().then((r) => setRuns(r.filter((x) => (x.outputs?.count ?? 0) > 0))).catch(() => setRuns([]));
  }, []);
  useEffect(() => {
    setFiles(null);
    if (run) api.run(run).then((d) => setFiles(d.files.files.filter((f) => f.kind !== "image"))).catch(() => setFiles([]));
  }, [run]);
  if (runs === null) return <p className="muted small" style={{ marginTop: 8 }}>Loading runs…</p>;
  if (!runs.length) return <p className="muted small" style={{ marginTop: 8 }}>No run has made files yet.</p>;
  return (
    <div className="stack" style={{ marginTop: 10, gap: 6 }}>
      <select value={run} onChange={(e) => setRun(e.target.value)}>
        <option value="">Choose a run…</option>
        {runs.map((r) => <option key={r.id} value={r.id}>{r.title} · {r.tool_title} · {new Date(r.created).toLocaleString()}</option>)}
      </select>
      {files && (
        <select value="" onChange={(e) => e.target.value && onPick({ kind: "run", run, file: `output/${e.target.value}`, name: e.target.value.split("/").pop() })}>
          <option value="">Choose a file…</option>
          {files.map((f) => <option key={f.path} value={f.path}>{f.path} ({bytes(f.size)})</option>)}
        </select>
      )}
    </div>
  );
}
