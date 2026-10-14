/** The everyday converter: add documents, choose what to save them as, Convert. The few choices
 *  that matter sit under "More options"; everything else is Docling's sensible default. */
import { useEffect, useRef, useState } from "react";
import { api, changed, type Input, type JobOptions, type JobRequest, type Run } from "../api";
import { BRAND } from "../brand";
import { itemName } from "../form/Inputs";
import { href, navigate } from "../router";
import { ago, bytes, plural } from "../ui/format";
import { FileIcon, FORMAT_INFO } from "./icons";

const PREFS_KEY = BRAND.storagePrefix + "lastChoices";
type Choices = Omit<JobRequest, "inputs">;
const DEFAULTS: Choices = { formats: ["word"], scan: "auto", language: "", pages: "", pictures: "keep" };

function remembered(): Choices {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(PREFS_KEY) ?? "{}"), pages: "" };
  } catch {
    return DEFAULTS;
  }
}

export default function Home() {
  const [options, setOptions] = useState<JobOptions | null>(null);
  const [items, setItems] = useState<Input[]>([]);
  const [uploading, setUploading] = useState<string[]>([]);
  const [choices, setChoices] = useState<Choices>(remembered);
  const [more, setMore] = useState(false);
  const [over, setOver] = useState(false);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [recent, setRecent] = useState<Run[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.jobOptions().then(setOptions).catch((e) => setError(e.message));
    api.runs().then((r) => setRecent(r.filter((x) => x.finish).slice(0, 5))).catch(() => {});
  }, []);

  const set = (patch: Partial<Choices>) => setChoices((c) => ({ ...c, ...patch }));
  const add = (added: Input[]) => setItems((cur) => [...cur, ...added.filter((a) => !cur.some((c) => JSON.stringify(c) === JSON.stringify(a)))]);

  const upload = async (files: FileList | File[]) => {
    const list = Array.from(files);
    setUploading((u) => [...u, ...list.map((f) => f.name)]);
    await Promise.all(list.map(async (file) => {
      try {
        add([await api.upload(file)]);
      } catch (e) {
        setError(`${file.name}: ${(e as Error).message}`);
      } finally {
        setUploading((u) => u.filter((_, i) => i !== u.indexOf(file.name)));
      }
    }));
  };

  const chooseFiles = async () => {
    if (!options?.native_dialogs) return fileRef.current?.click();
    try {
      add(await api.chooseFiles());
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const chooseFolder = async () => {
    const { path } = await api.chooseFolder("input");
    if (path) add([await api.checkInput({ kind: "path", path })]);
  };
  const addUrl = async () => {
    if (!url?.trim()) return;
    try {
      add([await api.checkInput({ kind: "url", url: url.trim() })]);
      setUrl(null);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const changeFolder = async () => {
    const { path } = await api.chooseFolder("save_to");
    if (path) setOptions(await api.jobOptions());
  };

  const convert = async () => {
    setStarting(true);
    setError(null);
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify({ ...choices, pages: "" }));
    } catch {
      /* only a convenience */
    }
    try {
      const run = await api.startJob({ ...choices, inputs: items });
      changed();
      navigate({ page: "job", id: run.id });
    } catch (e) {
      setError((e as Error).message);
      setStarting(false);
    }
  };

  const toggleFormat = (f: string) =>
    set({ formats: choices.formats.includes(f) ? choices.formats.filter((x) => x !== f) : [...choices.formats, f] });
  const ready = items.length > 0 && choices.formats.length > 0 && uploading.length === 0;

  return (
    <div className="page simple">
      <div className="hero">
        <h1>Convert a document</h1>
        <p>{options?.tagline ?? ""}</p>
      </div>

      {error && <div className="banner error">{error}</div>}

      <section className="step">
        <div className="step-title"><span className="step-num">1</span> Add documents</div>
        <div className={`drop${over ? " over" : ""}${items.length ? " has" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files); }}>
          {items.length === 0 && uploading.length === 0 ? (
            <div className="drop-empty">
              <div className="drop-icon" aria-hidden>⇪</div>
              <strong>Drop PDFs, scans, Word, PowerPoint or images here</strong>
              <span className="muted">They stay on this computer.</span>
            </div>
          ) : (
            <ul className="picked">
              {items.map((item, n) => (
                <li key={n}>
                  <FileIcon name={itemName(item)} folder={item.kind === "path" && item.folder} />
                  <span className="ellipsis grow" title={itemName(item)}>{item.kind === "url" ? item.url : item.name ?? itemName(item)}</span>
                  {item.kind === "upload" && item.size != null && <span className="muted small">{bytes(item.size)}</span>}
                  {item.kind === "path" && item.folder && <span className="muted small">whole folder</span>}
                  <button className="ghost small" onClick={() => setItems(items.filter((_, i) => i !== n))} aria-label={`Remove ${itemName(item)}`}>✕</button>
                </li>
              ))}
              {uploading.map((name, n) => (
                <li key={`u${n}`} className="muted"><FileIcon name={name} /><span className="ellipsis grow">{name}</span><span className="small">Adding…</span></li>
              ))}
            </ul>
          )}
          <div className="drop-actions">
            <button className="primary" onClick={chooseFiles}>Choose files…</button>
            {options?.native_dialogs && <button onClick={chooseFolder}>Choose a folder…</button>}
            <button className="ghost" onClick={() => setUrl(url === null ? "" : null)}>From a web address</button>
          </div>
          {url !== null && (
            <div className="row" style={{ marginTop: 10, flexWrap: "nowrap" }}>
              <input autoFocus type="url" value={url} placeholder="https://example.com/report.pdf" onChange={(e) => setUrl(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addUrl()} />
              <button onClick={addUrl} disabled={!url.trim()}>Add</button>
            </div>
          )}
          <input ref={fileRef} type="file" multiple hidden onChange={(e) => { upload(e.target.files ?? []); e.target.value = ""; }} />
        </div>
      </section>

      <section className="step">
        <div className="step-title"><span className="step-num">2</span> Save as</div>
        <div className="format-grid" role="group" aria-label="Save as">
          {Object.entries(options?.formats ?? {}).map(([key, label]) => {
            const on = choices.formats.includes(key);
            const info = FORMAT_INFO[key];
            const locked = options && !options.plan.features[key] && key in options.plan.features;
            return (
              <button key={key} className={`format${on ? " on" : ""}`} aria-pressed={on} onClick={() => toggleFormat(key)} disabled={!!locked}>
                <span className="format-badge" style={{ background: info?.color }}>{info?.ext}</span>
                <span className="format-label">{label}</span>
                <span className="format-note">{info?.note}</span>
                {on && <span className="format-check" aria-hidden>✓</span>}
              </button>
            );
          })}
        </div>

        <button className="link more-toggle" onClick={() => setMore(!more)} aria-expanded={more}>
          {more ? "▾" : "▸"} More options
          {!more && (choices.scan !== "auto" || choices.language || choices.pages || choices.pictures !== "keep") && <span className="badge accent">changed</span>}
        </button>
        {more && options && (
          <div className="more">
            <label className="field">
              <span className="field-label">Scanned pages and photos</span>
              <select value={choices.scan} onChange={(e) => set({ scan: e.target.value })}>
                {Object.entries(options.scan).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
              <span className="field-help">Automatic reads text in images where it finds them. Choose Always for scans or phone photos of pages.</span>
            </label>
            <label className="field">
              <span className="field-label">Language of scanned text</span>
              <select value={choices.language} onChange={(e) => set({ language: e.target.value })}>
                {Object.entries(options.languages).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
            <label className="field">
              <span className="field-label">Pages</span>
              <input value={choices.pages} placeholder="All pages" onChange={(e) => set({ pages: e.target.value })} />
              <span className="field-help">One page (5) or a range (2-10).</span>
            </label>
            <label className="field">
              <span className="field-label">Pictures</span>
              <select value={choices.pictures} onChange={(e) => set({ pictures: e.target.value as Choices["pictures"] })}>
                <option value="keep">Keep them</option>
                <option value="describe">Keep them and describe them with AI (slower)</option>
                <option value="drop">Leave them out</option>
              </select>
            </label>
          </div>
        )}
      </section>

      <section className="convert-bar">
        <div className="muted small">
          Saves to <span className="mono" title={options?.save_to}>{options?.save_to_label ?? "…"}</span>{" "}
          {options?.native_dialogs ? <button className="link small" onClick={changeFolder}>Change…</button> : <a href={href({ page: "preferences" })}>Change…</a>}
        </div>
        <button className="primary big" onClick={convert} disabled={!ready || starting}>
          {starting ? "Starting…" : items.length > 1 ? `Convert ${plural(items.length, "document")}` : "Convert"}
        </button>
      </section>

      {recent.length > 0 && (
        <section className="recent">
          <div className="row"><h2 style={{ margin: 0 }}>Recent</h2><span className="grow" /><a href={href({ page: "history" })}>All conversions</a></div>
          <ul>
            {recent.map((r) => (
              <li key={r.id}>
                <a href={href({ page: "job", id: r.id })} className="row" style={{ flexWrap: "nowrap" }}>
                  <span className={`status ${r.status}`} aria-label={r.status} />
                  <span className="ellipsis grow">{r.title}</span>
                  <span className="muted small nowrap">{(r.finish?.formats ?? []).map((f) => FORMAT_INFO[f]?.ext).join(" · ")}</span>
                  <span className="muted small nowrap">{ago(r.created)}</span>
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
