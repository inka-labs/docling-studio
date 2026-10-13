/** What a run made, per document: the page Docling's viewer shows, Markdown rendered, HTML, the
 *  structure Docling found (text by kind, tables, pictures with what enrichment said), chunks, the
 *  other formats as text, page and debug images, profiling, and every file. */
import DOMPurify from "dompurify";
import { marked } from "marked";
import { useEffect, useMemo, useState } from "react";
import { api, type DocPicture, type DocSummary, type DocTable, type OutputDocument, type RunDetail } from "../api";
import { href, navigate } from "../router";
import { toast } from "../ui/Dialogs";
import { bytes, plural } from "../ui/format";

type View = { key: string; label: string; count?: number };
const TEXT_KINDS: Record<string, string> = {
  text: "Text", doctags: "DocTags", doclang: "DocLang", yaml: "YAML", vtt: "WebVTT", latex: "LaTeX", xml: "XML", csv: "CSV",
};
const RAW_LIMIT = 3 * 1024 * 1024;

export default function Results({ run, doc, view }: { run: RunDetail; doc?: string; view?: string }) {
  const documents = run.files.documents;
  const current: OutputDocument | undefined = documents.find((d) => d.name === doc) ?? documents[0];
  const fileUrl = (path: string) => run.file_base + "output/" + path.split("/").map(encodeURIComponent).join("/");
  const files = useMemo(() => run.files.files.filter((f) => current?.files.includes(f.path)), [run.files.files, current]);
  const pick = (kind: string, test?: (p: string) => boolean) => files.find((f) => f.kind === kind && (!test || test(f.path)));

  const json = pick("json", (p) => !p.includes("/"));
  const markdown = pick("markdown");
  const html = pick("html");
  const chunks = pick("chunks");
  const profiling = pick("profiling");
  const images = files.filter((f) => f.kind === "image");
  const texts = files.filter((f) => f.kind in TEXT_KINDS);

  const views: View[] = [];
  if (json) views.push({ key: "document", label: "Document" });
  if (markdown) views.push({ key: "markdown", label: "Markdown" });
  if (html) views.push({ key: "html", label: "HTML" });
  if (json) views.push({ key: "structure", label: "Structure" }, { key: "tables", label: "Tables" }, { key: "pictures", label: "Pictures" });
  if (chunks) views.push({ key: "chunks", label: "Chunks" });
  for (const f of texts) views.push({ key: `raw:${f.path}`, label: TEXT_KINDS[f.kind] });
  if (json) views.push({ key: `raw:${json.path}`, label: "JSON" });
  if (images.length) views.push({ key: "images", label: "Images", count: images.length });
  if (profiling) views.push({ key: "profiling", label: "Profiling" });
  views.push({ key: "files", label: "Files", count: files.length });

  const active = views.find((v) => v.key === view) ?? views[0];
  const go = (d: string | undefined, v: string | undefined) => navigate({ page: "run", id: run.id, doc: d, view: v }, true);

  return (
    <div className="card">
      <div className="card-head">
        <h2>Results</h2>
        <span className="muted small">{plural(run.files.files.length, "file")} · {bytes(run.files.total_size)}</span>
        <span className="grow" />
        {json && (
          <a className="button small" href={href({ page: "tool", id: "serialize", file: `${run.id}:output/${json.path}` })} title="Make HTML, Markdown, DocTags… from this document without converting again">
            Export as…
          </a>
        )}
      </div>
      <div className={documents.length > 1 ? "result-layout" : undefined} style={documents.length > 1 ? { padding: 12 } : undefined}>
        {documents.length > 1 && (
          <div className="doc-list" role="tablist" aria-label="Documents">
            {documents.map((d) => (
              <button key={d.name} className={d.name === current?.name ? "active" : ""} onClick={() => go(d.name, active?.key)}>
                {d.name}
                <span className="muted small" style={{ display: "block" }}>{d.kinds.filter((k) => k !== "image").join(" · ")}</span>
              </button>
            ))}
          </div>
        )}
        <div className={documents.length > 1 ? "card" : undefined} style={{ minWidth: 0 }}>
          <div className="tabs" role="tablist">
            {views.map((v) => (
              <button key={v.key} role="tab" aria-selected={v.key === active.key} className={v.key === active.key ? "active" : ""} onClick={() => go(current?.name, v.key)}>
                {v.label}{v.count !== undefined && <span className="count">{v.count}</span>}
              </button>
            ))}
          </div>
          <div className="viewer">
            {active.key === "document" && json && <DocumentView runId={run.id} file={`output/${json.path}`} />}
            {active.key === "markdown" && markdown && <MarkdownView url={fileUrl(markdown.path)} base={fileUrl(markdown.path.split("/").slice(0, -1).join("/") + "/").replace(/\/+$/, "/")} />}
            {active.key === "html" && html && <iframe title="HTML" src={fileUrl(html.path)} sandbox="allow-scripts allow-popups" />}
            {active.key === "structure" && json && <Structure runId={run.id} file={`output/${json.path}`} />}
            {active.key === "tables" && json && <Tables runId={run.id} file={`output/${json.path}`} />}
            {active.key === "pictures" && json && <Pictures runId={run.id} file={`output/${json.path}`} />}
            {active.key === "chunks" && chunks && <Chunks url={fileUrl(chunks.path)} size={chunks.size} />}
            {active.key.startsWith("raw:") && <Raw url={fileUrl(active.key.slice(4))} size={files.find((f) => f.path === active.key.slice(4))?.size ?? 0} />}
            {active.key === "images" && (
              <div className="gallery">
                {images.map((f) => (
                  <figure key={f.path}>
                    <a href={fileUrl(f.path)} target="_blank" rel="noreferrer"><img src={fileUrl(f.path)} alt={f.path} loading="lazy" /></a>
                    <figcaption className="ellipsis" title={f.path}>{imageLabel(f.path)}</figcaption>
                  </figure>
                ))}
              </div>
            )}
            {active.key === "profiling" && profiling && <Profiling url={fileUrl(profiling.path)} />}
            {active.key === "files" && (
              <table className="list">
                <tbody>
                  {files.map((f) => (
                    <tr key={f.path}>
                      <td className="mono small" style={{ wordBreak: "break-all" }}>{f.path}</td>
                      <td className="muted small">{f.kind}</td>
                      <td className="num muted small nowrap">{bytes(f.size)}</td>
                      <td className="nowrap" style={{ textAlign: "right" }}>
                        <a className="button small" href={fileUrl(f.path)} download={f.path.split("/").pop()}>Download</a>{" "}
                        <button className="small" onClick={() => api.reveal(run.id, `output/${f.path}`).catch((e) => toast(e.message))}>Show</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function imageLabel(path: string): string {
  const name = path.split("/").pop() ?? path;
  if (path.startsWith("debug/")) return `Debug · ${name.replace(/\.png$/, "").replace(/_/g, " ")}`;
  const m = name.match(/^(page|image|table)_0*(\d+)_/);
  return m ? `${m[1] === "page" ? "Page" : m[1] === "image" ? "Picture" : "Table"} ${m[2]}` : name;
}

function useFetch<T>(load: () => Promise<T>, deps: unknown[]): { data: T | null; error: string | null } {
  const [state, setState] = useState<{ data: T | null; error: string | null }>({ data: null, error: null });
  useEffect(() => {
    let alive = true;
    setState({ data: null, error: null });
    load().then((data) => alive && setState({ data, error: null })).catch((e) => alive && setState({ data: null, error: (e as Error).message }));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}

function Loading({ error, what = "Loading…" }: { error: string | null; what?: string }) {
  return error ? <div className="banner error" style={{ margin: 14 }}>{error}</div> : <p className="muted" style={{ padding: 16 }}>{what}</p>;
}

async function text(url: string): Promise<string> {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.text();
}

/** What `docling-view` opens: the document as HTML, with each page's image next to its text. */
function DocumentView({ runId, file }: { runId: string; file: string }) {
  const [split, setSplit] = useState(true);
  const { data, error } = useFetch(() => api.docView(runId, file, split), [runId, file, split]);
  return (
    <>
      <div className="row" style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)" }}>
        <div className="chips">
          <button className={`chip${split ? " on" : ""}`} onClick={() => setSplit(true)}>Pages beside text</button>
          <button className={`chip${!split ? " on" : ""}`} onClick={() => setSplit(false)}>Text only</button>
        </div>
        <span className="grow" />
        {data && <a className="small" href={data.url} target="_blank" rel="noreferrer">Open in a new tab ↗</a>}
      </div>
      {data ? <iframe title="Document" src={data.url} sandbox="allow-scripts allow-popups" /> : <Loading error={error} what="Laying out the document (docling-serialize)…" />}
    </>
  );
}

function MarkdownView({ url, base }: { url: string; base: string }) {
  const [raw, setRaw] = useState(false);
  const { data, error } = useFetch(() => text(url), [url]);
  const rendered = useMemo(() => {
    if (data == null || raw) return "";
    const htmlText = DOMPurify.sanitize(marked.parse(data, { async: false }) as string);
    const doc = new DOMParser().parseFromString(htmlText, "text/html");
    doc.querySelectorAll("img").forEach((img) => {
      const src = img.getAttribute("src") ?? "";
      if (src && !/^(data:|https?:|\/)/.test(src)) img.setAttribute("src", base + src.split("/").map(encodeURIComponent).join("/"));
    });
    doc.querySelectorAll("a").forEach((a) => a.setAttribute("target", "_blank"));
    return doc.body.innerHTML;
  }, [data, raw, base]);
  if (data == null) return <Loading error={error} />;
  return (
    <>
      <div className="row" style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)" }}>
        <div className="chips">
          <button className={`chip${!raw ? " on" : ""}`} onClick={() => setRaw(false)}>Rendered</button>
          <button className={`chip${raw ? " on" : ""}`} onClick={() => setRaw(true)}>Source</button>
        </div>
        <span className="grow" />
        <button className="small ghost" onClick={() => navigator.clipboard.writeText(data).then(() => toast("Markdown copied"))}>Copy Markdown</button>
      </div>
      {raw ? <pre className="raw">{data}</pre> : <div className="markdown" dangerouslySetInnerHTML={{ __html: rendered }} />}
    </>
  );
}

function Raw({ url, size }: { url: string; size: number }) {
  const big = size > RAW_LIMIT;
  const { data, error } = useFetch(() => (big ? Promise.resolve("") : text(url)), [url]);
  if (big) return <p style={{ padding: 16 }}>This file is {bytes(size)}: <a href={url} target="_blank" rel="noreferrer">open it</a> or download it from Files.</p>;
  if (data == null) return <Loading error={error} />;
  let shown = data;
  if (url.endsWith(".json")) {
    try {
      shown = JSON.stringify(JSON.parse(data), null, 2);
    } catch {
      /* as it is */
    }
  }
  return (
    <>
      <div className="row" style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)" }}>
        <span className="muted small">{bytes(size)}</span>
        <span className="grow" />
        <button className="small ghost" onClick={() => navigator.clipboard.writeText(data).then(() => toast("Copied"))}>Copy</button>
      </div>
      <pre className="raw">{shown}</pre>
    </>
  );
}

function Structure({ runId, file }: { runId: string; file: string }) {
  const { data, error } = useFetch<DocSummary>(() => api.docSummary(runId, file), [runId, file]);
  if (!data) return <Loading error={error} />;
  const labels = Object.entries(data.labels);
  const max = Math.max(1, ...labels.map(([, n]) => n));
  return (
    <div className="stack" style={{ padding: 16 }}>
      <div className="stat-row">
        {[["Pages", data.pages], ["Text items", data.texts], ["Tables", data.tables], ["Pictures", data.pictures],
          ["Key-value items", data.key_value_items], ["Form items", data.form_items], ["Groups", data.groups]].map(([label, value]) => (
          <div className="stat" key={label as string}><div className="value">{(value as number).toLocaleString()}</div><div className="label">{label}</div></div>
        ))}
      </div>
      <dl className="kv">
        <dt>Source</dt><dd>{data.origin.filename ?? data.name}</dd>
        <dt>Type</dt><dd>{data.origin.mimetype ?? "—"}</dd>
        <dt>Docling document</dt><dd>version {data.version}</dd>
        <dt>Page furniture</dt><dd>{plural(data.furniture, "item")} (headers, footers, page numbers: left out of Markdown)</dd>
      </dl>
      {labels.length > 0 && (
        <div>
          <h3>Text by kind</h3>
          <div className="bar-chart">
            {labels.map(([label, n]) => (
              <div className="bar-row" key={label}>
                <span className="ellipsis">{label.replace(/_/g, " ")}</span>
                <div><div className="bar" style={{ width: `${(n / max) * 100}%` }} /></div>
                <span className="num muted">{n.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function csv(rows: string[][]): string {
  return rows.map((r) => r.map((c) => (/[",\n]/.test(c) ? `"${c.replace(/"/g, '""')}"` : c)).join(",")).join("\n");
}

function Tables({ runId, file }: { runId: string; file: string }) {
  const { data, error } = useFetch<DocTable[]>(() => api.docTables(runId, file), [runId, file]);
  if (!data) return <Loading error={error} />;
  if (!data.length) return <p className="muted" style={{ padding: 16 }}>Docling found no tables in this document{" "}(or table structure was off: --no-tables).</p>;
  return (
    <div className="stack" style={{ padding: 16 }}>
      {data.map((t) => (
        <div key={t.index} className="stack" style={{ gap: 6 }}>
          <div className="row">
            <strong>Table {t.index + 1}</strong>
            <span className="muted small">{t.num_rows} × {t.num_cols}{t.pages.length ? ` · page ${t.pages.join(", ")}` : ""}</span>
            <span className="grow" />
            <button className="small" onClick={() => navigator.clipboard.writeText(csv(t.rows)).then(() => toast("Table copied as CSV"))}>Copy CSV</button>
            <a className="button small" download={`table-${t.index + 1}.csv`} href={URL.createObjectURL(new Blob([csv(t.rows)], { type: "text/csv" }))}>Download CSV</a>
          </div>
          {t.caption && <div className="muted small">{t.caption}</div>}
          <div className="data-table">
            <table>
              <tbody>
                {t.rows.map((row, r) => (
                  <tr key={r}>{row.map((cell, c) => (t.header_rows.includes(r) ? <th key={c}>{cell}</th> : <td key={c}>{cell}</td>))}</tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  );
}

function Pictures({ runId, file }: { runId: string; file: string }) {
  const { data, error } = useFetch<DocPicture[]>(() => api.docPictures(runId, file), [runId, file]);
  if (!data) return <Loading error={error} />;
  if (!data.length) return <p className="muted" style={{ padding: 16 }}>Docling found no pictures in this document.</p>;
  const enriched = data.some((p) => p.classes.length || p.description);
  return (
    <>
      {!enriched && (
        <div className="banner info" style={{ margin: 14 }}>
          Turn on <strong>Enrichment › Enrich picture classes</strong> or <strong>picture description</strong> when converting to have Docling say what each picture is.
        </div>
      )}
      <div className="gallery">
        {data.map((p) => (
          <figure key={p.index}>
            {p.src ? <img src={p.src} alt={p.caption || `Picture ${p.index + 1}`} loading="lazy" /> : (
              <div className="muted small" style={{ height: 180, display: "grid", placeItems: "center", background: "var(--surface-2)", padding: 10, textAlign: "center" }}>
                No image kept (Image export mode: placeholder)
              </div>
            )}
            <figcaption className="stack" style={{ gap: 4 }}>
              <strong>Picture {p.index + 1}{p.pages.length ? ` · page ${p.pages.join(", ")}` : ""}</strong>
              {p.caption && <span className="muted">{p.caption}</span>}
              {p.classes.length > 0 && (
                <span className="chips">
                  {p.classes.slice(0, 3).map((c) => <span key={c.name} className="badge accent">{c.name} {Math.round((c.confidence ?? 0) * 100)}%</span>)}
                </span>
              )}
              {p.description && <span>{p.description}</span>}
              {p.other.length > 0 && <details><summary className="small">More from enrichment</summary><pre className="small" style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(p.other, null, 2)}</pre></details>}
            </figcaption>
          </figure>
        ))}
      </div>
    </>
  );
}

type Chunk = { chunk_index?: number; text: string; raw_text?: string; num_tokens?: number; headings?: string[] | null; captions?: string[] | null; page_numbers?: number[] | null };

function Chunks({ url, size }: { url: string; size: number }) {
  const { data, error } = useFetch(() => (size > 50 * 1024 * 1024 ? Promise.reject(new Error("Too many chunks to show here; download the file.")) : text(url)), [url]);
  const [q, setQ] = useState("");
  const chunks = useMemo(() => (data ?? "").split("\n").filter(Boolean).map((l) => {
    try {
      return JSON.parse(l) as Chunk;
    } catch {
      return { text: l } as Chunk;
    }
  }), [data]);
  if (data == null) return <Loading error={error} />;
  const shown = q ? chunks.filter((c) => c.text.toLowerCase().includes(q.toLowerCase())) : chunks;
  const tokens = chunks.map((c) => c.num_tokens ?? 0);
  return (
    <div className="stack" style={{ padding: 16 }}>
      <div className="row">
        <strong>{plural(chunks.length, "chunk")}</strong>
        {tokens.some(Boolean) && <span className="muted small">{Math.min(...tokens)}–{Math.max(...tokens)} tokens each, {Math.round(tokens.reduce((a, b) => a + b, 0) / chunks.length)} on average</span>}
        <span className="grow" />
        <input type="text" placeholder="Find in chunks…" value={q} onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 240 }} />
      </div>
      {shown.slice(0, 500).map((c, n) => (
        <div key={c.chunk_index ?? n} className="card" style={{ marginTop: 0 }}>
          <div className="card-body stack" style={{ gap: 6, padding: 12 }}>
            <div className="row small muted">
              <strong style={{ color: "var(--text)" }}>#{c.chunk_index ?? n}</strong>
              {c.num_tokens != null && <span>{c.num_tokens} tokens</span>}
              {c.page_numbers?.length ? <span>· page {c.page_numbers.join(", ")}</span> : null}
              {c.headings?.length ? <span className="ellipsis">· {c.headings.join(" › ")}</span> : null}
            </div>
            <div style={{ whiteSpace: "pre-wrap", fontSize: 13 }}>{c.text}</div>
          </div>
        </div>
      ))}
      {shown.length > 500 && <p className="muted small">The first 500 are shown; the file has them all.</p>}
    </div>
  );
}

type Timings = Record<string, { scope: string; count: number; times: number[] }>;

function Profiling({ url }: { url: string }) {
  const { data, error } = useFetch(() => text(url).then((t) => JSON.parse(t) as Timings), [url]);
  if (!data) return <Loading error={error} />;
  const stages = Object.entries(data).map(([name, s]) => ({ name, scope: s.scope, count: s.count, total: s.times.reduce((a, b) => a + b, 0), mean: s.times.length ? s.times.reduce((a, b) => a + b, 0) / s.times.length : 0 }));
  const max = Math.max(0.001, ...stages.map((s) => s.total));
  return (
    <div className="stack" style={{ padding: 16 }}>
      <p className="muted small">Time in each stage of the pipeline (total over all pages, in seconds). Turn on Debug & profiling › Profiling to get this.</p>
      <div className="bar-chart">
        {stages.map((s) => (
          <div className="bar-row" key={s.name}>
            <span className="ellipsis" title={`${s.scope} · ${s.count}×`}>{s.name.replace(/_/g, " ")}</span>
            <div><div className="bar" style={{ width: `${(s.total / max) * 100}%` }} /></div>
            <span className="num muted">{s.total.toFixed(2)} s</span>
          </div>
        ))}
      </div>
      <table className="list">
        <thead><tr><th>Stage</th><th>Per</th><th className="num">Count</th><th className="num">Total</th><th className="num">Mean</th></tr></thead>
        <tbody>
          {stages.map((s) => (
            <tr key={s.name}><td>{s.name}</td><td className="muted">{s.scope}</td><td className="num">{s.count}</td><td className="num">{s.total.toFixed(3)} s</td><td className="num">{s.mean.toFixed(3)} s</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
